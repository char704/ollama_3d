"""Allowlisted Blender operator discovery and execution."""
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path

import psutil

from .common import BLENDER, CONFIG, DEFAULT_MODEL, ROOT, log, read_json, scoped_path, write_json

CALLS = ROOT / 'runtime' / 'operator-calls'
PROCESSES = ROOT / 'runtime' / 'operator-processes.json'
_lock = threading.Lock()


def _configured(operator_id=None):
    items = [item for item in CONFIG.get('blender_operators', []) if item.get('enabled', True)]
    if operator_id is None:
        return items
    item = next((item for item in items if item['id'] == operator_id), None)
    if item is None:
        raise ValueError('Unknown or disabled Blender operator: ' + operator_id)
    return item


def list_operators():
    operators = []
    for item in _configured():
        operators.append({
            'id':item['id'], 'name':item['name'], 'description':item['description'],
            'operator':item['operator'], 'execution_mode':item['execution_mode'],
            'load_model':bool(item.get('load_model')), 'parameters':item.get('parameters', {}),
        })
    result = {
        'ok': True,
        'operators': operators,
        'usage': 'Choose the operator whose description matches the request, then call run_blender_addon with its exact id and only documented parameters.',
    }
    log('list_blender_addons', {'result':result})
    return result


def _valid_value(name, value, spec):
    kind = spec['type']
    valid = ((kind == 'string' and isinstance(value, str)) or
             (kind == 'integer' and type(value) is int) or
             (kind == 'number' and type(value) in (int, float)) or
             (kind == 'boolean' and type(value) is bool))
    if not valid:
        raise ValueError(f'Parameter {name} must be {kind}')
    if kind == 'string' and len(value) > 4096:
        raise ValueError(f'Parameter {name} is too long')
    if 'enum' in spec and value not in spec['enum']:
        raise ValueError(f'Parameter {name} must be one of {spec["enum"]}')
    if 'minimum' in spec and value < spec['minimum']:
        raise ValueError(f'Parameter {name} must be at least {spec["minimum"]}')
    if 'maximum' in spec and value > spec['maximum']:
        raise ValueError(f'Parameter {name} must be at most {spec["maximum"]}')
    return value


def _parameters(item, supplied):
    if not isinstance(supplied, dict):
        raise ValueError('parameters must be a JSON object')
    specs = item.get('parameters', {})
    unknown = sorted(set(supplied) - set(specs))
    if unknown:
        raise ValueError('Unknown parameters: ' + ', '.join(unknown))
    result = {}
    for name, spec in specs.items():
        if name in supplied:
            value = supplied[name]
        elif 'default' in spec:
            value = spec['default']
        elif spec.get('required'):
            raise ValueError('Missing required parameter: ' + name)
        else:
            continue
        result[name] = _valid_value(name, value, spec)
    return result


def _running(operator_id):
    if not PROCESSES.is_file():
        return None
    state = read_json(PROCESSES).get(operator_id)
    if not state:
        return None
    try:
        process = psutil.Process(state['pid'])
        if abs(process.create_time() - state['create_time']) > 1:
            return None
        if Path(process.exe()).resolve() != BLENDER.resolve():
            return None
        return state
    except (psutil.Error, OSError, KeyError):
        return None


def _remember(operator_id, process, result):
    state = read_json(PROCESSES) if PROCESSES.is_file() else {}
    state[operator_id] = {
        'pid': process.pid,
        'create_time': psutil.Process(process.pid).create_time(),
        'status': 'running',
        'operator': result['operator'],
        'parameters': result['parameters'],
    }
    write_json(PROCESSES, state)
    return state[operator_id]


def run_operator(operator_id, parameters=None, model_path=''):
    item = _configured(operator_id)
    parameters = _parameters(item, parameters or {})
    if not BLENDER.is_file():
        raise FileNotFoundError('Blender executable not found: ' + str(BLENDER))
    model = None
    if item.get('load_model'):
        model = scoped_path(model_path, DEFAULT_MODEL)
        if model.suffix.lower() != '.blend' or not model.is_file():
            raise ValueError('Choose an existing Blender model')
    with _lock:
        if item['execution_mode'] == 'persistent':
            running = _running(operator_id)
            if running:
                result = {'ok':True, 'status':'already_running', 'operator_id':operator_id,
                          'pid':running['pid'], 'operator':item['operator'],
                          'parameters':running['parameters']}
                log('run_blender_addon', {'arguments':{'operator_id':operator_id}, 'result':result})
                return result
        request_id = uuid.uuid4().hex
        CALLS.mkdir(parents=True, exist_ok=True)
        request_file = CALLS / (request_id + '.request.json')
        report_file = CALLS / (request_id + '.result.json')
        request = {'operator_id':operator_id, 'operator':item['operator'], 'parameters':parameters,
                   'execution_mode':item['execution_mode'], 'save_after':bool(item.get('save_after'))}
        write_json(request_file, request)
        command = [str(BLENDER)]
        if item['execution_mode'] == 'one_shot':
            command.append('--background')
        if model:
            command.append(str(model))
        command += ['--python-exit-code', '1', '--python', str(ROOT / 'blender' / 'run_operator.py'),
                    '--', str(request_file), str(report_file)]
        log_file = ROOT / 'logs' / ('operator-' + operator_id + '.log')
        log_file.parent.mkdir(exist_ok=True)
        stream = log_file.open('a', encoding='utf-8')
        if item['execution_mode'] == 'one_shot':
            try:
                completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                           timeout=item.get('timeout_seconds', 30),
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            finally:
                stream.close()
            if completed.returncode and not report_file.is_file():
                raise RuntimeError('Blender operator failed. See ' + str(log_file))
        else:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            stream.close()
            deadline = time.monotonic() + item.get('timeout_seconds', 30)
            while time.monotonic() < deadline and not report_file.is_file():
                if process.poll() is not None:
                    break
                time.sleep(0.25)
            if not report_file.is_file():
                raise RuntimeError('Blender did not confirm the operator. See ' + str(log_file))
        result = read_json(report_file)
        if not result.get('ok'):
            raise RuntimeError(result.get('error', 'Blender operator failed') + '. See ' + str(log_file))
        result.update(operator_id=operator_id, request_id=request_id, model_path=str(model) if model else '')
        if item['execution_mode'] == 'persistent':
            result.update(_remember(operator_id, process, result))
        log('run_blender_addon', {'arguments':{'operator_id':operator_id, 'parameters':parameters,
                                               'model_path':str(model) if model else ''}, 'result':result})
        return result
