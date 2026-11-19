# Thêm và thay integration

Tài liệu này mô tả chính xác những file cần thay đổi khi:

- thêm một Blender add-on mới;
- cập nhật hoặc thay Blender add-on hiện có;
- thay Excel VBA add-in;
- kiểm tra Qwen có chọn đúng hành động mà không nhận quá nhiều candidate.

## 1. Cách hệ thống chọn và gọi integration

Open WebUI chỉ gửi nội dung chat tới REST agent. Qwen không nhận trực tiếp toàn bộ
macro hay operator trên máy.

```text
Open WebUI
  → REST agent
  → Qwen 4B phân loại intent
  → Python lấy capability đang bật từ registry
  → Python chỉ giữ tối đa 5 candidate liên quan
  → Qwen 4B chọn candidate và trích tham số
  → Python kiểm tra enum, schema, allowlist và đường dẫn
  → Excel COM/VBA hoặc Blender subprocess
```

`qwen3.5:0.8b` chỉ trả lời chat ngắn. Model này không chọn hoặc chạy Excel/Blender.

Nguồn capability:

- capability lõi: `capabilities.json`;
- Blender add-on pack: `addons/<module>/addon.json`;
- tài liệu phục vụ retrieval: `addons/<module>/docs.md`;
- workflow tùy chọn: `addons/<module>/workflows/*.json`.

Chỉ operator có `enabled: true` và `expose: generic` do registry tạo mới có thể
trở thành candidate cho Qwen. Tên candidate bị khóa bằng JSON Schema `enum`; model
không thể hợp lệ hóa một capability ngoài danh sách Python đã cấp.

## 2. Thuật ngữ Blender

Ba tên sau không giống nhau:

| Loại | Ví dụ | Dùng ở đâu |
|---|---|---|
| Module add-on | `my_company_addon` | import/cài trong Blender và tên thư mục pack |
| Operator idname | `my_company.build_asset` | `bl_idname` thật của Blender operator |
| Capability ID | `blender.my_company_addon.build_asset` | ID ổn định mà agent/Qwen sử dụng |

Không nên đổi Capability ID nếu hành động vẫn giữ cùng ý nghĩa. ID ổn định giúp
prompt, test và workflow cũ tiếp tục hoạt động.

## 3. Thêm Blender add-on mới

### 3.1. Chuẩn bị add-on

Add-on phải import được trong Blender background sử dụng bởi `config.json`. Operator
cần đáp ứng:

- có `bl_idname` và `bl_description` rõ ràng;
- không dùng `bl_options = {'INTERNAL'}`;
- chạy được khi Blender dùng `--background`;
- không phụ thuộc vào panel đang mở, selection thủ công hoặc UI modal;
- trả `{'FINISHED'}` khi thành công và báo lỗi rõ khi thất bại;
- tham số nên dùng `BoolProperty`, `IntProperty`, `FloatProperty`,
  `StringProperty`, `EnumProperty` hoặc vector scalar cố định;
- đường dẫn file/thư mục nên khai báo subtype `FILE_PATH` hoặc `DIR_PATH` để hệ
  thống áp dụng kiểm tra phạm vi đường dẫn.

Pointer/collection phức tạp, operator internal và operator không chạy được trong
background không nên công khai cho agent.

### 3.2. Discovery trước khi đăng ký

```powershell
cd E:\3d\ollama_3d-publish
.\.venv\Scripts\python.exe manage.py discover --module my_company_addon
```

Xem kết quả tại:

```text
runtime/discovered/my_company_addon.json
```

Kiểm tra `operator_ids`, schema tham số, giá trị enum, minimum/maximum,
`poll_default` và các thuộc tính unsupported. Discovery không tự bật operator.

### 3.3. Tạo pack metadata

```powershell
.\.venv\Scripts\python.exe manage.py addon add my_company_addon
```

Lệnh tạo:

```text
addons/my_company_addon/addon.json
```

Tất cả operator mới có `enabled: false`. Đây là trạng thái đúng; không bật toàn bộ
add-on chỉ để thử.

Mỗi operator nên được kiểm tra và chỉnh metadata:

```json
{
  "module": "my_company_addon",
  "description": "Các thao tác dựng asset nội bộ.",
  "operators": {
    "my_company.build_asset": {
      "id": "blender.my_company_addon.build_asset",
      "enabled": false,
      "risk": "filesystem",
      "description": "Dựng một asset từ file cấu hình và lưu scene kết quả.",
      "background_safe": true,
      "params": {
        "type": "object",
        "properties": {
          "config_path": {"type": "string", "x-path": true},
          "quality": {"type": "string", "enum": ["draft", "final"]}
        },
        "required": ["config_path", "quality"],
        "additionalProperties": false
      }
    }
  }
}
```

`additionalProperties` phải là `false`. Đường dẫn phải có `x-path: true`. Không
thêm tham số kiểu Python code, expression hoặc script.

### 3.4. Viết tài liệu để Qwen chọn đúng

