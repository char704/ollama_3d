# Ollama 3D — Excel → VBOM → Blender

Prototype chạy trên Windows, cho phép bạn ra lệnh trong Open WebUI để xuất dữ liệu vật liệu từ Excel và áp dụng vào mô hình Blender. Ollama chạy mô hình AI trên máy và lựa chọn công cụ cần gọi cho từng bước.

Quy trình demo gồm:

1. Tìm file Excel và mô hình `.blend` trong thư mục đầu vào.
2. Chuyển bảng BOM trong Excel thành file VBOM dạng XML.
3. Chạy add-on demo trong Blender để áp vật liệu và màu.
4. Lưu mô hình, mở lại để kiểm tra dữ liệu đã lưu và tạo ảnh kết quả.
5. Mở mô hình kết quả nếu người dùng yêu cầu.

**Bản hiện tại sử dụng bộ chuyển đổi Excel và add-on Blender mẫu.** Để dùng với công ty, cần kết nối API hoặc thay phần gọi add-in/add-on theo công cụ thực tế.

## Cài đặt

Tải repository về máy và giải nén nếu dùng file ZIP. Trong thư mục project, chạy **[Install.cmd](Install.cmd)**.

Bộ cài sẽ kiểm tra các thành phần đã có, cài phần còn thiếu và thiết lập môi trường chạy:

- uv và Python 3.12, cùng các thư viện trong `requirements.txt`.
- Ollama và mô hình AI được chọn trong `config.json`.
- Blender nếu đang dùng chế độ demo và chưa tìm thấy bản đã cài.
- API local, Open WebUI và bốn công cụ dùng cho quy trình.

Cần Internet khi tải phần mềm hoặc mô hình AI. Việc cài phần mềm còn thiếu sử dụng WinGet, được cung cấp qua Microsoft App Installer; cài Blender có thể cần quyền quản trị. Node.js không phải thành phần bắt buộc.

Bạn có thể chạy lại bộ cài khi cần. Bộ cài đã được thử trên máy phát triển với các phần mềm có sẵn, chưa được kiểm chứng toàn bộ trên một máy Windows chưa cài các thành phần này.

## Sử dụng

