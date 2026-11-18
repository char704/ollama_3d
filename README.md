# Ollama3D MCP — Qwen → Excel VBA → Blender add-on
## Demo: https://www.youtube.com/watch?v=GMYszBR3qgg

Project này cung cấp một MCP server local với đúng hai tool:

- `system_status()` kiểm tra Qwen, macro VBA thật và Blender operator thật.
- `run_excel_to_blender(excel_path, model_path, output_dir)` chạy trọn workflow và kiểm chứng file `.blend` sau khi mở lại.

Qwen chỉ chọn tool. Python giữ workflow cố định để tránh chọn nhầm add-in/add-on:

```text
Qwen (Open WebUI)
  → MCP http://127.0.0.1:8090/mcp
  → Excel COM gọi 'Ollama3DProof.xlam'!ExportVBOM
  → Blender background gọi bpy.ops.ollama3d_proof.apply_vbom
  → kiểm chứng và lưu result.blend
```

## Cài đặt

Yêu cầu Windows 10/11, Microsoft Excel đã cài, Blender và Ollama. Sau đó chạy:

```powershell
.\Install.cmd
```

Installer thực hiện và kiểm tra từng phần:

1. tạo Python 3.12 virtual environment và cài dependency đã khóa phiên bản;
2. mở Excel thật, nạp file `excel/Ollama3DProof.xlam`, gọi macro ping;
3. đóng gói, cài và bật `ollama3d_proof_addon` trong đúng Blender profile;
4. dùng `OLLAMA_MODELS` trong `config.json` và kiểm tra model Qwen;
5. khởi động local API/MCP và Open WebUI;
6. đăng ký model **Excel → Blender MCP** chỉ với hai MCP tool.

Installer không bật “Trust access to the VBA project object model” và không sửa Excel Trust Center. File `.xlam` đã được build sẵn; runtime chỉ mở add-in và gọi macro công khai.

Các lần sau dùng:

```powershell
.\Open-WebUI.cmd
```

Mở <http://127.0.0.1:8080>, chọn **Excel → Blender MCP**.

## Cấu hình máy

Các đường dẫn cần đúng trong `config.json`:

```json
{
  "paths": {
    "default_model": "inputs/Sneaker_Unassigned.blend",
    "blender_exe": "E:/Blender/blender.exe"
  },
  "ollama": {
    "model": "qwen3:8b",
    "executable": "E:/3d/Ollama/app/ollama.exe",
    "models_directory": "E:/3d/Ollama/models"
  },
  "excel_vba": {
    "executable": "C:/Program Files/Microsoft Office/Root/Office16/EXCEL.EXE",
    "addin_path": "excel/Ollama3DProof.xlam"
  }
}
```

Đường dẫn truyền cho `run_excel_to_blender` phải là đường dẫn tuyệt đối và nằm trong project hoặc `paths.allowed_roots`.

## Kiểm tra theo giai đoạn

```powershell
# Cấu hình, dependency và file integration
.\.venv\Scripts\python.exe manage.py check

# Unit/integration contract tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v

# MCP protocol gọi Excel VBA và Blender add-on thật
.\.venv\Scripts\python.exe tests\smoke_mcp.py

# Qwen chọn đúng tool, không gọi tool khi không cần, và chạy workflow thật
.\.venv\Scripts\python.exe tests\smoke_webui_mcp.py

# Trạng thái dịch vụ
.\Status.cmd
```

Chứng cứ của bài test Qwen được lưu tại `evidence/webui-mcp-smoke.json`; mỗi workflow tạo thư mục riêng trong `outputs/<run_id>/` gồm proof từ Excel, proof từ Blender, verification và `result.blend`.

## Quy tắc chọn tool

- Hỏi trạng thái/phiên bản/sẵn sàng → `system_status`.
- Yêu cầu xử lý và có đủ ba đường dẫn tuyệt đối → `run_excel_to_blender`.
- Thiếu đường dẫn → Qwen phải hỏi lại, không tự đoán.
- Câu hỏi giải thích → không gọi tool.

Blender add-on không được đưa trực tiếp thành hàng loạt tool cho LLM. MCP chỉ công bố workflow cấp cao nên add-on trùng tên hoặc operator khác không thể bị Qwen gọi nhầm.
