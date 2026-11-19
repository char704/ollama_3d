# Ollama3D — Qwen → Excel VBA + Blender

Demo: [YouTube](https://www.youtube.com/watch?v=GMYszBR3qgg)

Project chạy local trên Windows, cho phép Qwen điều phối Excel VBA và Blender qua allowlist. MCP phía Qwen/Open WebUI vẫn được hỗ trợ; phía Blender chỉ dùng tiến trình con ngắn hạn, không cài hoặc mở Blender MCP.

Đường điều phối mặc định là agent CLI nhỏ, không phụ thuộc MCP:

```powershell
.\.venv\Scripts\python.exe -m agent.run "Áp VBOM vào mẫu giày ..."
```

Trước khi dùng, cài hai model được cấu hình (installer không tự tải ngầm):

```powershell
ollama pull qwen3.5:4b
ollama pull qwen3.5:0.8b
```

`qwen3.5:4b` phân loại intent, chọn capability và trích tham số. Model
`qwen3.5:0.8b` chỉ trả lời hội thoại ngắn sau khi 4B đã xác nhận intent là
`chat`; nó không được định tuyến hoặc kích hoạt Blender.

- `system_status()` kiểm tra Qwen, macro VBA thật và Blender operator thật.
- `run_excel_to_blender(excel_path, model_path, output_dir)` chạy trọn workflow và kiểm chứng file `.blend` sau khi mở lại.
- `create_colored_primitive(primitive, color_hex, output_dir, size, object_name)` tạo cube, UV sphere hoặc cylinder có màu qua Blender subprocess.

Qwen chọn công việc; registry và Python quyết định chính xác macro/operator nào được phép chạy:

```text
Qwen (Open WebUI)
  → MCP http://127.0.0.1:8090/mcp
  → capabilities.json
      ├─ Excel COM → macro VBA đã đăng ký
      └─ Blender subprocess → fixed job entry → operator/bpy đã đăng ký
  → lưu proof, mở lại file và kiểm chứng kết quả
```

MCP của dự án chỉ là lớp tool giữa Open WebUI và workflow Python. Nó không nằm giữa workflow và Blender. Blender luôn chạy subprocess gọi add-on; Excel dùng COM gọi add-in VBA.

## Cài đặt

Yêu cầu Windows 10/11, Microsoft Excel đã cài, Blender và Ollama. Sau đó chạy:

```powershell
.\Install.cmd
```

Installer thực hiện và kiểm tra từng phần:

1. tạo Python 3.12 virtual environment và cài dependency đã khóa phiên bản;
2. mở Excel thật, nạp file `excel/Ollama3DProof.xlam`, gọi macro ping;
3. đóng gói và bật `ollama3d_proof_addon`; Blender chỉ dùng subprocess;
4. dùng `OLLAMA_MODELS` trong `config.json` và kiểm tra model Qwen;
5. khởi động local API/MCP và Open WebUI;
6. đăng ký model Open WebUI với các MCP tool allowlist hiện có.

Installer không bật “Trust access to the VBA project object model” và không sửa Excel Trust Center. File `.xlam` đã được build sẵn; runtime chỉ mở add-in và gọi macro công khai.

Các lần sau dùng:

```powershell
.\Open-WebUI.cmd
```

Mở <http://127.0.0.1:8080>, chọn **Ollama3D Excel → Blender**.

## Cấu hình máy

Các đường dẫn cần đúng trong `config.json`:

```json
{
  "paths": {
    "default_model": "inputs/Sneaker_Unassigned.blend",
    "blender_exe": "E:/Blender/blender.exe"
  },
  "ollama": {
    "model": "qwen3.5:4b",
    "router_model": "qwen3.5:4b",
    "utility_model": "qwen3.5:0.8b",
    "executable": "E:/3d/Ollama/app/ollama.exe",
    "models_directory": "E:/3d/Ollama/models"
  },
  "excel_vba": {
    "executable": "C:/Program Files/Microsoft Office/Root/Office16/EXCEL.EXE",
    "addin_path": "excel/Ollama3DProof.xlam"
  },
  "blender_addon": {
    "transport": "subprocess"
  },
  "capability_registry": "capabilities.json"
}
```

Đường dẫn truyền cho các tool phải là đường dẫn tuyệt đối và nằm trong project hoặc `paths.allowed_roots`.

## Kiểm tra theo giai đoạn

```powershell
# Cấu hình, dependency và file integration
.\.venv\Scripts\python.exe manage.py check

# Unit/integration contract tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v

# MCP protocol gọi Excel VBA và Blender thật
.\.venv\Scripts\python.exe tests\smoke_mcp.py

# Qwen chọn đúng tool, không gọi tool khi không cần, và chạy workflow thật
.\.venv\Scripts\python.exe tests\smoke_webui_mcp.py

# Trạng thái dịch vụ
.\Status.cmd
```

Chứng cứ của bài test Qwen được lưu tại `evidence/webui-mcp-smoke.json`. Mỗi lần chạy tạo thư mục riêng trong `outputs/<run_id>/`; workflow Excel chứa proof từ Excel, proof từ Blender, verification và `result.blend`, còn primitive chứa `primitive-proof.json` và file `.blend`.

## Quy tắc chọn tool

- Hỏi trạng thái/phiên bản/sẵn sàng → `system_status`.
- Yêu cầu xử lý và có đủ ba đường dẫn tuyệt đối → `run_excel_to_blender`.
- Yêu cầu tạo cube/UV sphere/cylinder có màu và có output directory → `create_colored_primitive`.
- Thiếu đường dẫn → Qwen phải hỏi lại, không tự đoán.
- Câu hỏi giải thích → không gọi tool.

Macro và Blender add-on không được đưa trực tiếp thành hàng loạt tool cho LLM. MCP chỉ công bố workflow cấp cao nên add-in/add-on trùng tên không thể khiến Qwen tự chọn nhầm operator hoặc macro.

Mỗi tác vụ mở một Blender background process, đọc `job.json` qua entry point cố định và đóng sau khi ghi `result.json`. Dispatch chỉ chứa các operation đã định trước; tham số không được biến thành mã Python.

## Capability registry

[`capabilities.json`](capabilities.json) giữ các tool lõi và entry cũ. Blender add-on mới dùng pack trong `addons/<module>/`; registry tự merge và tự nạp lại khi `addon.json`, `docs.md` hoặc workflow thay đổi, không cần restart.

Quy trình thêm add-on đã cài trong Blender:

```powershell
.\.venv\Scripts\python.exe manage.py addon add my_addon
.\.venv\Scripts\python.exe manage.py addon enable my_addon category.operator_name
```

Lệnh `addon add` discovery toàn bộ operator và tạo `addons/my_addon/addon.json` với mọi operator tắt mặc định. `addon enable` hoặc `addon disable` chỉ sửa metadata pack. Gỡ pack bằng cách xóa thư mục `addons/my_addon`.

Mỗi pack có dạng:

```text
addons/<module>/
  addon.json
  docs.md
  workflows/*.json
```

Ví dụ thêm một macro hoặc operator mới:

```json
{
  "id": "excel.company_export",
  "provider": "excel_vba",
  "handler": "company_export",
  "target": "'CompanyTools.xlam'!Company_Export",
  "version": "1.0.0",
  "enabled": true
}
```

Capability chỉ được chạy khi đang bật và toàn bộ dependency cũng đang bật. `manage.py check` xác minh registry, còn Open WebUI lấy allowlist public tool trực tiếp từ registry.

Để thêm operator add-on mới không cần sửa file Python hoặc `capabilities.json`: cài add-on, chạy `addon add`, xem schema được discovery, rồi bật đúng operator cần dùng.

Registry không tự động cho phép mọi macro hoặc `bpy.ops`. Thiết kế này cố ý yêu cầu handler rõ ràng để giữ ổn định, tránh xung đột tên và không đưa khả năng chạy VBA/Python tùy ý cho Qwen.

## Bảo mật và phạm vi local

- API/MCP, Ollama và Open WebUI chỉ dùng địa chỉ local.
- Blender background process được đóng sau mỗi tác vụ; không mở cổng mạng ở transport mặc định.
- Tham số được kiểm tra trước khi ghi JSON cho trusted runner.
- Workbook/model phải nằm trong project hoặc `paths.allowed_roots`.
- Internet chỉ cần khi tải dependency hoặc model; Blender không cần extension MCP.