Chạy **[Open-WebUI.cmd](Open-WebUI.cmd)** và đợi thông báo `READY`. Mở giao diện tại [http://127.0.0.1:8080](http://127.0.0.1:8080), chọn **Excel → Blender Demo**, rồi bắt đầu cuộc chat mới.

Ví dụ yêu cầu với dữ liệu mẫu:

> Dùng Footwear_BOM.xlsx, xuất VBOM rồi áp vật liệu và màu vào model mặc định. Mở kết quả.

Nếu muốn xử lý trong nền, thêm câu: “Không mở cửa sổ Blender”. Bạn cũng có thể chỉ định thư mục đầu vào và thư mục lưu trong yêu cầu. Khi thư mục có nhiều file Excel mà bạn chưa chọn tên file, AI sẽ hỏi cần sử dụng file nào.

Mặc định, mỗi lượt chạy tạo một thư mục riêng trong `oputs/`:

```text
oputs/<run_id>/
├── materials.vbom          # Dữ liệu vật liệu đã xuất
├── Sneaker_Applied.blend   # Mô hình sau khi áp vật liệu
├── after.png              # Ảnh kết quả
├── manifest.json          # Thông tin đầu vào và dữ liệu đối chiếu
├── verification.json      # Kết quả kiểm tra mô hình đã lưu
└── blender.log            # Nhật ký xử lý của Blender
```

`run_id` là mã riêng của lượt chạy. File `.blend` đầu vào được giữ nguyên.

| File chạy | Chức năng |
|---|---|
| [Install.cmd](Install.cmd) | Cài đặt, tải mô hình AI còn thiếu và thiết lập công cụ |
| [Open-WebUI.cmd](Open-WebUI.cmd) | Khởi động dịch vụ và cập nhật công cụ trong Open WebUI |
| [Status.cmd](Status.cmd) | Kiểm tra dịch vụ, mô hình AI và thư mục đang sử dụng |
| [Stop.cmd](Stop.cmd) | Dừng API và Open WebUI của project; giữ Ollama và các cửa sổ Blender đang mở |

Nếu Blender đang xử lý, hãy đợi hoàn tất trước khi dừng hoặc khởi động lại project. Nếu một chương trình khác đang sử dụng cổng đã cấu hình, launcher sẽ báo lỗi để bạn đổi cổng.

## Thay đổi cấu hình

Các thiết lập nằm trong **[config.json](config.json)**.

| Thiết lập | Ý nghĩa |
|---|---|
| `mode` | `demo` để dùng dữ liệu và công cụ mẫu; `company` để gọi các API công ty |
| `paths.inputs` | Thư mục tìm file Excel và mô hình Blender |
| `paths.outputs` | Thư mục lưu kết quả mặc định; hiện là `oputs` |
| `paths.default_model` | File `.blend` sử dụng khi yêu cầu không chỉ định mô hình |
| `paths.blender_exe` | Đường dẫn đến `blender.exe` dùng trong demo |
| `paths.allowed_roots` | Các thư mục bổ sung mà công cụ được phép truy cập |
| `services.api_port` | Cổng API demo; mặc định là `8090` |
| `services.webui_port` | Cổng Open WebUI; mặc định là `8080` |
| `services.ollama_url` | Địa chỉ Ollama trên máy; mặc định là `http://127.0.0.1:11434` |
| `ollama.model` | Tên mô hình AI; mặc định là `qwen2.5:7b` |
| `ollama.executable` | Đường dẫn đến Ollama; để trống để tự tìm |
| `company_api` | Địa chỉ và thiết lập xác thực cho từng API công ty |

Ví dụ, để dùng dữ liệu trên ổ D, thay mục `paths` bằng:

```json
{
  "inputs": "D:/DuLieu/BOM",
  "outputs": "D:/DuLieu/KetQua",
  "default_model": "D:/DuLieu/Models/product.blend",
  "blender_exe": "E:/Blender/blender.exe",
  "allowed_roots": []
}
```

Đường dẫn tương đối được tính từ thư mục chứa `config.json`. Với đường dẫn Windows trong JSON, dùng `/` hoặc viết dấu gạch chéo ngược thành `\\`.

Công cụ được phép sử dụng thư mục project, thư mục đầu vào, thư mục đầu ra và file mô hình mặc định đã cấu hình. Nếu muốn sử dụng thêm thư mục khác trong yêu cầu chat, thêm đường dẫn thư mục đó vào `allowed_roots`. Các thư mục nội bộ như `.venv`, `webui-data` và `runtime` được chặn khỏi thao tác truy cập file của công cụ.

Sau khi sửa cấu hình, chạy **Stop.cmd → Open-WebUI.cmd** và bắt đầu chat mới. Nếu chọn mô hình AI chưa tải về, chạy **Install.cmd** để tải mô hình đó.

## Open WebUI và Ollama phối hợp như thế nào?

```text
Người dùng nhập yêu cầu trong Open WebUI
                    ↕
       Ollama chọn công cụ và tham số
                    ↓
       Open WebUI thực thi webui_tool.py
                    ↓
        Gọi API theo config.json
          ├── Tìm file
          ├── Xuất Excel thành VBOM
          ├── Chạy add-on Blender
          └── Đọc trạng thái và kết quả
```

Ollama quyết định bước cần thực hiện dựa trên mô tả công cụ và kết quả của bước trước. Open WebUI thực thi lời gọi công cụ, sau đó gửi kết quả về cho Ollama để tiếp tục quy trình hoặc trả lời người dùng.

Trong demo, các API cùng chạy trong `api_service.py`. Phần đọc Excel nằm ở `adapters/excel.py`; phần mở Blender và theo dõi xử lý nằm ở `adapters/blender.py`. Script `blender/apply_vbom.py` chạy bên trong Blender để gọi add-on, lưu file và kiểm chứng kết quả.

## Kết nối công cụ của công ty

Có hai cách tích hợp, tùy công cụ công ty cung cấp.

### Công ty đã có HTTP API

Đặt `mode` thành `company`, sau đó điền mục `company_api`. Các API có thể chạy ở những địa chỉ hoặc cổng khác nhau. Ví dụ dưới đây là giá trị thay cho mục `company_api`; các địa chỉ chỉ dùng để minh họa:

```json
{
  "files": {
    "url": "http://127.0.0.1:9001/files",
    "token_env": ""
  },
  "export": {
    "url": "http://127.0.0.1:9001/export-vbom",
    "token_env": "EXCEL_API_TOKEN"
  },
  "apply": {
    "url": "http://127.0.0.1:9002/apply-vbom",
    "token_env": "BLENDER_API_TOKEN"
  },
  "result": {
    "url": "http://127.0.0.1:9002/results/{run_id}",
    "token_env": "BLENDER_API_TOKEN"
  }
}
```

`token_env` là **tên biến môi trường Windows chứa Bearer token**, không phải giá trị token. Đặt biến môi trường trước khi khởi động Open WebUI. Nếu API không yêu cầu token, để trống trường này.

Chỉ cần đổi URL khi API công ty nhận và trả dữ liệu theo quy ước mà công cụ hiện tại sử dụng:

| Chức năng | Yêu cầu HTTP | Kết quả JSON cần có khi thành công |
|---|---|---|
| Tìm file | GET, tham số query `input_dir` | `ok: true`, `excel_files`, `blender_models`; các đường dẫn phải đầy đủ |
| Xuất VBOM | POST JSON gồm `excel_path`, `output_dir` | `ok: true`, `status: "exported"`, `run_id`, `vbom_path` |
| Áp vật liệu | POST JSON gồm `vbom_path`, `model_path`, `open_window` | `ok: true`, `status: "completed"`, `run_id`, `output` |
| Đọc trạng thái | GET tại URL có `{run_id}` | `ok: true`, `run_id`, `status` và đường dẫn kết quả khi đã hoàn tất |

Khi có lỗi, API nên trả mã HTTP 4xx/5xx và JSON dạng `{"ok": false, "error": "Mô tả lỗi"}`. API đọc trạng thái phải tra được mã `run_id` do API xuất VBOM trả về.

Chế độ `company` hiện yêu cầu đủ bốn URL. Nếu công ty chỉ có hai API xuất VBOM và xử lý Blender, cần bổ sung phần tìm file, tra trạng thái hoặc điều chỉnh các công cụ tương ứng trong `webui_tool.py`. Khi cấu hình thiếu hoặc API lỗi, chương trình sẽ báo lỗi thay vì chuyển về demo.

Nếu API công ty dùng tên tham số, cấu trúc kết quả hoặc cách xác thực khác, sửa phần gọi HTTP trong **`webui_tool.py`**, hoặc tạo một API trung gian để chuyển đổi dữ liệu. Với API xử lý bất đồng bộ, cần bổ sung bước chờ và kiểm tra trạng thái; quy trình hiện tại chờ yêu cầu POST xử lý xong mới tiếp tục.

Máy chạy API phải truy cập được các đường dẫn file được gửi đến. Công cụ hiện tại truyền đường dẫn, chưa hỗ trợ tải file lên server hay chuyển đổi đường dẫn giữa Windows và Linux.

### Công ty cung cấp add-in hoặc add-on, chưa có HTTP API

Thay phần xử lý demo bằng lệnh gọi công cụ thực tế:

| File | Phần cần thay đổi |
|---|---|
| `adapters/excel.py` | Gọi add-in Excel để xuất VBOM |
| `adapters/blender.py` | Chuẩn bị đầu vào, mở Blender và theo dõi kết quả |
| `blender/apply_vbom.py` | Nạp add-on Blender, gọi operator và kiểm tra file đã lưu |

Cách gọi cụ thể phụ thuộc API, macro hoặc operator mà công cụ công ty cung cấp.

## Thêm một add-on hoặc một bước xử lý mới

Nếu add-on mới **luôn chạy cùng bước áp vật liệu**, thêm lệnh gọi trong `blender/apply_vbom.py`, trước khi lưu và kiểm chứng mô hình. Add-on phải được nạp trong tiến trình Blender trước khi gọi operator. Nếu bước mới thay đổi dữ liệu đầu ra, hãy cập nhật phần kiểm chứng tương ứng.

Nếu muốn **Ollama gọi bước mới như một công cụ riêng**, cần:

1. Thêm phần xử lý và endpoint trong `api_service.py`.
2. Thêm phương thức gọi endpoint đó trong `webui_tool.py`, kèm mô tả tham số và kết quả.
3. Cập nhật hướng dẫn thứ tự xử lý trong hàm `sync_webui()` của `manage.py`.

Sau khi sửa, chạy **Stop.cmd → Open-WebUI.cmd**, rồi mở chat mới. Launcher sẽ đăng ký lại công cụ và hướng dẫn trong Open WebUI. Có thể cập nhật riêng phần đăng ký khi WebUI đang chạy bằng lệnh:

```powershell
.\.venv\Scripts\python.exe manage.py sync
```

Việc thêm công cụ được thực hiện trong mã Python và mô tả công cụ; không cần huấn luyện lại mô hình AI. `setup-webui.mjs` chỉ được giữ để tương thích với lệnh cũ, không phải nơi cấu hình chính.

## Yêu cầu của dữ liệu demo

File Excel cần có sheet `BOM` với các cột theo đúng thứ tự:

```text
Object | Material | ColorHex | Roughness | Metallic
```

BOM gồm ba đối tượng `Upper`, `Sole`, `Laces`. Mỗi đối tượng xuất hiện một lần; màu dùng định dạng `#RRGGBB`; `Roughness` và `Metallic` nhận giá trị từ 0 đến 1. VBOM được xuất theo cấu trúc XML `demo-v1`.

Demo đọc Excel bằng openpyxl. Add-on Blender mẫu được nạp tạm trong tiến trình nền và không xuất hiện trong Preferences của Blender. Vì Blender được mở với `--factory-startup`, add-on công ty có thể cần được nạp và cấu hình riêng trong script.

API và Open WebUI chỉ lắng nghe trên máy local. Open WebUI hiện dùng chế độ một người dùng, không yêu cầu đăng nhập.

## Kiểm tra trạng thái và xử lý lỗi

Chạy **Status.cmd** để kiểm tra dịch vụ. Với cấu hình mặc định:

- Giao diện chat: [http://127.0.0.1:8080](http://127.0.0.1:8080).
- Tài liệu API demo: [http://127.0.0.1:8090/docs](http://127.0.0.1:8090/docs). Trang Swagger này tải tài nguyên từ CDN.
- Mô tả OpenAPI: [http://127.0.0.1:8090/openapi.json](http://127.0.0.1:8090/openapi.json).

| Vị trí | Nội dung |
|---|---|
| `logs/api-error.log`, `logs/webui-error.log`, `logs/ollama-error.log` | Nhật ký lỗi của dịch vụ do launcher khởi động |
| `logs/tool-calls.jsonl` | Các thao tác được API demo ghi nhận |
| `runtime/results/<run_id>.json` | Trạng thái và kết quả của từng lượt chạy |
| `<thư mục kết quả>/blender.log` | Nhật ký Blender của lượt đó |
| `runtime/services.json` | Thông tin cấu hình dịch vụ; launcher tự quản lý |

API demo chỉ xử lý một tác vụ Blender tại một thời điểm. Gọi lại bước áp vật liệu cho lượt đã hoàn tất với cùng mô hình đầu vào sẽ trả kết quả cũ.

Công cụ gọi HTTP chờ tối đa 210 giây. Nếu hết thời gian chờ, dùng `get_run_result` để kiểm tra trước khi chạy lại. Nếu tiến trình bị ngắt đột ngột, trạng thái có thể còn là `applying`; hãy xem nhật ký để xác định bước bị gián đoạn.

## Kiểm thử và sao lưu

Chạy các lệnh sau từ thư mục project:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\Start-OpenWebUI.ps1 -NoBrowser
.\.venv\Scripts\python.exe tests\smoke_api.py
.\.venv\Scripts\python.exe tests\smoke_webui.py
```

Các bài kiểm tra bao gồm cấu hình và quyền truy cập đường dẫn, cách gọi API ở các địa chỉ khác nhau, xác thực và xử lý lỗi. Bài thử API sử dụng Blender thật để đối chiếu hai bộ màu với dữ liệu Excel. Bài thử WebUI tạo một cuộc chat thật để kiểm tra chuỗi gọi công cụ của Ollama.

Kết quả kiểm thử được lưu trong `evidence/`; các file Blender được tạo trong thư mục đầu ra đã cấu hình.

Để cài trên máy khác, tải lại repository và chạy `Install.cmd`. Môi trường `.venv` và `.python` cần được tạo trên máy đó. Để sao lưu lịch sử chat và cấu hình WebUI, giữ cả `webui-data/` lẫn `.webui_secret_key`; sao lưu riêng dữ liệu đầu vào và kết quả mà bạn muốn giữ.
