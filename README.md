# Ollama 3D — Excel → VBOM → Blender

Chạy trên Windows: nhập yêu cầu trong Open WebUI, Ollama chọn tool, Python chạy workflow Excel → VBOM → Blender → kiểm chứng kết quả.

> Bản hiện tại là demo. Excel được đọc bằng `openpyxl`, chưa gọi Excel/add-in thật. Blender dùng add-on mẫu trong project.

## 1. Cài đặt

```powershell
git clone https://github.com/char704/ollama_3d.git
cd ollama_3d
.\Install.cmd
.\Open-WebUI.cmd
```

Mở <http://127.0.0.1:8080>, chọn **Excel → Blender Demo**, tạo chat mới và thử:

```text
Dùng Footwear_BOM.xlsx, xuất VBOM rồi áp vật liệu và màu vào model mặc định. Mở kết quả.
```

- Kiểm tra: `Status.cmd`
- Dừng: `Stop.cmd`

## 2. Yêu cầu

- Windows 10/11 và Internet trong lần cài đầu.
- WinGet (Microsoft App Installer).
- Quyền cài phần mềm; Blender có thể yêu cầu quyền Administrator.
- Dung lượng đủ cho Ollama, model `qwen2.5:7b`, Blender và Open WebUI.

`Install.cmd` tự thiết lập `uv`, Python 3.12 trong `.venv`, package trong `requirements.txt`, Ollama, model AI, Blender và Open WebUI. Không cần Node.js.

Không copy `.venv` từ máy khác. Mỗi máy phải chạy lại `Install.cmd`.

## 3. Sau khi tải về cần sửa gì

Sửa **`config.json`** trước khi chạy:

```json
{
  "paths": {
    "inputs": "D:/DuLieu/BOM",
    "outputs": "D:/DuLieu/KetQua",
    "default_model": "D:/DuLieu/Models/product.blend",
    "blender_exe": "C:/Program Files/Blender Foundation/Blender 4.3/blender.exe",
    "allowed_roots": []
  },
  "ollama": {
    "model": "qwen2.5:7b",
    "executable": ""
  }
}
```

| Mục | Cần điền |
|---|---|
| `paths.inputs` | Thư mục chứa `.xlsx` và `.blend` |
| `paths.outputs` | Thư mục lưu kết quả |
| `paths.default_model` | Model dùng khi chat không chỉ định file |
| `paths.blender_exe` | Đường dẫn đầy đủ tới `blender.exe` |
| `paths.allowed_roots` | Thư mục ngoài project mà tool được phép đọc/ghi |
| `ollama.model` | Model Ollama muốn dùng |
| `ollama.executable` | Để trống để tự tìm; chỉ điền khi Ollama nằm ở vị trí riêng |
| `services.api_port` / `webui_port` | Đổi nếu cổng `8090` / `8080` đang bị dùng |

Trong JSON, dùng `/` hoặc escape `\` thành `\\`.

Dữ liệu demo yêu cầu sheet `BOM` với đúng các cột:

```text
Object | Material | ColorHex | Roughness | Metallic
```

Sau khi sửa cấu hình:

```powershell
.\Stop.cmd
.\Open-WebUI.cmd
```

## 4. Sửa lệnh gọi Blender và Excel

### Blender

Đường dẫn Blender: `config.json → paths.blender_exe`.

Lệnh chạy nằm trong **`adapters/blender.py`**, biến `command` trong `apply_vbom()`:

```text
blender.exe --background --factory-startup model.blend
  --python-exit-code 1
  --python blender/apply_vbom.py
  -- materials.vbom output.blend verification.json
