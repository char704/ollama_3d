# Excel → VBOM → Blender bằng Ollama local

## Dùng hằng ngày

1. Lần đầu trên máy mới: chạy **Install.cmd**. Cần Internet để tải phần mềm/model còn thiếu.
2. Chạy **Open-WebUI.cmd**, chờ `READY`, chọn **Excel → Blender Demo** và mở chat mới.
3. Ra lệnh:

> Dùng Footwear_BOM.xlsx, xuất VBOM rồi áp vật liệu và màu vào model mặc định. Mở kết quả.

Kết quả mặc định nằm trong `oputs/<run_id>/`: `materials.vbom`,
`Sneaker_Applied.blend`, `after.png`, manifest và log kiểm chứng.
Mỗi lượt có thư mục riêng, không ghi đè model đầu vào.
Thêm “chạy nền, không mở Blender” nếu chỉ muốn tạo file kết quả.

- **Status.cmd**: kiểm tra dịch vụ và xem thư mục đang dùng.
- **Stop.cmd**: dừng API và Open WebUI của project. Giữ Ollama và cửa sổ Blender đang mở.
- **Open-WebUI.cmd**: tự nạp lại dịch vụ khi cấu hình/code API thay đổi; cập nhật tool và hướng dẫn model.

Script không dừng dịch vụ khác đang chiếm cổng. Khi Blender đang xử lý, lệnh dừng/khởi động
lại sẽ báo cần đợi hoàn tất. Chat, file đầu vào và kết quả cũ được giữ nguyên.

## Một file cấu hình: config.json

| Trường | Ý nghĩa |
|---|---|
| `mode` | `demo` dùng bộ chuyển đổi/add-on mẫu; `company` gọi các URL công ty |
| `paths.inputs` | Thư mục Excel đầu vào và nơi tìm model |
| `paths.outputs` | Thư mục lưu mặc định, hiện là `oputs` |
| `paths.default_model` | File `.blend` khi prompt không chỉ định model |
| `paths.blender_exe` | Đường dẫn `blender.exe` cho demo |
| `paths.allowed_roots` | Thư mục bổ sung được phép sử dụng trong prompt |
| `services.api_port` / `webui_port` | Cổng API demo / giao diện chat |
| `services.ollama_url` | Địa chỉ Ollama trên máy này |
| `ollama.model` | Model dùng để gọi tool, hiện là `qwen2.5:7b` |
| `ollama.executable` | Để trống để tự tìm Ollama, hoặc chỉ rõ file `.exe` |
| `company_api` | Bốn URL và tên biến môi trường chứa token cho API công ty |

Đường dẫn tương đối tính từ thư mục chứa `config.json`, không phụ thuộc nơi mở terminal.
Có thể dùng thư mục khác ổ đĩa, ví dụ:

```json
"paths": {
  "inputs": "D:/DuLieu/BOM",
  "outputs": "D:/DuLieu/KetQua",
  "default_model": "D:/DuLieu/Models/product.blend",
  "blender_exe": "E:/Blender/blender.exe",
  "allowed_roots": []
}
```

Dùng `/` hoặc `\\` trong chuỗi JSON. Thư mục input/output được cấu hình tự được phép
truy cập; model mặc định cũng được phép. Với đường dẫn khác trong prompt, thêm thư mục
cha phù hợp vào `allowed_roots`. Không cho phép đọc dữ liệu nội bộ như `webui-data`,
`.venv`, `runtime` qua tool.

**Sau khi sửa config: chạy Stop.cmd rồi Open-WebUI.cmd, sau đó mở chat mới.**
Nếu đổi model sang model chưa tải, chạy Install.cmd để tải model đó.

## Cài trên máy Windows khác

Copy mã nguồn, `config.json`, `requirements.txt`, thư mục `adapters`, `blender`,
`inputs` và các script `.cmd`/`.ps1`. Không cần copy `.venv`, `.python`, log hoặc kết quả thử.
Chạy **Install.cmd** để:

