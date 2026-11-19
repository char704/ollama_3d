# Ollama3D — Open WebUI → REST agent → Excel + Blender

Project chạy local trên Windows với một đường xử lý duy nhất:

```text
Open WebUI
  → OpenAI-compatible REST API (127.0.0.1:8090/v1)
  → agent Python + Ollama
  ├─ Excel COM → VBA add-in
  └─ Blender background subprocess → add-on allowlist
```

Không có lớp giao thức tool trung gian. Excel được gọi trực tiếp từ workflow Python
qua COM/VBA; Blender được gọi trực tiếp bằng subprocess và fixed job entry.

## Cài đặt

Yêu cầu Windows, Excel, Blender và Ollama. Kiểm tra đường dẫn trong `config.json`,
sau đó chạy:

```powershell
.\Install.cmd
```

Installer tạo `.venv`, kiểm tra add-in/add-on, model local và khởi động REST API với
Open WebUI.

Các lần sau:

```powershell
.\Open-WebUI.cmd
```

Mở <http://127.0.0.1:8080> và chọn model `ollama3d-direct`.

## Xử lý folder tương đối

Trong Open WebUI, nhập:

```text
Xử lý folder inputs và xuất kết quả vào outputs
```

Workflow kiểm kê file trước khi chạy:

- một `.xlsx` + một `.blend` → Excel add-in → VBOM → Blender add-on;
- một VBOM `.xml` + một `.blend` → áp VBOM bằng Blender add-on;
- thiếu file, trùng file cần chọn hoặc nhiều workflow phù hợp → `needs_input`,
  không đoán.

Mọi đường dẫn tương đối được resolve từ root project và kiểm tra bằng `scoped_path`.
Đường dẫn đi ra ngoài vùng cho phép bị từ chối.

REST tương đương:

```powershell
$body = @{ input_dir = 'inputs'; output_dir = 'outputs' } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8090/proof/process-folder `
  -ContentType application/json `
  -Body $body
```

## Agent CLI

Có thể bỏ qua UI và gọi agent trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m agent.run `
  "Xử lý folder inputs và xuất kết quả vào outputs"
```

Model 4B phân loại intent/chọn capability/trích tham số. Model 0.8B chỉ trả lời
hội thoại ngắn sau khi 4B xác nhận intent là `chat`; nó không kích hoạt Excel hoặc
Blender.

## Thêm Blender add-on

Sau khi add-on đã được cài để Blender import được module:

```powershell
.\.venv\Scripts\python.exe manage.py addon add my_addon
.\.venv\Scripts\python.exe manage.py addon enable my_addon category.operator_name
```

Operator mới tắt mặc định. Registry tự nạp lại metadata:

```text
addons/<module>/
  addon.json
  docs.md
  workflows/*.json
```

## Lệnh quản trị

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py status
.\.venv\Scripts\python.exe manage.py sync
.\.venv\Scripts\python.exe manage.py discover --module my_addon
```

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests\smoke_rest.py
.\.venv\Scripts\python.exe tests\eval_models.py
```

## An toàn

- Không dựng Python từ tham số model.
- Excel chỉ gọi macro VBA đã đăng ký.
- Blender chỉ dispatch operation cố định qua `job_entry.py`.
- Add-on operator phải nằm trong allowlist và được bật.
- Thiếu hoặc mơ hồ đầu vào thì hỏi lại.
- API, Ollama và Open WebUI chỉ bind localhost.
- Runtime, log, output và evidence không được commit.
