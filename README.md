# Ollama 3D — Excel → VBOM → Blender

Prototype chạy trên Windows, cho phép bạn ra lệnh trong Open WebUI để xuất dữ liệu vật liệu từ Excel và áp dụng vào mô hình Blender. Ollama chạy mô hình AI trên máy, hiểu yêu cầu và chọn công cụ; Python chịu trách nhiệm thực thi workflow theo đúng thứ tự.

Quy trình demo gồm:

1. Tìm file Excel và mô hình `.blend` trong thư mục đầu vào.
2. Chuyển bảng BOM trong Excel thành file VBOM dạng XML.
3. Chạy add-on demo trong Blender để áp vật liệu và màu.
4. Lưu mô hình, mở lại để kiểm tra dữ liệu đã lưu và tạo ảnh kết quả.
5. Mở mô hình kết quả nếu người dùng yêu cầu.

Một yêu cầu hoàn chỉnh chỉ gọi `run_bom_pipeline` một lần. Workflow Python đảm bảo các bước xuất, áp dụng và kiểm chứng chạy tuần tự; mô hình AI không tự ghép các API thấp cấp. Yêu cầu giống hệt đang chạy hoặc đã hoàn tất được dùng lại để tránh tạo kết quả trùng, trừ khi người dùng chủ động yêu cầu chạy mới.

**Bản hiện tại sử dụng bộ chuyển đổi Excel và add-on Blender mẫu.** Để dùng với công ty, cần kết nối API hoặc thay phần gọi add-in/add-on theo công cụ thực tế.

## Cài đặt

Tải repository về máy và giải nén nếu dùng file ZIP. Trong thư mục project, chạy **[Install.cmd](Install.cmd)**.

Bộ cài sẽ kiểm tra các thành phần đã có, cài phần còn thiếu và thiết lập môi trường chạy:

- uv và Python 3.12, cùng các thư viện trong `requirements.txt`.
- Ollama và mô hình AI được chọn trong `config.json`.
- Blender khi workflow local hoặc danh sách operator cần sử dụng nó.
- API điều phối local, Open WebUI và bảy công cụ được phép cho mô hình sử dụng.

Cần Internet khi tải phần mềm hoặc mô hình AI. Việc cài phần mềm còn thiếu sử dụng WinGet, được cung cấp qua Microsoft App Installer; cài Blender có thể cần quyền quản trị. Node.js không phải thành phần bắt buộc.

Bạn có thể chạy lại bộ cài khi cần. Bộ cài đã được thử trên máy phát triển với các phần mềm có sẵn, chưa được kiểm chứng toàn bộ trên một máy Windows chưa cài các thành phần này.

## Sử dụng