1. Tìm uv; cài qua WinGet nếu thiếu.
2. Tạo Python 3.12 và `.venv` trong project; cài các phiên bản trực tiếp đã ghim trong `requirements.txt`.
3. Tìm/cài Ollama; tìm Blender đã cài hoặc cài Blender khi chạy demo và chưa có.
4. Tải model đã chọn nếu thiếu, khởi động dịch vụ, đợi sẵn sàng và đăng ký bốn tool.

Cần WinGet (Microsoft App Installer) nếu có phần mềm thiếu. Cài Blender có thể cần quyền
quản trị. Không cần Node.js để cài, chạy hoặc kiểm thử. Script cài có thể chạy lại.
Không copy môi trường `.venv` từ máy khác; các đường dẫn Python trong đó phụ thuộc máy.
Bộ cài đã được thử trên máy hiện tại với phần mềm có sẵn; chưa kiểm chứng toàn bộ trên máy trắng.

Giữ `webui-data/` và `.webui_secret_key` nếu muốn sao lưu/khôi phục lịch sử chat.

## Chuyển sang API công ty

Kiến trúc:

```text
Chat Open WebUI ↔ Ollama (model chọn tên tool và tham số)
        ↓
webui_tool.py → HTTP theo config.json
        ├── Excel API → xuất VBOM
        ├── Blender API → áp vật liệu/màu, lưu model
        ├── Files API → tìm file
        └── Results API → xem trạng thái
```

Ở demo, bốn endpoint cùng nằm trong `api_service.py` trên cổng 8090.
Ở company, chúng có thể ở các server/cổng khác nhau. Ví dụ cấu hình minh họa:

```json
"mode": "company",
"company_api": {
  "files":  {"url": "http://127.0.0.1:9001/files", "token_env": ""},
  "export": {"url": "http://127.0.0.1:9001/export-vbom", "token_env": "EXCEL_API_TOKEN"},
  "apply":  {"url": "http://127.0.0.1:9002/apply-vbom", "token_env": "BLENDER_API_TOKEN"},
  "result": {"url": "http://127.0.0.1:9002/results/{run_id}", "token_env": "BLENDER_API_TOKEN"}
}
```

Các URL trên là ví dụ, chưa có server công ty chạy ở đó. Nếu API không cần token, để
`token_env` trống. Nếu cần Bearer token, đặt biến môi trường Windows có tên tương ứng
rồi khởi động lại Open WebUI; không đặt token vào prompt. Mỗi endpoint dùng token riêng.
Chế độ company yêu cầu đủ bốn URL và không tự quay về demo khi thiếu/lỗi.
Nếu công ty chỉ có hai API nghiệp vụ, cần bổ sung lớp tìm file/trạng thái hoặc điều chỉnh
hai tool tương ứng trước khi chuyển toàn bộ sang company.

**Chỉ đổi URL là đủ khi API công ty giữ cùng hợp đồng dữ liệu:**

| Tool | HTTP và đầu vào | Trường kết quả cần có |
|---|---|---|
| `list_demo_files` | GET, query `input_dir` | `ok`, `excel_files`, `blender_models` (đường dẫn đầy đủ) |
| `export_excel_to_vbom` | POST JSON `excel_path`, `output_dir` | `ok`, `status: exported`, `run_id`, `vbom_path` |
| `apply_vbom_in_blender` | POST JSON `vbom_path`, `model_path`, `open_window` | `ok`, `status: completed`, `run_id`, `output` |
| `get_run_result` | GET URL có `{run_id}` | `ok`, `run_id`, `status`, đường dẫn kết quả nếu đã xong |