```

- Đổi Python script/tham số Blender: sửa danh sách `command` trong `adapters/blender.py`.
- Đổi add-on/operator áp VBOM: sửa `blender/apply_vbom.py`.

Demo hiện gọi:

```python
bpy.ops.demo.import_vbom(filepath=vbom)
```

Thay bằng operator thật của công ty, ví dụ:

```python
bpy.ops.company.import_vbom(filepath=vbom)
```

Operator tùy chọn cho Ollama nằm trong **`tool-library/blender/*.json`**. Trường `operator` là phần đứng sau `bpy.ops.`. Sau khi sửa, khởi động lại project.

### Excel

Hiện project **không mở `EXCEL.EXE` và không gọi add-in Excel**. `adapters/excel.py` dùng `openpyxl` đọc `.xlsx` rồi tự tạo VBOM. Không có “lệnh Excel” sẵn để chỉ đổi đường dẫn.

Chọn một trong hai cách tích hợp sau.

#### Có HTTP API

Sửa bước `export` trong `config.json`:

```json
"workflow": {
  "files": {"provider": "local"},
  "export": {
    "provider": "http",
    "url": "http://127.0.0.1:9001/export-vbom",
    "token_env": "EXCEL_API_TOKEN"
  },
  "apply": {"provider": "local"},
  "result": {"provider": "local"}
}
```

API nhận `excel_path`, `output_dir` và trả tối thiểu:

```json
{
  "ok": true,
  "status": "exported",
  "run_id": "...",
  "vbom_path": "D:/.../materials.vbom"
}
```

#### Có CLI, VBA macro hoặc Excel add-in

Thay `read_bom()` / `export_excel()` trong **`adapters/excel.py`** bằng lệnh thật. Ví dụ CLI:

```python
command = [
    r"C:\Program Files\Company\VbomExporter.exe",
    "--input", str(source),
    "--output", str(vbom),
]
subprocess.run(command, check=True, timeout=180)
```

Nếu gọi VBA macro, thêm `pywin32` vào `requirements.txt`, chạy lại `Install.cmd`, rồi dùng Excel COM:

```python
import win32com.client

excel = win32com.client.DispatchEx("Excel.Application")
excel.Visible = False
workbook = excel.Workbooks.Open(str(source))
try:
    excel.Application.Run("'CompanyAddin.xlam'!Module1.ExportVBOM", str(source), str(vbom))
finally:
    workbook.Close(False)
    excel.Quit()
```

### Lấy đường dẫn và lệnh gọi Excel

Lấy đường dẫn `EXCEL.EXE`:

```powershell
$keys = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe',
  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\excel.exe',
  'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe'
)
$keys | ForEach-Object { (Get-ItemProperty $_ -ErrorAction SilentlyContinue).'(default)' }
```

Lấy tên VBA macro:

1. Mở Excel, nhấn `Alt+F11`.
2. Tìm workbook/add-in chứa `Public Sub ...`.
3. Ghi lại tên add-in, module và procedure.
4. Dùng dạng `'CompanyAddin.xlam'!Module1.ExportVBOM`.

Liệt kê COM add-in và `ProgId`:

```powershell
$excel = New-Object -ComObject Excel.Application
$excel.COMAddIns | Select-Object Description, ProgId, Connect
$excel.Quit()
```

`EXCEL.EXE` chỉ mở Excel, không phải lệnh gọi nút trên Ribbon. Nếu add-in không có VBA macro/CLI công khai, cần lấy `ProgId`, method/API và tham số từ đội phát triển hoặc tài liệu của add-in; không thể suy ra từ tên nút.

## 5. Kiểm tra project và GitHub

Kiểm tra code/config:

```powershell
.\Install.cmd
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\Status.cmd
```

Kiểm tra local và GitHub:

```powershell
git fetch origin
git status --short --branch
git log --oneline origin/main..HEAD
git log --oneline HEAD..origin/main
```

Project đã đồng bộ khi:

- `git status` không liệt kê file thay đổi;
- branch không có `ahead` hoặc `behind`;
- hai lệnh `git log` không trả dòng nào.

Đẩy README lên GitHub:

```powershell
git add README.md
git commit -m "Rewrite setup and integration README"
git push origin main
```

Không commit `.venv`, `.python`, `webui-data`, `runtime`, `logs`, dữ liệu công ty hoặc token/API key.

Kết quả mỗi lượt chạy nằm trong `paths.outputs/<run_id>/`. Workflow cấp cao nằm ở `workflows/bom_pipeline.py`; trạng thái được lưu trong `runtime/workflows/`. Yêu cầu giống nhau được dùng lại, chỉ chạy mới khi người dùng yêu cầu rõ.
