# Báo cáo phân tích app Color by Number (`com.sycb.coloring.book`)

**Mục tiêu:** hiểu luồng hoạt động và cơ chế "tô màu lên ảnh" của ứng dụng.
**Phương pháp:** dùng `apktool` decode resource + `jadx` decompile DEX → Java/Kotlin, sau đó đọc các class lõi.
**Phiên bản:** 1.0.5 (split APK: `base.apk` + `arm64_v8a` + `en` + `xxhdpi`).

---

## 1. Ý tưởng cốt lõi

App **không thật sự "vẽ"** lên ảnh. Cơ chế là **xếp chồng 3 bitmap** và khi người dùng chạm vào một vùng, app **xóa các pixel của vùng đó ở lớp trên cùng** để lộ ra ảnh màu nằm bên dưới. Đây là kỹ thuật **layered-bitmap reveal**.

```
┌─────────────────────────┐  ← canvas hiển thị
│   số (Canvas.drawText)  │
│   hintBitmap            │  (lớp gợi ý)
│   mStock (canvas trắng) │  ← bị xóa pixel khi tô
│   mBoard (ảnh màu)      │  ← lộ ra ở vùng đã tô
└─────────────────────────┘
```

---

## 2. Cấu trúc tài nguyên (assets)

Mỗi tranh tô màu là **một thư mục** trong `assets/<category>/<item>/`. Ví dụ `assets/animal/animal_1/`:

| File | Vai trò |
|------|---------|
| `fill_1.png` | Ảnh màu hoàn chỉnh — **lớp đáy**, sẽ lộ ra dần khi tô |
| `stock_1.png` | Canvas trắng có nét line-art + số — **lớp trên cùng**, bị "khoét" khi tô |
| `thumbnail_1.png` | Thumbnail hiển thị ngoài danh sách |
| `level.txt` | JSON metadata: danh sách level (mỗi level = một mã màu) và toạ độ neo của các vùng |

Cấu trúc `level.txt`:

```json
{
  "levels": [
    {
      "level": 1,
      "color": "#EA8622",
      "textColor": "#000000",
      "coordinates": [
        { "x": 110, "y": 299, "textSize": 22 },
        { "x": 593, "y": 262, "textSize": 22 },
        ...
      ]
    },
    ...
  ]
}
```

Lưu ý: JSON **chỉ chứa toạ độ neo** `(x, y)` của mỗi vùng và kích thước số sẽ vẽ. **Tập pixel thuộc về vùng đó được tính ở runtime** bằng flood fill (xem mục 4).

---

## 3. Bốn class lõi

| File | Vai trò |
|------|---------|
| `model/SYCB_Level.java` + `model/SYCB_Coordinate.java` | Data model JSON — level chứa nhiều coordinate; mỗi coordinate có `(x, y, textSize)`, danh sách `points` (transient, lấp ở runtime) và cờ `isLevelCompleted` |
| `ColoringModel/SYCB_FloodFill.java` | Thuật toán **flood fill scanline** — đầu vào là một điểm seed, đầu ra là `ArrayList<Point>` chứa toàn bộ pixel của vùng đó trên ảnh stock |
| `ColoringModel/SYCB_KKView.java` | Custom `View` — sở hữu Matrix biến đổi, GestureDetector, vẽ bitmap và xử lý tap |
| `activity/SYCB_ColoringActivity.java` | Activity chính — tải ảnh + JSON, khởi động flood fill ngầm, lắng nghe sự kiện hoàn thành level |

---

## 4. Luồng tải dữ liệu (load-time)

Khởi điểm: `SYCB_ColoringActivity.l()` (line 130 trong file decompile).

1. **Đọc intent** lấy `SYCB_ItemBean`, trích `stockImagePath`, `fillImagePath`, `jsonPath`.
2. **Decode 3 bitmap:**
   ```java
   mBoard      = cbLoadImageFromAssets(this, fillImagePath);   // ảnh màu
   mStock      = cbLoadImageFromAssets(this, stockImagePath);  // canvas trắng
   hintBitmap  = cbLoadImageFromAssets(this, stockImagePath);  // bản sao cho hint
   ```