Tạo `addons/my_company_addon/docs.md`. Nội dung nên ghi:

- operator làm gì và không làm gì;
- các cụm từ người dùng thường nói;
- ý nghĩa và ví dụ của từng tham số;
- file đầu vào/đầu ra;
- điều kiện tiên quyết;
- trường hợp cần hỏi lại thay vì chạy.

Trong `addon.json`, có thể gắn tài liệu cho operator:

```json
"docs": "docs.md"
```

Đường dẫn `docs` phải nằm trong chính thư mục pack. Agent chỉ đọc tối đa 3.000 ký
tự và coi tài liệu là dữ liệu tham chiếu, không phải instruction có quyền vượt qua
allowlist.

Để giảm chọn nhầm:

- mô tả mỗi operator bằng một hành động duy nhất;
- dùng từ khóa khác nhau cho các operator có ý nghĩa khác nhau;
- tránh các mô tả chung như “process file” hoặc “run action”;
- không bật hai operator đồng nghĩa nếu chỉ cần một;
- giữ số operator được bật ở mức tối thiểu.

### 3.5. Bật đúng operator

```powershell
.\.venv\Scripts\python.exe manage.py addon enable `
  my_company_addon my_company.build_asset
```

Tắt lại khi cần:

```powershell
.\.venv\Scripts\python.exe manage.py addon disable `
  my_company_addon my_company.build_asset
```

Registry hot-reload `addon.json`, `docs.md` và workflow metadata. Không cần restart
chỉ để thay metadata. Nếu đã thay mã Python của API/adapter, chạy lại
`Open-WebUI.cmd` để fingerprint khởi động đúng phiên bản.

### 3.6. Checklist kiểm thử add-on

```powershell
# Cấu hình và registry
.\.venv\Scripts\python.exe manage.py check

# Toàn bộ contract/acceptance test
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v

# Đánh giá router/selector Qwen, không chạy Blender workflow
.\.venv\Scripts\python.exe tests\eval_models.py --models qwen3.5:4b
```

Sau đó thử một yêu cầu cố ý thiếu `model_path` hoặc `output_dir`. Kết quả đúng là:

- Qwen chọn đúng Capability ID;
- trạng thái là `needs_input`;
- Blender chưa chạy.

Cuối cùng mới chạy với file test thật và kiểm tra `output_path`, proof JSON và file
`.blend` sau khi mở lại.

## 4. Cập nhật hoặc thay Blender add-on

### 4.1. Cùng module, implementation thay đổi nhưng contract giữ nguyên

Nếu module, operator idname và schema tham số không đổi:

1. sao lưu bản add-on đang hoạt động;
2. cài/chép phiên bản add-on mới vào Blender;
3. chạy lại discovery;
4. so sánh report mới với `addons/<module>/addon.json`;
5. chạy `manage.py check` và acceptance test;
6. giữ nguyên Capability ID và trạng thái enable.

```powershell
.\.venv\Scripts\python.exe manage.py discover --module my_company_addon
```

`addon add` không dùng để ghi đè pack đang tồn tại. Lệnh sẽ dừng nếu thư mục pack
đã có, nhằm tránh vô tình mất allowlist và mô tả đã review.

### 4.2. Cùng module nhưng operator hoặc tham số thay đổi

Thứ tự an toàn:

1. disable operator bị ảnh hưởng;
2. cài phiên bản add-on mới;
3. chạy discovery và xem report mới;
4. cập nhật thủ công đúng entry trong `addon.json`;
5. cập nhật `description`, `docs.md` và workflow phụ thuộc;
6. chạy test khi operator vẫn đang disable;
7. enable lại đúng operator sau khi test đạt.

```powershell
.\.venv\Scripts\python.exe manage.py addon disable `
  my_company_addon my_company.build_asset

