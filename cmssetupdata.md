# CMS Setup Data Specification

Tài liệu mô tả cấu trúc dữ liệu cần thiết cho hệ thống CMS quản lý nội dung Color by Number.

---

## 1. Category (Danh mục)

Mỗi Category đại diện cho một nhóm ảnh tô màu (ví dụ: Animals, Flowers, Food...).

### Màn hình CMS
- **Categories List** — Danh sách tất cả categories
- **Category Detail** — Chi tiết / chỉnh sửa 1 category

### Các trường dữ liệu

| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `id` | String | ID duy nhất của category |
| `name` | String | Tên hiển thị (ví dụ: "Animals") |
| `items` | List\<Item\> | Danh sách các item (ảnh tô màu) thuộc category này |

---

## 2. Item (Ảnh tô màu)

Mỗi Item là một bức tranh tô màu nằm trong một Category.

### Các trường dữ liệu

| Trường | Kiểu | Bắt buộc | Mô tả |
|--------|------|----------|-------|
| `id` | String | ✅ | ID duy nhất của item |
| `name` | String | ✅ | Tên hiển thị |
| `badge` | Enum | ✅ | Chọn **một trong hai**: `NEW` hoặc `HOT` |
| `type` | Enum | ✅ | Kiểu dữ liệu: `WITH_IMAGE` hoặc `WITHOUT_IMAGE` |
| `preview_image` | Image | ✅ | Ảnh preview chỉ chứa nét vẽ (outline) |
| `result_image` | Image | ✅ | Ảnh kết quả sau khi tô xong (hiển thị cho user xem trước) |
| `data_zip` | File | ✅ | File ZIP chứa dữ liệu path — xem cấu trúc bên dưới |

---

## 3. Cấu trúc file ZIP

### Type 1: `WITH_IMAGE` (có ảnh nền)

```
{key}_b.zip
├── {key}b              ← File data path (SVG paths, pipe-delimited)
├── {key}c              ← Ảnh PNG/JPEG nền (dùng làm background khi tô)
└── sp_new_paint_flag   ← Chứa dòng "111\r\n" (flag kiểm tra giải nén thành công)
```

### Type 2: `WITHOUT_IMAGE` (không có ảnh nền)

```
{key}_b.zip
├── {key}b              ← File data path (SVG paths, pipe-delimited)
└── sp_new_paint_flag   ← Chứa dòng "111\r\n" (flag kiểm tra giải nén thành công)
```

> **Lưu ý:** App tự động detect kiểu dữ liệu bằng cách kiểm tra file `{key}c` có tồn tại trong ZIP hay không.

---

## 4. Sample Data

| Kiểu | Link download |
|------|---------------|
| Có ảnh (`WITH_IMAGE`) | https://devtool.pwhs.app/transfer/67adcf9c-4ac5-48bc-86f2-9a87fe6fd95f |
| Không ảnh (`WITHOUT_IMAGE`) | https://devtool.pwhs.app/transfer/59b40a96-00de-47e9-ba2b-c40d3e6e11aa |