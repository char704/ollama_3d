// Compatibility entry point. Setup/start now use Python and need no Node.js.
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root = fileURLToPath(new URL('.', import.meta.url));
const result = spawnSync(root + '.venv/Scripts/python.exe', [root + 'manage.py', 'sync'], {stdio:'inherit'});
process.exit(result.status ?? 1);