Chạy **[Open-WebUI.cmd](Open-WebUI.cmd)** và đợi thông báo `READY`. Mở giao diện tại [http://127.0.0.1:8080](http://127.0.0.1:8080), chọn **Excel → Blender Demo**, rồi bắt đầu cuộc chat mới.

Ví dụ yêu cầu với dữ liệu mẫu:

> Dùng Footwear_BOM.xlsx, xuất VBOM rồi áp vật liệu và màu vào model mặc định. Mở kết quả.

Nếu muốn xử lý trong nền, thêm câu: “Không mở cửa sổ Blender”. Bạn cũng có thể chỉ định thư mục đầu vào và thư mục lưu trong yêu cầu. Khi thư mục có nhiều file Excel mà bạn chưa chọn tên file, AI sẽ hỏi cần sử dụng file nào.

Nếu gửi lại đúng yêu cầu cũ, hệ thống trả về workflow đã hoàn tất thay vì chạy Blender lần nữa. Chỉ dùng `force_new` khi thật sự cần tạo một lượt chạy mới; trong chat có thể nói rõ “chạy lại thành một lượt mới”.

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
| [Stop.cmd](Stop.cmd) | Dừng API, Open WebUI và Blender Agent; giữ Ollama và các dịch vụ add-on chạy riêng |

Nếu Blender đang xử lý, hãy đợi hoàn tất trước khi dừng hoặc khởi động lại project. Nếu một chương trình khác đang sử dụng cổng đã cấu hình, launcher sẽ báo lỗi để bạn đổi cổng.

## Thay đổi cấu hình

Các thiết lập nằm trong **[config.json](config.json)**.

| Thiết lập | Ý nghĩa |
|---|---|
| `profile` | Tên hiển thị của bộ cấu hình, ví dụ `demo` hoặc `mixed-company`; không bật/tắt dịch vụ |
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
| `tool_library.directory` | Thư mục manifest của các tool; mặc định là `tool-library` |
| `workflow` | Chọn provider `local` hoặc `http` độc lập cho từng bước |
| `blender_agent.max_queued_jobs` | Số job Blender tối đa được phép chờ trong hàng đợi |
| `blender_agent.hung_grace_seconds` | Thời gian gia hạn sau timeout trước khi coi Agent bị treo |
| `blender_agent.auto_restart_hung` | Tự kết thúc và khởi động lại Agent bị treo |

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
       Ollama chọn công cụ và điền tham số
                    ↓
       Open WebUI thực thi webui_tool.py
                    ↓
       Gọi một API workflow xác định
          ├── Xuất Excel thành VBOM
          ├── Áp VBOM trong Blender
          ├── Kiểm chứng file đã lưu
          └── Trả kết quả hoặc lỗi có cấu trúc
```

Ollama không trực tiếp điều khiển Excel hoặc Blender. Nó chỉ chọn một trong các tool được công khai và tạo tham số JSON. Open WebUI chạy mã Python của tool, mã này gọi API local. API mới là nơi kiểm tra quyền truy cập đường dẫn, thực thi workflow và lưu trạng thái. Kết quả JSON quay lại Open WebUI để Ollama diễn giải cho người dùng.

Trong demo, các API cùng chạy trong `api_service.py`. Workflow cấp cao nằm ở `workflows/bom_pipeline.py`; phần đọc Excel nằm ở `adapters/excel.py`; phần mở Blender và theo dõi xử lý nằm ở `adapters/blender.py`. Script `blender/apply_vbom.py` chạy bên trong Blender để gọi add-on, lưu file và kiểm chứng kết quả. Các endpoint thấp cấp vẫn tồn tại để kiểm thử và tích hợp, nhưng không được công khai thành tool cho Ollama.

### Các tool Ollama được phép gọi

| Tool | Mục đích |
|---|---|
| `list_demo_files` | Tìm Excel và model trong thư mục được phép |
| `run_bom_pipeline` | Chạy toàn bộ Excel → VBOM → Blender → verify |
| `get_bom_pipeline_job` | Đọc lại trạng thái workflow mà không chạy lại |
| `list_blender_addons` | Đọc danh mục operator Blender được phép |
| `run_blender_addon` | Chạy một operator đã chọn từ danh mục |
| `get_blender_job` | Đọc trạng thái job Blender Agent |
| `cancel_blender_job` | Hủy job còn đang chờ khi người dùng yêu cầu |

## Blender Agent và hàng đợi

Các operator `one_shot` chạy trong một Blender Agent dùng chung. Agent được mở cùng project, lấy từng job theo thứ tự và thực thi `bpy.ops` trên luồng chính của Blender.

```text
Open WebUI + Ollama
        ↓ chọn operator và tham số
FastAPI → runtime/blender-agent/queue
        ↓ từng job một
Blender Agent → reset scene → bpy.ops → lưu kết quả → reset scene
```

Trước mỗi job, Agent mở file model được chỉ định hoặc template rỗng. Sau khi job hoàn tất hoặc thất bại, Agent mở lại template rỗng rồi mới nhận job kế tiếp. Kết quả mặc định nằm trong `oputs/agent/<job_id>/result.blend`. API `GET /blender/jobs/{job_id}` trả trạng thái `queued`, `running`, `completed`, `failed`, `cancelled` hoặc `interrupted`.

Agent dùng một thư mục `queue` riêng nên thời gian tìm job mới không tăng theo số lượng kết quả cũ. Job được claim nguyên tử trước khi chạy để tránh xung đột với thao tác hủy. Chỉ job còn trong hàng đợi mới được hủy; job đã chạy không bị dừng giữa chừng. Heartbeat được ghi theo chu kỳ trong `config.json`. Khi code hoặc cấu hình Agent thay đổi, launcher nhận biết phiên bản và khởi động lại tiến trình Agent đang rảnh. Nếu Agent vượt quá timeout và thời gian gia hạn, launcher có thể đánh dấu job bị gián đoạn rồi tự khởi động Agent mới.

Operator `persistent`, chẳng hạn Rhino Server, chạy trong tiến trình Blender riêng để việc reset scene của hàng đợi không ảnh hưởng vòng đời dịch vụ.

## Kết nối công cụ của công ty

Có hai cách tích hợp, tùy công cụ công ty cung cấp.

### Công ty đã có HTTP API

Trong mục `workflow`, đổi riêng bước cần kết nối từ `local` sang `http`. Các bước còn lại vẫn có thể chạy local, vì vậy API Excel công ty và Blender Agent trên máy có thể dùng chung một workflow. Ví dụ:

```json
{
  "files": {
    "provider": "local"
  },
  "export": {
    "provider": "http",
    "url": "http://127.0.0.1:9001/export-vbom",
    "token_env": "EXCEL_API_TOKEN"
  },
  "apply": {
    "provider": "http",
    "url": "http://127.0.0.1:9002/apply-vbom",
    "token_env": "BLENDER_API_TOKEN"
  },
  "result": {
    "provider": "http",
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

Mỗi bước `http` cần URL đúng hợp đồng của bước đó. Bước `local` tiếp tục gọi adapter trong project. API điều phối local luôn chạy để phục vụ Blender Agent và operator, bất kể tổ hợp provider nào được chọn.

Nếu API công ty dùng tên tham số, cấu trúc kết quả hoặc cách xác thực khác, ưu tiên viết adapter trong **`workflows/bom_pipeline.py`** hoặc tạo một API trung gian để chuyển đổi sang hợp đồng hiện tại. Không nên nhét logic riêng của công ty vào `webui_tool.py`: file đó chỉ là cầu nối ổn định giữa Open WebUI và API điều phối. Với API xử lý bất đồng bộ, adapter cần bổ sung bước chờ và kiểm tra trạng thái.

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

### Operator Blender có dạng `bpy.ops`

Các operator tùy chọn được khai báo thành từng manifest JSON trong `tool-library/blender`. `config.json` chỉ giữ đường dẫn đến thư viện. Ollama sử dụng hai công cụ chung:

1. `list_blender_addons` đọc danh sách operator được phép gọi, kèm mô tả và tham số.
2. `run_blender_addon` nhận `id` đã chọn và chạy operator tương ứng.

Ví dụ cấu hình Rhino Server:

```json
{
  "schema_version": 1,
  "id": "start_rhino_server",
  "name": "Start Rhino Server",
  "description": "Khởi động Rhino Server khi người dùng yêu cầu kết nối hoặc sử dụng Rhino Server.",
  "executor": "blender_operator",
  "operator": "blender_rhino_server.start",
  "enabled": true,
  "execution_mode": "persistent",
  "load_model": false,
  "save_after": false,
  "timeout_seconds": 30,
  "parameters": {
    "server_adr": {
      "type": "string",
      "default": "127.0.0.1",
      "enum": ["127.0.0.1"]
    },
    "server_port": {
      "type": "integer",
      "default": 55555,
      "minimum": 1024,
      "maximum": 65535
    }
  }
}
```

`operator` là phần đứng sau `bpy.ops.`, nên `blender_rhino_server.start` sẽ gọi:

```python
bpy.ops.blender_rhino_server.start(
    server_adr="127.0.0.1",
    server_port=55555,
)
```

Mô tả phải nói rõ operator dùng trong trường hợp nào để Ollama lựa chọn đúng. `parameters` giới hạn tên, kiểu và phạm vi giá trị được phép truyền. Mọi operator hoặc tham số không có trong danh sách đều bị API từ chối.

Manifest được kiểm tra theo `schemas/tool-manifest.schema.json` khi nạp cấu hình. Trường `id` là tên ổn định mà Ollama nhìn thấy; trường `operator` là lệnh Blender thực sự. Vì vậy, khi thay add-on công ty nhưng giữ cùng mục đích nghiệp vụ, thường chỉ cần sửa manifest và adapter liên quan, không cần sửa prompt hoặc huấn luyện lại model.

Chọn `execution_mode: "persistent"` cho server hoặc operator cần giữ Blender tiếp tục chạy. Chế độ này mở một tiến trình Blender riêng và trả lại PID sau khi operator khởi động. Gọi lại cùng operator sẽ trả trạng thái `already_running` thay vì mở thêm tiến trình. Chọn `one_shot` để đưa tác vụ vào hàng đợi của Blender Agent dùng chung. Đặt `load_model: true` nếu operator cần mở file `.blend`, và `save_after: true` nếu cần lưu file sau khi chạy.

Add-on phải được cài và bật trong profile Blender được chỉ định bởi `paths.blender_exe`. Trình chạy operator tùy chọn dùng profile Blender đó để các operator công ty được đăng ký. Nếu Blender không tìm thấy operator, xem `logs/operator-<id>.log`.

Nếu add-on mới **luôn chạy cùng bước áp vật liệu**, bạn cũng có thể thêm trực tiếp lệnh gọi trong `blender/apply_vbom.py`, trước khi lưu và kiểm chứng mô hình. Cách này phù hợp khi operator là một phần bắt buộc của quy trình, không cần Ollama lựa chọn.

Để thêm một operator có dạng `bpy.ops`, sao chép một manifest trong `tool-library/blender`, đổi `id`, `operator`, mô tả và tham số rồi khởi động lại.

### Tool ngoài Blender hoặc workflow mới

Tool Library hiện có executor hoàn chỉnh cho `blender_operator`. Một add-in Excel, service nội bộ hoặc tool hệ thống khác cần một executor/adapter Python tương ứng; chỉ thêm JSON là chưa đủ. Nếu bước mới cần quy trình riêng, xử lý file đặc biệt hoặc một API khác:

1. Viết adapter/executor Python gọi API, COM, CLI hoặc SDK thật của công ty.
2. Ghép adapter vào workflow xác định trong `workflows/`, với timeout và kiểm chứng đầu ra.
3. Thêm endpoint cấp cao trong `api_service.py`.
4. Chỉ khi cần cho Ollama ra lệnh trực tiếp, thêm một phương thức tool hẹp trong `webui_tool.py` và cập nhật allowlist/hướng dẫn ở `manage.py`.
5. Thêm JSON Schema và bài kiểm thử hợp đồng cho input/output mới.

Sau khi sửa, chạy **Stop.cmd → Open-WebUI.cmd**, rồi mở chat mới. Launcher sẽ đăng ký lại công cụ và hướng dẫn trong Open WebUI. Có thể cập nhật riêng phần đăng ký khi WebUI đang chạy bằng lệnh:

```powershell
.\.venv\Scripts\python.exe manage.py sync
```

Việc thêm công cụ được thực hiện trong mã Python và mô tả công cụ; không cần huấn luyện lại mô hình AI. `setup-webui.mjs` chỉ được giữ để tương thích với lệnh cũ, không phải nơi cấu hình chính.

## Hợp đồng dữ liệu

Các file trong `schemas/` định nghĩa cấu trúc chuẩn cho manifest tool, workflow, job, kết quả tool và material recipe. `contracts.py` dùng JSON Schema Draft 2020-12 để kiểm tra dữ liệu. Định nghĩa workflow nằm trong `workflows/definitions/`.

Các schema này là ranh giới giữa AI và code thực thi: Ollama có thể chọn tool và điền tham số, nhưng Python vẫn phải xác thực dữ liệu trước khi chạm vào Excel, Blender hoặc API công ty. Khi thay tích hợp thật, nên chuyển đổi dữ liệu công ty sang hợp đồng chuẩn này trong adapter thay vì để model tự đoán cấu trúc.

## Yêu cầu của dữ liệu demo

File Excel cần có sheet `BOM` với các cột theo đúng thứ tự:

```text
Object | Material | ColorHex | Roughness | Metallic
```

BOM gồm ba đối tượng `Upper`, `Sole`, `Laces`. Mỗi đối tượng xuất hiện một lần; màu dùng định dạng `#RRGGBB`; `Roughness` và `Metallic` nhận giá trị từ 0 đến 1. VBOM được xuất theo cấu trúc XML `demo-v1`.

Demo đọc Excel bằng openpyxl. Add-on Blender mẫu được nạp tạm trong tiến trình nền và không xuất hiện trong Preferences của Blender. Luồng áp VBOM mẫu chạy với `--factory-startup`. Blender Agent đọc các manifest `blender_operator` và dùng profile Blender hiện tại để nạp add-on đã bật của công ty.

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
| `logs/operator-<id>.log` | Nhật ký của operator Blender tùy chọn |
| `runtime/results/<run_id>.json` | Trạng thái và kết quả của từng lượt chạy |
| `runtime/workflows/<job_id>.json` | Trạng thái từng bước của workflow cấp cao |
| `runtime/workflows/idempotency/` | Ánh xạ yêu cầu giống nhau tới workflow đã có |
| `<thư mục kết quả>/blender.log` | Nhật ký Blender của lượt đó |
| `runtime/services.json` | Thông tin cấu hình dịch vụ; launcher tự quản lý |

Blender Agent chỉ xử lý một job `one_shot` tại một thời điểm; các job khác chờ trong hàng đợi có giới hạn. Operator `persistent` được tuần tự hóa riêng. Workflow cấp cao tạo idempotency key từ workflow, đầu vào, thư mục đầu ra và tùy chọn mở kết quả. Gọi lại yêu cầu tương đương sẽ trả job đang chạy hoặc đã hoàn tất với `reused_job: true`.

Công cụ gọi HTTP chờ tối đa 210 giây. Nếu hết thời gian chờ, dùng `get_bom_pipeline_job` hoặc `get_blender_job` với đúng mã job trước khi quyết định chạy lại. Không bật `force_new` chỉ vì giao diện hết thời gian chờ. Nếu tiến trình bị ngắt đột ngột, xem trạng thái job và nhật ký để xác định bước bị gián đoạn.

## Kiểm thử và sao lưu

Chạy các lệnh sau từ thư mục project:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\Start-OpenWebUI.ps1 -NoBrowser
.\.venv\Scripts\python.exe tests\smoke_api.py
.\.venv\Scripts\python.exe tests\smoke_agent.py
.\.venv\Scripts\python.exe tests\smoke_workflow.py
.\.venv\Scripts\python.exe tests\smoke_idempotency.py
.\.venv\Scripts\python.exe tests\smoke_webui.py
.\.venv\Scripts\python.exe tests\smoke_webui_agent.py
```

Các bài kiểm tra đơn vị bao gồm cấu hình, quyền truy cập đường dẫn, JSON Schema, Tool Library, workflow, idempotency, hàng đợi và thao tác hủy job. Bài thử Agent chạy cube và UV sphere trên cùng PID, kiểm tra thứ tự hàng đợi, reset scene, một job lỗi và job phục hồi tiếp theo. Bài thử workflow chạy thật Excel → VBOM → Blender → verify. Bài thử WebUI tạo chat thật để xác nhận Ollama chọn đúng workflow cấp cao; bài thử WebUI Agent xác nhận model chọn operator từ allowlist.

Kết quả kiểm thử được lưu trong `evidence/`; các file Blender được tạo trong thư mục đầu ra đã cấu hình.

Để cài trên máy khác, tải lại repository và chạy `Install.cmd`. Môi trường `.venv` và `.python` cần được tạo trên máy đó. Để sao lưu lịch sử chat và cấu hình WebUI, giữ cả `webui-data/` lẫn `.webui_secret_key`; sao lưu riêng dữ liệu đầu vào và kết quả mà bạn muốn giữ.
