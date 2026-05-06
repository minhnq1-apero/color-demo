# Tool flow — SVG → Iceors color-by-number

Tài liệu mô tả luồng xử lý từ ảnh SVG đầu vào đến file ZIP output mà
app Android nạp được. Tập trung vào *bước làm gì*, không phải *làm bằng gì*.

---

## Tổng quan

```
SVG file
   │
   ▼
[1] Đọc kích thước & viewBox, pad vuông
   │
   ▼
[2] Duyệt từng shape (path / polygon / rect / circle / ellipse / line)
   │   – flatten transform của parent group nếu có
   │   – chuyển mọi shape về dạng path "M…L…C…Q…Z"
   │   – scale tọa độ về canvas đích
   │
   ▼
[3] Đọc thuộc tính `fill` và `stroke` của mỗi shape
   │   – có fill?    → ghi nhận là FILL region
   │   – có stroke?  → ghi nhận là STROKE line
   │
   ▼
[4] Gộp các màu fill gần giống nhau thành cùng 1 màu palette
   │   (theo khoảng cách màu RGB; vùng lớn được giữ làm "đại diện")
   │
   ▼
[5] Sắp xếp FILL theo diện tích giảm dần
   │   (vùng lớn → đáy stack, vùng nhỏ → đỉnh stack)
   │
   ▼
[6] Trừ chồng lấp: mỗi vùng chỉ giữ những điểm ảnh KHÔNG nằm dưới vùng nào ở trên
   │
   ▼
[7] (Optional) Phát sinh đường viền đen cho mỗi vùng FILL
   │
   ▼
[8] Sinh dòng dữ liệu cho từng FILL và STROKE
   │   – mỗi shape → 1 dòng pipe-delimited
   │
   ▼
[9] Đóng gói ZIP
   │   – data file
   │   – ảnh JPEG render từ SVG (làm reference cho app)
   │   – flag file
   │
   ▼
File ZIP sẵn sàng nạp vào app
```

---

## Chi tiết từng bước

### 1. Đọc & pad vuông

- Đọc viewBox của SVG (hoặc width/height nếu thiếu viewBox).
- Tính cạnh `side = max(width, height)`.
- Tạo affine transform: dịch SVG vào giữa khung vuông `side × side`,
  rồi scale về `OUTPUT_CANVAS` (mặc định 2048).
- Đảm bảo aspect ratio output luôn 1:1 — khớp canvas mà app yêu cầu.

### 2. Duyệt shapes & flatten transform

- Duyệt cây SVG, lấy mọi node là shape thực sự (bỏ qua `<g>`, `<defs>`...).
- Với mỗi shape: gom toàn bộ transform của các parent group nhân với
  affine ở bước 1, rồi áp xuống tọa độ thực của shape.
- Mọi loại hình (rect, circle, polygon, line, …) được quy về cùng một
  định dạng path để xử lý đồng nhất ở các bước sau.
- Cung tròn (Arc) trong path được xấp xỉ bằng các đoạn cubic Bézier
  để dùng được với mọi trình render path.

### 3. Phân loại fill / stroke

- Shape có `fill` không phải `none`/`transparent` → tạo 1 entry **FILL**.
- Shape có `stroke` và `stroke-width > 0` → tạo 1 entry **STROKE**.
- Một shape có thể đồng thời tạo cả 2 entry.
- Stroke-width được scale theo cùng tỉ lệ canvas.
- Black tinh (`#000000`) và white tinh (`#FFFFFF`) được "bump" 1 đơn vị
  để tránh trùng giá trị mà app coi là "không tô được" hoặc "bị bỏ".

### 4. Gộp màu gần giống

- Vectorizer hay sinh nhiều shade rất gần nhau cho cùng một vùng "trông
  như một màu" (do anti-aliasing, JPEG noise...).
- Các màu cách nhau dưới `merge_tolerance` (RGB Euclidean) được gộp.
- Thuật toán: sắp xếp màu theo tổng diện tích giảm dần; mỗi màu mới
  hoặc tự thành 1 slot palette mới, hoặc remap về slot kề gần đã có.
- Diện tích lớn hơn được "ưu tiên" làm đại diện → màu chủ đạo không bị
  thay bởi shade phụ.

### 5. Sắp xếp theo diện tích