3. **Khởi tạo flood fill** với ảnh stock:
   ```java
   SYCB_FloodFill flood = new SYCB_FloodFill(mStock);
   ((SYCB_KKView) view).imageSet(mBoard, mStock, flood);
   ```
4. **Parse JSON** → `SYCB_JsonData { levels: [...] }`.
5. **Tính trước tập pixel của từng vùng** (chạy nền — `NumberingDataManage.numberingDataManageNotDir`):
   ```java
   for (level in levels) {
       for (coord in level.coordinates) {
           ArrayList<Point> pts = flood.cbAdvanceHintFill(new Point(coord.x, coord.y));
           coord.setPoints(pts);
       }
   }
   ```
   Bước này **chạy 1 lần khi mở tranh** trên một executor riêng. Lý do: flood fill quét pixel-by-pixel nên chậm; làm trước thì khi tap chỉ cần `Set.contains`, phản hồi tức thì.

---

## 5. Thuật toán flood fill (`SYCB_FloodFill.cbAdvanceHintFill`)

Đây là **scanline flood fill**, không đệ quy:

```java
public ArrayList<Point> cbAdvanceHintFill(Point seed) {
    pixelsArea = new boolean[width * height];           // bitmap đánh dấu pixel đã thăm
    LinkedList<Point> queue = new LinkedList<>();
    queue.add(seed);

    while (!queue.isEmpty()) {
        Point p = queue.poll();
        int x = p.x, y = p.y;

        // chạy về trái cho đến khi gặp đường biên
        while (x > 0 && cbIsPixelReplacable(x - 1, y)) x--;

        // quét sang phải, đánh dấu và queue lên/xuống
        while (x < width && cbIsPixelReplacable(x, y)) {
            cbSetPixelReplaced(x, y);
            result.add(new Point(x, y));
            if (y > 0       && cbIsPixelReplacable(x, y - 1)) queue.add(new Point(x, y - 1));
            if (y < height-1 && cbIsPixelReplacable(x, y + 1)) queue.add(new Point(x, y + 1));
            x++;
        }
    }
    return result;
}
```

**Định nghĩa pixel "có thể tô"** (`cbIsPixelReplacable`): pixel chưa thăm + **không phải đường nét đen**. Cách phân biệt nét đen: tách RGB từ pixel ARGB, nếu `R == G == B` (xám) **và** giá trị ≤ 100 thì coi là nét → bỏ qua. Tức là vùng "tô được" là mọi pixel **không phải xám-tối** (trắng, kem, chống aliasing v.v. đều OK).

```java
int r = (px >> 16) & 0xff;
int g = (px >> 8)  & 0xff;
int b =  px        & 0xff;
return !(r == g && g == b && r <= 100);
```

---

## 6. Render — `SYCB_KKView.onDraw`

```java
canvas.save();
canvas.concat(mMatrix);                                 // pan + zoom
canvas.drawBitmap(mBoard, 0, 0, null);                  // (1) ảnh màu — đáy
canvas.drawBitmap(mStock, 0, 0, null);                  // (2) canvas trắng — che (1)
canvas.drawBitmap(hintBitmap, 0, 0, null);              // (3) hint nếu có
// (4) vẽ số cho các coordinate chưa hoàn thành
for (level in dataList)
    for (coord in level.coordinates)
        if (!coord.isCompleted && coord.textSize >= getTextLimit(zoom))
            cbSetTextData(canvas, coord, coord.x, coord.y, level.level.toString());
canvas.restore();
```

**Tối ưu:** `getTextLimit(zoom)` ẩn số ở các vùng quá nhỏ khi zoom thấp (ví dụ vùng `textSize < 25` bị ẩn ở zoom ≤ 1) để tránh nhiễu thị giác. Khi zoom lên, số nhỏ mới hiện ra.

