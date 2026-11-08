// Compatibility entry point for the previous Node.js smoke test.
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
const result = spawnSync(root + '.venv/Scripts/python.exe', [root + 'tests/smoke_webui.py'], {stdio:'inherit'});
process.exit(result.status ?? 1);
