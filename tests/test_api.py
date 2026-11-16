"""Contract checks; real Blender end-to-end tests are run via HTTP separately."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from fastapi.testclient import TestClient
from api_service import app

class ApiContract(unittest.TestCase):
    def setUp(self): self.client = TestClient(app)

    def test_files_and_schema(self):
        files = self.client.get('/files').json()
        self.assertTrue(any(p.endswith('Footwear_BOM.xlsx') for p in files['excel_files']))
        self.assertIn('/blender/apply-vbom', self.client.get('/openapi.json').json()['paths'])
        self.assertIn('/blender/operators/run', self.client.get('/openapi.json').json()['paths'])
        operators = self.client.get('/blender/operators').json()['operators']
        self.assertEqual(operators[0]['id'], 'start_rhino_server')

    def test_reject_invalid_paths_and_unknown_parameters(self):
        self.assertEqual(self.client.get('/files', params={'input_dir':'../'}).status_code, 400)
        self.assertEqual(self.client.get('/files', params={'input_dir':'webui-data'}).status_code, 400)
        self.assertEqual(self.client.post('/excel/export-vbom', json={'excel_path':'missing.xlsx'}).status_code, 400)
        self.assertEqual(self.client.post('/excel/export-vbom', json={'excel_path':'Footwear_BOM.xlsx','output_dir':'../'}).status_code, 400)
        self.assertEqual(self.client.post('/excel/export-vbom', json={'excel_path':'Footwear_BOM.xlsx','output':'ignored'}).status_code, 422)
        self.assertEqual(self.client.get('/results/not-a-run').status_code, 400)
        self.assertEqual(self.client.get('/results/'+'0'*32).status_code, 404)
        self.assertEqual(self.client.post('/blender/operators/run', json={
            'operator_id':'unknown', 'parameters':{}}).status_code, 400)

if __name__ == '__main__': unittest.main()
