"""Demo converter. Replace this implementation with the company's Excel API."""
import hashlib
import uuid
import xml.etree.ElementTree as ET
import re
from openpyxl import load_workbook
from .common import INPUTS, RUNS, scoped_path, write_json, save_result, log

def read_bom(source):
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        if 'BOM' not in workbook.sheetnames: raise ValueError('Expected a sheet named BOM')
        sheet = workbook['BOM']
        headers = [c.value for c in next(sheet.iter_rows(min_row=1, max_row=1))]
        if headers != ['Object','Material','ColorHex','Roughness','Metallic']: raise ValueError('Unexpected BOM headers')
        rows = []
        for obj, material, color, roughness, metallic in sheet.iter_rows(min_row=2, max_col=5, values_only=True):
            if not obj or isinstance(obj, str) and obj.startswith('Demo data:'): continue
            if obj not in ('Upper','Sole','Laces') or not isinstance(material, str) or not material.strip():
                raise ValueError('Unknown object or missing material')
            if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color): raise ValueError('Invalid ColorHex')
            if any(type(v) not in (int,float) or not 0 <= v <= 1 for v in (roughness, metallic)):
                raise ValueError('Invalid roughness/metallic')
            rows.append(dict(object=obj, material=material, color=color.upper(), roughness=roughness, metallic=metallic))
        if len(rows) != 3 or len({r['object'] for r in rows}) != 3: raise ValueError('Expected three unique objects: Upper, Sole, Laces')
        return rows
    finally:
        workbook.close()

def export_excel(excel_path, output_dir=''):
    if '/' not in excel_path and '\\' not in excel_path: excel_path = str(INPUTS / excel_path)
    source = scoped_path(excel_path)
    if source.suffix.lower() != '.xlsx' or not source.is_file(): raise ValueError('Choose an existing XLSX file')
    destination = scoped_path(output_dir, RUNS)
    rows = read_bom(source)
    run_id = uuid.uuid4().hex
    folder = destination / run_id
    folder.mkdir(parents=True)
    root = ET.Element('vbom', {'format':'demo-v1', 'source':source.name})
    for row in rows: ET.SubElement(root, 'item', {k:str(v) for k,v in row.items()})
    ET.indent(root)
    vbom = folder / 'materials.vbom'
    ET.ElementTree(root).write(vbom, encoding='utf-8', xml_declaration=True)
    manifest = {'run_id':run_id, 'source_excel':str(source), 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                'vbom_path':str(vbom), 'vbom_sha256':hashlib.sha256(vbom.read_bytes()).hexdigest(), 'rows':rows}
    write_json(folder / 'manifest.json', manifest)
    result = save_result(run_id, ok=True, status='exported', items=len(rows), source_excel=str(source),
                         vbom_path=str(vbom), output_dir=str(folder), format='demo-v1 XML', company_addin=False,
                         next_step='Call apply_vbom_in_blender with this exact vbom_path and the selected model_path.')
    log('export_excel_to_vbom', {'arguments':{'excel_path':str(source),'output_dir':str(destination)}, 'result':result})
    return result
