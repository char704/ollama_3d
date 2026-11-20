# Ollama3D — Open WebUI → REST agent → Excel + Blender

Project chạy local trên Windows với một đường xử lý duy nhất:

```text
Open WebUI
  → OpenAI-compatible REST API (127.0.0.1:8090/v1)
  → agent Python + Ollama
  → Excel COM đọc BOM → Python xuất VBOM
  → Blender chạy add-on JHV → lưu và mở lại model
```

Excel được đọc qua COM ở chế độ read-only. Python tạo VBOM. Blender gọi
`jhv.run_dpc_automation` trong subprocess.

## Cài đặt

Yêu cầu Windows, Excel, Blender và Ollama. Kiểm tra đường dẫn trong `config.json`,
sau đó chạy:

```powershell
.\Install.cmd
```

Cài module `jhv_dpc` vào thư mục add-on đúng phiên bản Blender trước khi chạy
installer. Installer tạo `.venv`, kiểm tra tích hợp và model local, rồi khởi động
REST API cùng Open WebUI.

Các lần sau:

```powershell
.\Open-WebUI.cmd
```

Mở <http://127.0.0.1:8080> và chọn model `ollama3d-direct`.

## Cập nhật trên máy công ty

### Máy không có Git

1. Tải [ZIP bản mới nhất](https://github.com/char704/ollama_3d/archive/refs/heads/main.zip).
   Chờ job xong, đóng Blender, chạy `Stop.cmd` trong thư mục cũ rồi giải nén ZIP
   vào **thư mục mới**. Giữ thư mục cũ để có thể quay lại.
2. Gộp các đường dẫn riêng của máy vào `config.json` mới, nhất là Blender, Ollama,
   Excel và thư mục dữ liệu. Nếu muốn tiếp tục dùng dữ liệu trong dự án cũ, sao chép
   `inputs`, `outputs` và, nếu cần giữ dữ liệu Open WebUI, cả `webui-data` và
   `.webui_secret_key` (nếu có). Nếu máy đã cấu hình thư mục dữ liệu ở ngoài
   project, giữ các đường dẫn đó trong cấu hình mới.
3. Mở PowerShell trong thư mục vừa giải nén và đồng bộ bản `jhv_dpc.py` có SQLite
   nhận qua kênh nội bộ:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\Update.ps1 -SkipPull -JhvAddonPath 'E:\DuongDanNoiBo\jhv_dpc.py'
   ```

4. Chạy `Install.cmd` trong thư mục mới để tạo môi trường Python tại đúng đường dẫn.
   Kiểm tra `Asset Library Path` trong Blender. Nếu thư viện chưa được lập chỉ mục
   hoặc vừa thay đổi, mở Asset Browser để cập nhật metadata rồi bấm **Refresh Library
   Cache** trong JHV. Các lần khởi động sau dùng `Open-WebUI.cmd`.

### Máy có Git

1. Chờ workflow đang chạy hoàn tất, rồi đóng Blender và chạy `Stop.cmd`. Sao lưu
   `config.json` và các file làm việc quan trọng. Giữ thư mục `webui-data` nếu
   muốn giữ cấu hình Open WebUI hiện tại.
2. Trong thư mục dự án, cập nhật nhánh `main` và cài bản `jhv_dpc.py` có SQLite
   nhận từ nguồn nội bộ đã được công ty duyệt:

   ```powershell
   git pull --ff-only origin main
   powershell -NoProfile -ExecutionPolicy Bypass -File .\Update.ps1 -SkipPull -JhvAddonPath 'E:\DuongDanNoiBo\jhv_dpc.py'
   ```

   Sau lần đầu, có thể bỏ lệnh `git pull` riêng và chạy `Update.ps1` với
   `-JhvAddonPath`, bỏ `-SkipPull`. Script dùng Blender được cấu hình trong
   `config.json` và sao lưu add-on cũ trong `runtime\addon-backups`.
   Nếu Git báo xung đột cấu hình local, giữ bản sao rồi gộp các đường dẫn
   máy công ty vào cấu hình mới trước khi tiếp tục. Tránh dùng lệnh reset.
3. Trong Blender, kiểm tra `Asset Library Path` của JHV trỏ đến thư mục cha
   chứa `Adidas Library` và `Generic Library`, ví dụ `E:\Blender` nếu cả hai
   thư mục nằm ngay bên dưới. Mở Asset Browser để Blender có metadata thư viện,
   lưu Preferences, rồi làm bước refresh bên dưới.
4. Mở lại bằng `Open-WebUI.cmd`. Nếu máy chưa có `.venv`, chạy `Install.cmd`
   sau khi đã cài add-on và chỉnh các đường dẫn máy local.

Mã nguồn add-on JHV nội bộ, BOM, model, file Excel add-in và Asset Library được
chuyển qua kênh nội bộ của công ty. Repo GitHub cung cấp mã tích hợp Ollama3D.

## Xử lý folder tương đối

Trong Open WebUI, nhập:

```text
Xử lý folder inputs và xuất kết quả vào outputs
```

Workflow kiểm kê file trước khi chạy:

- Chat tự chạy cả hai bước khi có đúng một Excel BOM và một model `.blend`.
- Yêu cầu “chỉ xuất VBOM” tạo `materials.vbom`. Để dùng VBOM có sẵn, yêu cầu áp file `.vbom` lên model.
- Nếu thiếu file hoặc có nhiều lựa chọn, trả lời bằng mã JHV được hiển thị, theo sau là tên file hoặc đường dẫn. Mã có hiệu lực 15 phút và dùng một lần.
- Model đã có Article trùng với VBOM trả lỗi `ARTICLE_ALREADY_EXISTS`. Dùng model gốc và có thể tái sử dụng VBOM đã xuất.
- Khi Blender đã xác minh file kết quả nhưng báo thiếu part, màu hoặc vật liệu, trạng thái là `completed_with_warnings`. Báo cáo mã Article, cảnh báo và đường dẫn xác minh nằm trong kết quả workflow.

Mọi đường dẫn tương đối được resolve từ root project và kiểm tra bằng `scoped_path`.
Đường dẫn đi ra ngoài vùng cho phép bị từ chối.

REST tương đương:

```powershell
$body = @{ input_dir = 'inputs'; output_dir = 'outputs' } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8090/jhv/process-folder `
  -ContentType application/json `
  -Body $body
```

## Agent CLI

Có thể bỏ qua UI và gọi agent trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m agent.run `
  "Xử lý folder inputs và xuất kết quả vào outputs"
```

Model cấu hình phân loại yêu cầu và trích tham số. Python kiểm tra đầu vào và
thực thi workflow. Nếu cần chọn nhiều lượt, dùng Open WebUI hoặc chat API để giữ
mã tiếp tục trong cùng tiến trình.

### Asset index SQLite của JHV

Trong Blender, cấu hình Asset Library của JHV và để Blender cập nhật Asset Index.
Sau đó bấm **Refresh Library Cache** hoặc chạy từ root project:

```powershell
.\.venv\Scripts\python.exe scripts/jhv_cli.py refresh-index
```

Refresh sau khi thêm, sửa, đổi tên hoặc xóa asset. Nếu refresh thất bại, bản
SQLite trước đó vẫn còn. Báo cáo job ghi phiên bản và thời điểm index được cập nhật.
Job chỉ kiểm tra các file mà index chọn. Asset mới, kể cả asset có ưu tiên cao
hơn một kết quả cũ, chỉ được tra qua SQLite sau khi refresh.

Để kiểm chứng cùng một VBOM trên model gốc, đặt seed như nhau cho các lần chạy:

```powershell
$env:PYTHONHASHSEED = '0'
.\.venv\Scripts\python.exe scripts/jhv_cli.py apply outputs/materials.vbom outputs --model inputs/shoe.blend --resolver compare
.\.venv\Scripts\python.exe scripts/jhv_cli.py apply outputs/materials.vbom outputs --model inputs/shoe.blend --resolver sqlite
```

`legacy` là mặc định. `compare` ghi khác biệt theo mã nhưng dùng kết quả legacy
để gán. `sqlite` dùng index mới và quay về legacy khi index thiếu, lỗi hoặc file
được chọn đã đổi. Với Open WebUI, đặt biến môi trường `JHV_DPC_RESOLVER` cho tiến
trình chạy Ollama3D nếu cần chọn chế độ.

Xem `asset_resolver`, `addon_timings.resolver` và `timings` trong
`blender-operator-proof.json`. Trên máy có thư viện thật, đo riêng lần refresh
và chạy ba lần mỗi chế độ `legacy` và `sqlite`. Dùng `compare` để xác nhận không
có sai khác trong tra cứu, rồi đối chiếu shader và texture với kết quả Blender
thủ công. Mục tiêu là giảm ít nhất 50% thời gian quét/xác thực index và tổng thời
gian trung vị không tăng.

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

Hướng dẫn thêm hoặc cập nhật add-on và nghiệm thu JHV nằm tại
[`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md). Tài liệu cũng mô tả
contract bắt buộc, cách viết metadata để Qwen chọn đúng, kiểm thử và rollback.

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
- Excel COM đọc workbook và Python xuất VBOM.
- Blender chỉ dispatch operation cố định qua `job_entry.py`.
- Add-on operator phải nằm trong allowlist và được bật.
- Thiếu hoặc mơ hồ đầu vào thì hỏi lại.
- API, Ollama và Open WebUI chỉ bind localhost.
- Runtime, log, output và evidence không được commit.