---

## 7. Xử lý tap — "tô màu một vùng"

Hàm trung tâm: `SYCB_KKView.cbOnSingleClick(float screenX, float screenY)`.

```java
// 1. quy đổi toạ độ màn hình → toạ độ bitmap qua ma trận đảo
float[] pt = {screenX, screenY};
Matrix inv = new Matrix();
mMatrix.invert(inv);
inv.mapPoints(pt);
int x = (int) pt[0], y = (int) pt[1];

// 2. duyệt các vùng của level đang chọn (hintList) — tìm vùng chứa pixel (x, y)
for (SYCB_Coordinate coord : hintList) {
    if (coord.getPoints().contains(new Point(x, y))) {

        // 3. xoá pixel của vùng đó trên mStock và hintBitmap
        mStock     = floodFill.makePointsTransparent(mStock,     new Point(x, y));
        hintBitmap = floodFill.makePointsTransparent(hintBitmap, new Point(x, y));

        coord.setLevelCompleted(true);
    }
}

// 4. nếu mọi coordinate trong hintList đều xong → callback levelUp
// 5. invalidate() để onDraw chạy lại
invalidate();
```

`makePointsTransparent(bitmap, seed)` chạy lại flood fill từ `seed` rồi gọi `bitmap.setPixel(p.x, p.y, 0)` — alpha 0 — cho từng pixel. Sau khi xoá, lớp `mStock` ở vùng đó **trong suốt**, lộ ra mảng màu của `mBoard` bên dưới ⇒ trông như "đã được tô".

---

## 8. Pan / zoom

Tất cả biến đổi dồn vào một `Matrix mMatrix` duy nhất:

| Tương tác | Xử lý |
|----------|-------|
| `ScaleGestureDetector.onScale` | `mMatrix.postScale(factor, focusX, focusY)` |
| `GestureDetector.onScroll` | `mMatrix.postTranslate(-dx, -dy)` |
| `onSizeChanged` | tính scale ban đầu để vừa khít view, rồi `postTranslate` để căn giữa |
| `cbZoom()` (nút "find next") | tự zoom ×5 vào coordinate chưa hoàn thành đầu tiên |

Mọi tap đều phải `mMatrix.invert()` rồi `mapPoints()` để chuyển từ toạ độ màn hình về toạ độ bitmap gốc — đó là lý do duy nhất ma trận tham gia vào logic tap.

---

## 9. Tính năng phụ liên quan tới drawing

- **Hint** (`newHintSet`): khi bấm gợi ý, app dựng lại `hintBitmap` bằng cách đè màu (lấy từ `mBoard`) lên các pixel của những vùng **chưa hoàn thành** ở level hiện tại — chạy trong `Executors.newSingleThreadExecutor()`.
- **Lưu tiến trình:** `SYCB_FileHelper` ghi lại `mStock` hiện tại + `data.json` cập nhật cờ `isLevelCompleted` xuống thư mục riêng (`progressStockImagePath`). Khi mở lại tranh, nếu `intent.dir == true && restart == false` thì load `progressStockImagePath` thay vì `stockImagePath`.
- **Xuất ảnh:** `SYCB_KKView.getDrawBitmap()` tạo bitmap `ARGB_8888` mới và vẽ chồng `mBoard` rồi `mStock` lên, sau đó `SYCB_FileHelper.cbSaveBitmapImageToGallery` lưu JPEG vào `Pictures/SYCB_Coloring Number/`.

---

## 10. Tóm tắt sơ đồ luồng

