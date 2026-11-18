# Ollama 3D — Excel Add-in → VBOM → Blender Add-on

## Trạng thái hiện tại

Project đã có workflow và tool gọi từ Open WebUI, nhưng phần tích hợp thật vẫn chưa hoàn tất:

- `adapters/excel.py` hiện dùng `openpyxl` để tự sinh VBOM. **Chưa gọi Excel add-in.**
- `blender/apply_vbom.py` hiện gọi add-on Blender demo. **Chưa gọi add-on công ty.**

Muốn chạy production phải thay đúng hai adapter này bằng lệnh của add-in/add-on thật.

## Tool được gọi như thế nào

Với yêu cầu Excel → Blender, Ollama chỉ gọi **một tool**:

```text
run_bom_pipeline(excel_path, model_path, output_dir, open_result)
```

Luồng thực thi:

```text
Open WebUI
  → webui_tool.py: run_bom_pipeline
  → POST /workflows/bom
  → workflows/bom_pipeline.py
      1. adapters/excel.py     → gọi Excel add-in → xuất VBOM
      2. adapters/blender.py   → mở Blender
      3. blender/apply_vbom.py → gọi Blender add-on → lưu và kiểm tra file
```

Không cần để Ollama tự gọi từng bước Excel và Blender. Python workflow chịu trách nhiệm chạy đúng thứ tự, timeout, trạng thái và kiểm chứng kết quả.

`tool-library/blender/*.json` chỉ dành cho các operator Blender chạy độc lập. Không sửa thư mục này để thay bước Excel → VBOM của workflow chính.

## 1. Cài đặt

```powershell
git clone https://github.com/char704/ollama_3d.git
cd ollama_3d
.\Install.cmd
.\Open-WebUI.cmd
```

Mở <http://127.0.0.1:8080>, chọn **Excel → Blender Demo** và tạo chat mới.

## 2. Yêu cầu

- Windows 10/11.
- WinGet và Internet trong lần cài đầu.
- Excel cùng add-in xuất VBOM đã được cài và bật.
- Blender cùng add-on cần gọi đã được cài và bật.
- Quyền cài Ollama, Blender và Python 3.12.

## 3. Sau khi cài cần sửa gì

Sửa `config.json`:

```json
"paths": {
  "inputs": "D:/BOM",
  "outputs": "D:/KetQua",
  "default_model": "D:/Models/product.blend",
  "blender_exe": "C:/Program Files/Blender Foundation/Blender 4.3/blender.exe",
  "allowed_roots": []
}
```

- `inputs`: thư mục Excel và model đầu vào.
- `outputs`: nơi lưu VBOM và file Blender kết quả.
- `default_model`: model mặc định.
- `blender_exe`: đúng file `blender.exe` đang có add-on công ty.
- `allowed_roots`: thêm thư mục ngoài project nếu workflow cần truy cập.

Sau khi sửa:

```powershell
.\Stop.cmd
.\Open-WebUI.cmd
```

## 4. Thay lệnh Excel add-in và Blender add-on

### Excel add-in

Vị trí phải thay: `adapters/excel.py`, hàm `export_excel()`.

Hàm này phải thực hiện đúng workflow:

```text
mở workbook đầu vào
→ gọi chức năng Export VBOM của add-in
→ chờ add-in chạy xong
→ kiểm tra file VBOM tồn tại
→ trả về run_id và vbom_path
```

Để viết được lệnh gọi thật, cần lấy **automation entry point** của add-in:

| Loại add-in | Thông tin cần lấy |
|---|---|
| VBA / `.xlam` | Tên macro đầy đủ, ví dụ `'Addin.xlam'!Module.ExportVBOM` |
| COM / VSTO add-in | `ProgID`, method công khai và danh sách tham số |
| Add-in có CLI/API | File `.exe` hoặc URL, tham số input/output và cách đọc kết quả |
| Chỉ có nút trên Ribbon | Cần đội viết add-in cung cấp API/macro; tên nút không phải lệnh gọi |

Cách xác định loại add-in: mở Excel → **File → Options → Add-ins**. Sau đó lấy tài liệu automation hoặc hỏi đội phát triển add-in. Chỉ biết đường dẫn `EXCEL.EXE` là chưa đủ để gọi chức năng Export.

Khi có entry point, thay đoạn `openpyxl` trong `export_excel()` bằng bridge tương ứng:

- VBA/COM: gọi Excel qua `pywin32`.
- CLI: gọi bằng `subprocess.run()`.
- HTTP API: gọi endpoint từ adapter hoặc đổi `workflow.export.provider` sang `http`.

Không giữ đoạn tự tạo XML hiện tại khi chuyển sang add-in thật. VBOM phải là file do add-in xuất ra.

### Blender add-on

Đường dẫn Blender nằm ở:

```text
config.json → paths.blender_exe
```

Lệnh mở Blender nằm trong `adapters/blender.py`, biến `command` của `apply_vbom()`:

```text
blender.exe --background model.blend
  --python blender/apply_vbom.py
  -- materials.vbom output.blend verification.json
```

Operator được gọi trong `blender/apply_vbom.py`. Thay operator demo:

```python
bpy.ops.demo.import_vbom(filepath=vbom)
```

bằng operator thật do add-on công ty cung cấp:

```python
bpy.ops.<module>.<operator>(filepath=vbom)
```

Tên chính xác lấy từ source hoặc tài liệu add-on Blender. Add-on phải được bật trong đúng Blender profile mà `paths.blender_exe` đang sử dụng.

## 5. Kiểm tra project đã cập nhật chưa

```powershell
git fetch origin
git status --short --branch
git log --oneline origin/main..HEAD
git log --oneline HEAD..origin/main
```

Project đã đồng bộ khi `git status` không có file thay đổi, branch không `ahead/behind` và hai lệnh `git log` không trả kết quả.

Kiểm tra code sau khi cài:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\Status.cmd
```

## Thông tin còn thiếu để nối add-in thật

Cần cung cấp bốn thông tin sau:

1. Tên và loại Excel add-in.
2. Macro, `ProgID` + method, CLI hoặc API dùng để Export VBOM.
3. Tham số đầu vào/đầu ra của lệnh Export.
4. Tên `bpy.ops...` của Blender add-on.

Khi chưa có bốn thông tin này, project chỉ chạy được workflow demo sinh VBOM bằng code.
