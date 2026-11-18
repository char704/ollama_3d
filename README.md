# Ollama3D MCP — Qwen → Excel VBA + Blender MCP

Demo: [YouTube](https://www.youtube.com/watch?v=GMYszBR3qgg)

Project chạy local trên Windows, cho phép Qwen điều phối Excel VBA và Blender qua một MCP server có allowlist. Qwen chỉ nhìn thấy ba tool cấp cao:

- `system_status()` kiểm tra Qwen, macro VBA thật và Blender operator thật.
- `run_excel_to_blender(excel_path, model_path, output_dir)` chạy trọn workflow và kiểm chứng file `.blend` sau khi mở lại.
- `create_colored_primitive(primitive, color_hex, output_dir, size, object_name)` tạo cube, UV sphere hoặc cylinder có màu qua Blender MCP chính thức.

Qwen chọn công việc; registry và Python quyết định chính xác macro/operator nào được phép chạy:

```text
Qwen (Open WebUI)
  → MCP http://127.0.0.1:8090/mcp
  → capabilities.json
      ├─ Excel COM → macro VBA đã đăng ký
      └─ Blender MCP chính thức → trusted runner → operator/bpy đã đăng ký
  → lưu proof, mở lại file và kiểm chứng kết quả
```

MCP của dự án là lớp tool, quyền và workflow dành cho Qwen. Blender MCP chính thức là cầu nối thực thi bên trong Blender. Excel dùng COM làm cầu nối tới add-in VBA.

## Cài đặt

Yêu cầu Windows 10/11, Microsoft Excel đã cài, Blender và Ollama. Sau đó chạy:

```powershell
.\Install.cmd
```

Installer thực hiện và kiểm tra từng phần:

1. tạo Python 3.12 virtual environment và cài dependency đã khóa phiên bản;
2. mở Excel thật, nạp file `excel/Ollama3DProof.xlam`, gọi macro ping;
3. xác minh/cài Blender MCP chính thức v1.0.3, sau đó đóng gói và bật `ollama3d_proof_addon`;
4. dùng `OLLAMA_MODELS` trong `config.json` và kiểm tra model Qwen;
5. khởi động local API/MCP và Open WebUI;
6. đăng ký model **Excel → Blender MCP** với ba MCP tool allowlist.

Installer không bật “Trust access to the VBA project object model” và không sửa Excel Trust Center. File `.xlam` đã được build sẵn; runtime chỉ mở add-in và gọi macro công khai.

Installer tự tải gói MCP v1.0.3 từ release chính thức và chỉ cài khi SHA-256 khớp. Nếu máy chủ Blender chặn tải tự động, tải `mcp-1.0.3.zip` từ [release chính thức](https://projects.blender.org/lab/blender_mcp/releases/tag/v1.0.3) vào `runtime/vendor/` rồi chạy lại `Install.cmd`.

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

# MCP protocol gọi Excel VBA và Blender MCP thật
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

Blender MCP chính thức chỉ bind vào `127.0.0.1` trên một cổng động và Blender được đóng sau mỗi lần gọi. Qwen không nhìn thấy tool chạy Python tự do; adapter chỉ gửi runner cố định cùng dữ liệu JSON đã mã hóa, nên không thể biến tham số tool thành mã Python.

## Capability registry

[`capabilities.json`](capabilities.json) là nguồn cấu hình chung cho Excel và Blender. Mỗi capability có ID duy nhất, provider, handler, target, phiên bản, trạng thái bật/tắt và dependency. Tên macro VBA và Blender operator được đọc từ registry thay vì cho Qwen truyền vào hoặc khai báo lặp lại trong `config.json`.

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

Để thêm integration mới:

1. thêm capability với ID không trùng vào `capabilities.json`;
2. viết trusted handler trong adapter/runner tương ứng và kiểm tra toàn bộ đầu vào;
3. thêm dependency vào workflow sử dụng capability đó;
4. chỉ khai báo `public_tool` khi đã có MCP implementation tương ứng;
5. chạy unit test, `tests/smoke_mcp.py` và `tests/smoke_webui_mcp.py`.

Registry không tự động cho phép mọi macro hoặc `bpy.ops`. Thiết kế này cố ý yêu cầu handler rõ ràng để giữ ổn định, tránh xung đột tên và không đưa khả năng chạy VBA/Python tùy ý cho Qwen.

## Bảo mật và phạm vi local

- API/MCP, Ollama và Open WebUI chỉ dùng địa chỉ local.
- Blender MCP bind `127.0.0.1` trên cổng động và Blender được đóng sau mỗi tác vụ.
- Tham số được kiểm tra trước khi mã hóa thành JSON cho trusted runner.
- Workbook/model phải nằm trong project hoặc `paths.allowed_roots`.
- Internet chỉ cần khi tải dependency, model hoặc gói Blender MCP trong bước cài đặt.