```
┌──────────────────────────────────────────────────────────────────┐
│ MỞ TRANH                                                          │
│  SYCB_ColoringActivity.onCreate                                   │
│    └─ l(): load 3 bitmap + JSON                                   │
│         └─ new SYCB_FloodFill(mStock)                             │
│         └─ KKView.imageSet(mBoard, mStock, flood)                 │
│         └─ NumberingDataManage (background)                       │
│              for each coord:                                      │
│                 coord.points = flood.cbAdvanceHintFill(coord.xy)  │
│                                                                   │
│ NGƯỜI DÙNG TƯƠNG TÁC                                              │
│  KKView.onTouchEvent                                              │
│    ├─ scale  → mMatrix.postScale  → invalidate                    │
│    ├─ scroll → mMatrix.postTranslate → invalidate                 │
│    └─ tap    → cbOnSingleClick                                    │
│                ├─ mMatrix⁻¹ . map(tapXY) = bitmap (x, y)          │
│                ├─ tìm coord chứa Point(x, y)                      │
│                ├─ mStock     = flood.makePointsTransparent(...)   │
│                ├─ hintBitmap = flood.makePointsTransparent(...)   │
│                ├─ coord.completed = true                          │
│                └─ invalidate                                      │
│                                                                   │
│ RENDER                                                            │
│  KKView.onDraw                                                    │
│    ├─ canvas.concat(mMatrix)                                      │
│    ├─ drawBitmap(mBoard)   ← lộ qua các pixel trong suốt          │
│    ├─ drawBitmap(mStock)   ← bị "khoét" dần ở các vùng đã tô      │
│    ├─ drawBitmap(hintBitmap)                                      │
│    └─ drawText cho mỗi coord chưa hoàn thành (filter theo zoom)   │
└──────────────────────────────────────────────────────────────────┘
```

---

## 11. Điểm mấu chốt cần nhớ nếu muốn tự cài đặt

1. **Hai ảnh, một file JSON** là đủ data: `fill.png` (đáp án màu), `stock.png` (canvas trắng + nét + số), `level.txt` (mã màu + toạ độ neo của vùng).
2. **Flood fill 1 lần lúc tải**, không tô lúc tap.
3. **"Tô màu" thực chất là `setPixel(..., 0)`** trên lớp trên cùng để lộ lớp dưới. Không có `Paint.setColor` nào liên quan.
4. **Pan/zoom dồn về một `Matrix`**. Tap luôn map ngược qua matrix đảo trước khi xử lý logic.
5. **Số được vẽ động** bằng `Canvas.drawText` mỗi frame, không phải đốt sẵn vào bitmap — nhờ vậy có thể ẩn/hiện theo zoom và tự biến mất khi vùng hoàn thành.
6. **Ngưỡng nét đen** trong `cbIsPixelReplacable`: `R==G==B && R<=100` — đơn giản nhưng đủ tốt với line-art chuẩn.

---

## Phụ lục: vị trí file decompile

```
/Users/macmini0051/Workspace/RE/ColorByNumber/
├── base.apk, split_config.*.apk          # APK gốc đã pull
├── apktool_out/                          # apktool decode (manifest, res, assets, smali)
│   ├── AndroidManifest.xml
│   └── assets/<category>/<item>/         # tranh: fill, stock, thumb, level.txt
└── jadx_out/                             # jadx decompile (Java/Kotlin)
    └── sources/com/sycb/coloring/book/
        ├── activity/SYCB_ColoringActivity.java     # Activity tô màu
        ├── ColoringModel/
        │   ├── SYCB_KKView.java                    # custom View vẽ + tap
        │   ├── SYCB_FloodFill.java                 # thuật toán flood fill
        │   └── SYCB_FileHelper.java                # I/O ảnh + JSON
        ├── model/
        │   ├── SYCB_Level.java                     # 1 màu = 1 level
        │   └── SYCB_Coordinate.java                # 1 vùng tô
        └── database/
            └── NumberingDataManage.java            # tính trước points cho mỗi vùng
```

Mở GUI để xem trực tiếp:

```bash
jadx-gui /Users/macmini0051/Workspace/RE/ColorByNumber/base.apk
```
