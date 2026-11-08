from pathlib import Path
import datetime
import json
import re
from project_config import load, data_path, scoped_path as configured_path, resolve

ROOT = Path(__file__).resolve().parents[1]
CONFIG = load()
INPUTS = data_path(CONFIG, 'inputs')
RUNS = data_path(CONFIG, 'outputs')
DEFAULT_MODEL = data_path(CONFIG, 'default_model')
STATE = ROOT / 'runtime' / 'results'
BLENDER = resolve(CONFIG, CONFIG['paths']['blender_exe'])

def scoped_path(value, default=None):
    return configured_path(CONFIG, value, default)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def log(action, data):
    folder = ROOT / 'logs'
    folder.mkdir(exist_ok=True)
    with (folder / 'tool-calls.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'time':datetime.datetime.now().astimezone().isoformat(), 'tool':action, **data}, ensure_ascii=False)+'\n')

def save_result(run_id, **updates):
    if not re.fullmatch(r'[a-f0-9]{32}', run_id): raise ValueError('Invalid run_id')
    path = STATE / (run_id+'.json')
    result = read_json(path) if path.exists() else {'run_id':run_id}
    result.update(updates)
    result['updated_at'] = datetime.datetime.now().astimezone().isoformat()
    write_json(path, result)
    return result

def get_result(run_id):
    if not re.fullmatch(r'[a-f0-9]{32}', run_id): raise ValueError('Invalid run_id')
    path = STATE / (run_id+'.json')
    if not path.is_file(): raise FileNotFoundError('Run not found')
    return read_json(path)

def list_files(input_dir=''):
    folder = scoped_path(input_dir, INPUTS)
    if not folder.is_dir(): raise FileNotFoundError('Input directory not found')
    result = {'ok':True, 'directory':str(folder),
              'excel_files':[str(p.resolve()) for p in sorted(folder.glob('*.xlsx')) if not p.name.startswith('~$')],
              'blender_models':[str(p.resolve()) for p in sorted(folder.glob('*.blend'))],
              'next_step':'Export the requested Excel file; use exact paths returned here.'}
    log('list_demo_files', {'result':result})
    return result
