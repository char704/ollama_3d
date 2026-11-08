"""Shared configuration for the API, launcher and registered WebUI tool."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / 'config.json'
ROUTES = {'files': '/files', 'export': '/excel/export-vbom',
          'apply': '/blender/apply-vbom', 'result': '/results/{run_id}'}


def load(path=None):
    path = Path(path or CONFIG_FILE).resolve()
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if config.get('mode') not in ('demo', 'company'):
        raise ValueError('config.json: mode must be demo or company')
    for key in ('api_port', 'webui_port'):
        value = config['services'][key]
        if type(value) is not int or not 1024 <= value <= 65535:
            raise ValueError(f'config.json: invalid {key}')
    if config['services']['api_port'] == config['services']['webui_port']:
        raise ValueError('API and WebUI ports must be different')
    parsed = urlparse(config['services']['ollama_url'])
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('This local prototype requires a local Ollama HTTP URL')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('ollama_url must be a base URL without credentials or a path')
    if (parsed.port or 80) in (config['services']['api_port'], config['services']['webui_port']):
        raise ValueError('Ollama, API and WebUI must use different ports')
    if not config['ollama']['model'].strip():
        raise ValueError('config.json: ollama.model is required')
    for key in ('inputs', 'outputs', 'default_model'):
        if not isinstance(config['paths'][key], str) or not config['paths'][key].strip():
            raise ValueError(f'config.json: paths.{key} is required')
    config['_root'] = path.parent
    if config['mode'] == 'company':
        for operation in ROUTES:
            endpoint(config, operation)
    return config


def resolve(config, value):
    path = Path(os.path.expandvars(value)).expanduser()
    return (path if path.is_absolute() else config['_root'] / path).resolve()


def data_path(config, key):
    return resolve(config, config['paths'][key])


def service_url(config, name):
    if name == 'ollama':
        return config['services']['ollama_url'].rstrip('/')
    return f"http://127.0.0.1:{config['services'][name + '_port']}"


def endpoint(config, operation):
    if config['mode'] == 'demo':
        return {'url': service_url(config, 'api') + ROUTES[operation], 'token_env': ''}
    item = config['company_api'].get(operation, {})
    url = item.get('url', '')
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f'config.json: company_api.{operation}.url must be an HTTP(S) URL without credentials')
    if operation == 'result' and '{run_id}' not in url:
        raise ValueError('company_api.result.url must contain {run_id}')
    return item


def scoped_path(config, value, default=None):
    path = resolve(config, str(value or default))
    root = config['_root'].resolve()
    allowed = [root, data_path(config, 'inputs'), data_path(config, 'outputs'),
               *[resolve(config, p) for p in config['paths'].get('allowed_roots', [])]]
    if path != data_path(config, 'default_model') and not any(path.is_relative_to(p) for p in allowed):
        raise ValueError('Path must be inside the project or a configured input/output/allowed directory')
    if path.is_relative_to(root):
        if any(p.startswith('.') or p.casefold() in ('webui-data', 'runtime', 'archive', 'logs')
               for p in path.relative_to(root).parts):
            raise ValueError('This directory is reserved for application data')
    return path