.\.venv\Scripts\python.exe manage.py discover --module my_company_addon
```

Quy tắc tương thích:

- cùng ý nghĩa: giữ Capability ID;
- đổi ý nghĩa: tạo Capability ID mới, mặc định disable;
- operator đã bị xóa: xóa entry cũ khỏi pack sau khi workflow không còn tham chiếu;
- thêm tham số required: cập nhật docs, test và mọi workflow gọi operator;
- đổi enum/min/max: cập nhật schema theo report discovery;
- đổi operator idname: cập nhật key operator và `target`, nhưng chỉ giữ Capability ID
  nếu hành vi thực sự tương thích.

### 4.3. Đổi sang module add-on khác

Không ghi đè pack cũ ngay:

1. cài module mới;
2. `addon add <module_mới>`;
3. review metadata và docs;
4. bật một operator mới;
5. kiểm thử Qwen selection và Blender thật;
6. disable operator tương ứng của module cũ;
7. theo dõi một thời gian rồi mới bỏ pack cũ.

Cách này giữ rollback: chỉ cần disable module mới và enable lại operator cũ.

## 5. Thay Excel VBA add-in

Excel không dùng discovery. Python gọi đúng macro được allowlist trong
`capabilities.json` bằng Windows COM.

### 5.1. Contract bắt buộc

Add-in tương thích phải là `.xlam` và cung cấp hai public macro trong standard VBA
module:

```text
Ollama3D_Ping() As String
ExportVBOM(source_excel, output_directory, run_id) As String
```

`Ollama3D_Ping` phải trả:

```text
ollama3d-proof|<version>
```

`ExportVBOM` phải:

- đọc workbook `source_excel`;
- tạo `<output_directory>/materials.vbom`;
- tạo `<output_directory>/excel-proof.json`;
- ghi đúng `run_id` và `producer: ollama3d-vba` trong proof;
- trả về đường dẫn tuyệt đối của `materials.vbom`.

Adapter sẽ từ chối kết quả nếu tên file, producer, run ID hoặc đường dẫn proof không
khớp. Excel được mở bằng `DispatchEx`, add-in read-only và tiến trình được đóng sau
mỗi tác vụ.

### 5.2. Thay file nhưng giữ tên và macro

Nếu file mới vẫn tên `Ollama3DProof.xlam` và giữ hai macro trên, chỉ cần:

1. sao lưu file hiện tại;
2. đặt file mới ở vị trí mong muốn;
3. sửa `excel_vba.addin_path` trong `config.json` nếu đường dẫn thay đổi;
4. chạy kiểm tra bên dưới.

Ví dụ:

```json
"excel_vba": {
  "executable": "C:/Program Files/Microsoft Office/Root/Office16/EXCEL.EXE",
  "addin_path": "excel/Ollama3DProof.xlam",
  "timeout_seconds": 90
}
```

### 5.3. Đổi tên file add-in

Nếu đổi thành `CompanyTools.xlam`, phải sửa cả ba vị trí logic:

1. `config.json` → `excel_vba.addin_path`;
2. `capabilities.json` → target của `excel.ping`;
3. `capabilities.json` → target của `excel.export_vbom`.

```json
{
  "id": "excel.ping",
  "target": "'CompanyTools.xlam'!Ollama3D_Ping"
}
```

```json
{
  "id": "excel.export_vbom",
  "target": "'CompanyTools.xlam'!ExportVBOM"
}
```

Tên workbook trong target phải trùng chính xác tên file được mở. Chỉ đổi
`addin_path` mà không đổi target sẽ khiến Excel tìm workbook macro cũ và thất bại.

### 5.4. Đổi tên macro hoặc contract

Nếu chỉ đổi tên macro, cập nhật target tương ứng trong `capabilities.json`. Nếu đổi
tham số hoặc định dạng kết quả, cần cập nhật đồng bộ:

- `scripts/excel_vba_worker.py` — cách truyền đối số và nhận giá trị;
- `adapters/excel_vba.py` — kiểm tra kết quả/proof;
- workflow sử dụng kết quả;
- unit test và test Excel thật;
- version trong capability nếu contract đã thay đổi.

Không cho Qwen truyền tên macro. Macro luôn phải được chọn từ allowlist registry.

### 5.5. Kiểm thử add-in mới

```powershell
# Kiểm tra file, registry và dependency
.\.venv\Scripts\python.exe manage.py check

# Khởi động lại API khi config/source đã đổi
.\Open-WebUI.cmd --no-browser

# Trạng thái dịch vụ
.\.venv\Scripts\python.exe manage.py status
```

Chạy workflow thật vào thư mục test riêng:

```powershell
$body = @{
  excel_path = 'inputs/Footwear_BOM.xlsx'
  model_path = 'inputs/Sneaker_Unassigned.blend'
  output_dir = 'outputs/addin-acceptance'
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8090/proof/run `
  -ContentType application/json `
  -Body $body `
  -TimeoutSec 300
```

Kết quả chỉ đạt khi:

- step `export_vbom_with_vba` là `completed`;
- `excel-proof.json` tồn tại và đúng version/run ID;
- step Blender là `completed`;
- `verification.json` xác nhận mở lại `.blend` thành công.

## 6. Rollback

### Blender

- disable operator mới;
- enable lại operator cũ;
- phục hồi add-on Python cũ trong Blender;
- phục hồi `addon.json`/`docs.md` từ Git nếu metadata đã đổi;
- chạy `manage.py check` và test lại.

### Excel

- phục hồi `.xlam` cũ;
- phục hồi `addin_path` và hai macro target;
- chạy `Open-WebUI.cmd --no-browser`;
- chạy một workflow acceptance vào output mới.

Không dùng output của lần chạy thất bại làm input cho lần rollback test.

## 7. Checklist trước khi commit/push

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests\smoke_rest.py
.\.venv\Scripts\python.exe manage.py status
git diff --check
git status --short
```

Không commit `.xlam` mới nếu chưa xác minh macro thật. Không commit `runtime/`,
`outputs/`, `logs/`, `evidence/` hoặc dữ liệu workbook khách hàng.
