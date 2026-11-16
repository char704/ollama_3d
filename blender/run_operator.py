"""Executed inside Blender. Calls one pre-approved bpy.ops operator."""
import json
import os
import sys
import traceback

import bpy


def write(path, value):
    temporary = path + '.tmp'
    with open(temporary, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


request_file, report_file = sys.argv[sys.argv.index('--') + 1:]
with open(request_file, encoding='utf-8') as stream:
    request = json.load(stream)

try:
    group_name, operator_name = request['operator'].split('.')
    group = getattr(bpy.ops, group_name, None)
    operator = getattr(group, operator_name, None) if group else None
    if operator is None:
        raise RuntimeError('Operator is not registered in this Blender profile: bpy.ops.' + request['operator'])
    status = set(operator(**request['parameters']))
    accepted = {'FINISHED', 'RUNNING_MODAL'} if request['execution_mode'] == 'persistent' else {'FINISHED'}
    if not status.intersection(accepted):
        raise RuntimeError('Operator returned ' + repr(status))
    if request.get('save_after'):
        bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath)
    write(report_file, {'ok':True, 'status':'running' if 'RUNNING_MODAL' in status else 'completed',
                        'operator':request['operator'], 'parameters':request['parameters'],
                        'blender_result':sorted(status)})
except Exception as exc:
    write(report_file, {'ok':False, 'status':'failed', 'operator':request.get('operator'),
                        'error':str(exc), 'traceback':traceback.format_exc()})
    if request.get('execution_mode') == 'persistent':
        bpy.ops.wm.quit_blender()
    raise
