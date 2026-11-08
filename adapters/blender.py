"""Blender process adapter. The company operator belongs in blender/apply_vbom.py."""
import hashlib
import subprocess
import threading
from .common import ROOT, DEFAULT_MODEL, BLENDER, scoped_path, read_json, save_result, get_result, log

_lock = threading.Lock()

def apply_vbom(vbom_path, model_path='', open_window=True):
    vbom = scoped_path(vbom_path)
    model = scoped_path(model_path, DEFAULT_MODEL)
    if vbom.name != 'materials.vbom' or not vbom.is_file() or not (vbom.parent / 'manifest.json').is_file():
        raise ValueError('Use the VBOM returned by the Excel API')
    if model.suffix.lower() != '.blend' or not model.is_file(): raise ValueError('Choose an existing Blender model')
    manifest = read_json(vbom.parent / 'manifest.json')
    run_id = manifest.get('run_id', vbom.parent.name)
    if manifest.get('vbom_sha256') and hashlib.sha256(vbom.read_bytes()).hexdigest() != manifest['vbom_sha256']:
        raise ValueError('VBOM changed since export; export the Excel again')
    if not BLENDER.is_file(): raise FileNotFoundError('Blender executable not found: '+str(BLENDER))
    output, report = vbom.parent / 'Sneaker_Applied.blend', vbom.parent / 'verification.json'
    if output.resolve() == model: raise ValueError('Output must not overwrite the input model')
    if not _lock.acquire(blocking=False): raise RuntimeError('Blender is busy; wait for the current request to finish')
    started = False
    try:
        if output.exists():
            try: previous = get_result(run_id)
            except FileNotFoundError: previous = {}
            if previous.get('status') == 'completed' and previous.get('model_path') == str(model):
                return {**previous, 'reused_result':True}
            raise ValueError('Output already exists; export again to start a new run')
        save_result(run_id, ok=True, status='applying', vbom_path=str(vbom), model_path=str(model))
        started = True
        command = [str(BLENDER), '--background', '--factory-startup', str(model), '--python-exit-code', '1',
                   '--python', str(ROOT / 'blender' / 'apply_vbom.py'), '--', str(vbom), str(output), str(report)]
        with (vbom.parent / 'blender.log').open('w', encoding='utf-8') as stream:
            proc = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=180,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if proc.returncode or not report.is_file() or not output.is_file():
            raise RuntimeError('Blender failed. See '+str(vbom.parent / 'blender.log'))
        result = read_json(report)
        for expected in manifest['rows']:
            actual = next((r for r in result['applied'] if r['object'] == expected['object']), None)
            if not actual or any(actual[k] != expected[k] for k in ('material','color','roughness','metallic')):
                raise RuntimeError('Saved Blender result differs from the Excel BOM')
        result.update(status='completed', model_path=str(model), preview=str(vbom.parent / 'after.png'),
                      real_blender=True, company_addon=False, window_opened=False,
                      next_step='Finished. Report the saved output path; do not apply again.')
        if open_window:
            try:
                subprocess.Popen([str(BLENDER), str(output)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                result['window_opened'] = True
            except OSError as exc: result['window_error'] = str(exc)
        result = save_result(run_id, **result)
        log('apply_vbom_in_blender', {'arguments':{'vbom_path':str(vbom), 'model_path':str(model)}, 'result':result})
        return result
    except Exception as exc:
        if started: save_result(run_id, ok=False, status='failed', error=str(exc), next_step='Inspect the error and blender.log before retrying.')
        raise
    finally:
        _lock.release()