- App vẽ FILL theo thứ tự xuất hiện trong file: trước → đáy, sau → đỉnh.
- Sắp diện tích giảm dần để vùng nền lớn vẽ trước, chi tiết nhỏ vẽ sau
  (chi tiết luôn nằm trên cùng).

### 6. Trừ chồng lấp

- Sau khi sắp xếp, đi từ vùng trên cùng (nhỏ nhất) xuống dưới cùng
  (lớn nhất).
- Tích lũy vùng `above_union` = hợp tất cả vùng đã xét.
- Vùng đang xét bị trừ đi `above_union` → chỉ còn pixels mà chưa vùng
  nào ở trên đã giữ.
- Kết quả: mọi vùng phủ một bộ pixel rời rạc — khi user tô từng vùng,
  không vùng nào lấn vào vùng khác.
- Phép trừ tính trên cubic Bézier trực tiếp (không flatten về polygon),
  giữ nguyên độ mượt của đường biên gốc.

### 7. Sinh outline (tuỳ chọn)

- Khi user bật **Auto outline**: với mỗi vùng FILL sau bước 6, tạo thêm
  1 entry STROKE đen có cùng path d, độ dày do user chọn.
- Vì share đúng `d` của fill (đã trừ chồng lấp), outline khít khao —
  không lệch nửa pixel.
- Không trùng với stroke đã có sẵn từ SVG (bước 3) — đó là 2 nguồn
  riêng biệt cộng dồn.

### 8. Sinh dòng dữ liệu

Định dạng mỗi dòng:

```
{path d} | {hex color} | {stroke width} | {label position} | {font size}
```

- **FILL entry**: `{d}|{RRGGBB}|0|{cy*canvas + cx}|12`
  - stroke_width = 0 → app phân loại là vùng tô được
  - color = hex 6 chữ
  - label_position = bbox center (để hiển thị số bên trong vùng)
- **STROKE entry**: `{d}|0|{width}|0|0`
  - stroke_width > 0 → app phân loại là decoration line
  - color sentinel "0" — app render màu đen cố định cho mọi STROKE

Tất cả dòng nối bằng CRLF (`\r\n`).

### 9. Đóng gói ZIP

ZIP chứa 3 file:

- `{key}b` — dữ liệu path từ bước 8
- `{key}c` — ảnh JPEG 2048×2048 render từ SVG gốc (làm reference cho
  app, ví dụ chế độ "reveal" hoặc thumbnail)
- `sp_new_paint_flag` — flag nội dung `"111\r\n"`, app cần để nhận diện
  định dạng

---

## Chế độ Manual (vẽ tay)

Tồn tại song song dùng cho ảnh raster (PNG/JPG) không có sẵn vector:

```
Ảnh raster
   │
   ▼
Hiển thị canvas + cho user click từng vertex của polygon
   │
   ▼
User nhấn "Close" — polygon thành 1 vùng
   │
   ▼
Tự đo màu chủ đạo bên trong polygon (median RGB của pixels gốc)
   │
   ▼
Vào pipeline ở bước 5 (sắp xếp & sinh dòng dữ liệu)
```

Trade-off: precision cao hơn (user kiểm soát 100%) nhưng tốn thời gian
hơn cho ảnh có nhiều vùng.

---

## Tham số người dùng có thể chỉnh

| Tham số | Ý nghĩa | Khi nào tăng / giảm |
|---|---|---|
| `Merge tolerance` | Khoảng RGB để gộp màu | Tăng nếu palette còn quá nhiều shade gần giống |
| `Subtract overlaps` | Bật trừ chồng lấp | Để **bật** trừ khi muốn giữ nguyên SVG y nguyên |
| `Auto outline` | Vẽ nét đen quanh fill | Bật để app hiển thị rõ vùng khi chưa tô |
| `Outline width` | Độ dày nét đen | Tăng cho ảnh lớn / cần nhìn rõ hơn |
| `Asset key` | Tên file trong ZIP | Tuỳ ý, không dấu cách |

---

## Quy ước input mong muốn

- Mỗi vùng màu là 1 shape độc lập, fill solid (không gradient)
- Đường viền nghệ thuật là shape có stroke đen
- Shape không có fill và không có stroke → bị bỏ qua
- viewBox đặt cho cả khung hình, không quan trọng vuông hay không
  (tool tự pad vuông)
- Tránh các pattern, mask, clipPath phức tạp — sẽ bị bỏ qua
