# Ollama3D direct automation

Project Windows chạy hoàn toàn local. Ollama phân loại yêu cầu, Python kiểm tra
allowlist và tham số, Excel được gọi qua VBA add-in, còn Blender chạy add-on trong
một background subprocess ngắn hạn.

```text
Người dùng
  → agent/run.py
  → workflow Python tất định
  ├─ ExcelVbaAdapter → Ollama3DProof.xlam
  └─ BlenderAdapter  → blender/job_entry.py → Blender add-on
```

Nhánh `main` không cần API hoặc UI trung gian. Các tích hợp giao thức tùy chọn cũ
được lưu riêng trên nhánh `mcp-optional`.

## Cài đặt

Sửa đường dẫn trong `config.json`, sau đó chạy:

```powershell
.\Install.cmd
```

Installer tạo `.venv`, cài dependency nhỏ, kiểm tra Excel add-in, đóng gói/cài
Blender add-on và bảo đảm hai model đã có:

```text
qwen3.5:4b    router, chọn capability, trích tham số
qwen3.5:0.8b  chỉ trả lời hội thoại ngắn sau khi 4B chọn intent chat
```

## Chạy agent

```powershell
.\.venv\Scripts\python.exe -m agent.run "Kiểm tra hệ thống"
```

Ví dụ workflow Excel add-in → Blender add-on:

```powershell
.\.venv\Scripts\python.exe -m agent.run `
  "Đọc BOM E:/3d/ollama_3d-publish/inputs/Footwear_BOM.xlsx, áp vào E:/3d/ollama_3d-publish/inputs/Sneaker_Unassigned.blend và lưu E:/3d/ollama_3d-publish/outputs"
```

Ví dụ gọi operator add-on:

```powershell
.\.venv\Scripts\python.exe -m agent.run `
  "Áp VBOM E:/3d/ollama_3d-publish/tests/fixtures/proof_v1.vbom.xml với run_id TEST-RUN vào model E:/3d/ollama_3d-publish/inputs/Sneaker_Unassigned.blend, lưu E:/3d/ollama_3d-publish/outputs"
```

## Lệnh quản trị

```powershell
# Kiểm tra cấu hình và dependency
.\.venv\Scripts\python.exe manage.py check

# Kiểm tra Ollama, Excel add-in và Blender add-on thật
.\.venv\Scripts\python.exe manage.py status

# Discovery add-on đã cài trong Blender
.\.venv\Scripts\python.exe manage.py discover --module my_addon
```

## Thêm Blender add-on

Sau khi add-on đã được cài để Blender import được module:

```powershell
.\.venv\Scripts\python.exe manage.py addon add my_addon
.\.venv\Scripts\python.exe manage.py addon enable my_addon category.operator_name
```

Lệnh `addon add` tạo toàn bộ operator ở trạng thái tắt. Chỉ bật operator thực sự
cần dùng. Registry tự nạp lại khi metadata thay đổi, không cần restart.

```text
addons/<module>/
  addon.json
  docs.md
  workflows/*.json
```

Gỡ pack bằng cách xóa riêng thư mục `addons/<module>`; tắt operator bằng:

```powershell
.\.venv\Scripts\python.exe manage.py addon disable my_addon category.operator_name
```

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests\eval_models.py
```

Các test có Blender dùng executable trong `paths.blender_exe`. Mọi report Blender
ghi phiên bản thực tế, hash đầu ra và kết quả kiểm tra sau khi mở lại file.

## An toàn

- Không sinh hoặc chạy Python từ tham số của model.
- Blender chỉ dispatch operation cố định qua `job_entry.py`.
- Operator add-on phải nằm trong allowlist và được bật rõ ràng.
- Mọi đường dẫn đi qua `scoped_path`.
- Thiếu tham số hoặc đường dẫn thì agent hỏi lại, không đoán.
- Model 0.8B không được định tuyến hoặc kích hoạt Excel/Blender.
- Runtime, log, output và evidence không được commit.