Lỗi trả HTTP 4xx/5xx kèm JSON `{"ok": false, "error": "mô tả"}`.
`run_id` của lớp tool nhận chữ/số/gạch ngang/gạch dưới, tối đa 128 ký tự; demo dùng 32 ký tự hex.
Tool chờ tối đa 210 giây. API chạy bất đồng bộ cần trả trạng thái rõ và lớp tool/model
phải xử lý polling phù hợp; bộ demo hiện dùng POST đồng bộ.

Nếu công ty khác tên tham số, schema kết quả hoặc kiểu xác thực, sửa phần chuyển đổi
trong **webui_tool.py**, hoặc tạo API bọc có hợp đồng trên. Cùng một `run_id` phải tra được
ở Results API. Server phải truy cập được đường dẫn file được gửi; tool hiện không upload,
không copy file giữa máy và không tự chuyển đường dẫn Windows sang Linux.

Nếu công ty chỉ cung cấp macro/operator chứ chưa có HTTP API, thay code ở:

- `adapters/excel.py`: gọi add-in Excel thay converter mẫu.
- `adapters/blender.py` và `blender/apply_vbom.py`: gọi add-on Blender thực tế và kiểm chứng kết quả.

Sửa `webui_tool.py` xong chạy Open-WebUI.cmd để đồng bộ bản code lưu trong Open WebUI.
Có thể đồng bộ riêng bằng `.\.venv\Scripts\python.exe manage.py sync`.
`setup-webui.mjs` được giữ làm lệnh tương thích cũ; không còn là nơi cấu hình model/tool.

## Phạm vi demo và kiểm tra lỗi

Demo đọc XLSX bằng openpyxl, **không dùng add-in Excel công ty**. Cần sheet `BOM`,
các cột `Object`, `Material`, `ColorHex`, `Roughness`, `Metallic` và ba đối tượng
`Upper`, `Sole`, `Laces`. VBOM là XML `demo-v1`.
Blender nạp add-on demo tạm trong tiến trình nền, lưu rồi mở lại model để kiểm tra màu/vật liệu.
Add-on này không được cài vào Preferences. Add-on công ty có thể cần profile hoặc giao diện;
phải chỉnh adapter theo yêu cầu thực tế.

API: `http://127.0.0.1:8090`, schema tại `/openapi.json`, thử bằng `/docs` (Swagger dùng CDN).
Chat: `http://127.0.0.1:8080`. Cả hai chỉ nghe trên loopback, WebUI dùng single-user local.

- Log dịch vụ mới: `logs/api-error.log`, `logs/webui-error.log`, `logs/ollama-error.log`.
- Lời gọi tool: `logs/tool-calls.jsonl`.
- Trạng thái mỗi lượt: `runtime/results/<run_id>.json`.
- Log Blender: `blender.log` trong thư mục kết quả của lượt đó.
- `runtime/services.json`: nhận diện cấu hình đã khởi động; được script tự quản lý.

API chỉ xử lý một tác vụ Blender cùng lúc. Apply lại lượt đã hoàn tất với cùng model trả
kết quả cũ. Timeout ở client không có nghĩa Blender đã dừng: gọi `get_run_result` trước
khi thử lại. Nếu tiến trình bị ngắt đột ngột, trạng thái `applying` có thể còn lưu; kiểm tra log.

## Kiểm thử dành cho người chỉnh code

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\Start-OpenWebUI.ps1 -NoBrowser
.\.venv\Scripts\python.exe tests\smoke_api.py
.\.venv\Scripts\python.exe tests\smoke_webui.py
```

Unit tests kiểm tra ranh giới đường dẫn, cấu hình lỗi, hai API công ty giả lập ở hai địa chỉ
khác nhau, token riêng và lỗi/timeout. Smoke API thực sự xuất BOM và một biến thể màu
sinh tạm, chạy Blender và đối chiếu kết quả với Excel. Smoke WebUI tạo một chat thật và
kiểm tra Ollama đã gọi tool đến khi lưu/kiểm chứng file Blender.
Bằng chứng lưu tại `evidence/`; các lượt thử tạo file thật trong thư mục outputs đã cấu hình.
