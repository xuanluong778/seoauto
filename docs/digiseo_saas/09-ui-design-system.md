# UI Design System Roadmap

Tài liệu này mô tả cách chuẩn hóa UI/UX cho Seoauto để nhìn chuyên nghiệp như SaaS thật.

---

## 1. Hiện trạng

Frontend hiện tại:

```txt
Jinja2 SSR
HTML/CSS/JS
TinyMCE
Tailwind CDN ở một số UI
CSS riêng
Dark mode
Accent xanh #00e676
```

Không cần chuyển sang React/Next.js ngay, nhưng cần chuẩn hóa UI.

---

## 2. Cần hạn chế

```txt
CSS inline quá nhiều
Mỗi trang một kiểu button
Mỗi trang một kiểu table
Loading/error không thống nhất
Modal không thống nhất
Form style không thống nhất
```

---

## 3. Thư mục component nên tạo

```txt
templates/components/
```

Gồm:

```txt
button.html
card.html
modal.html
table.html
input.html
badge.html
toast.html
sidebar.html
empty_state.html
loading.html
pagination.html
```

---

## 4. Tài liệu cần có

```txt
docs/UI_DESIGN_SYSTEM.md
```

Nội dung:

```txt
Màu chính
Màu phụ
Font
Spacing
Button style
Card style
Table style
Form style
Badge status
Toast message
Dark mode
Mobile responsive
```

---

## 5. Nguyên tắc migration UI

```txt
Không sửa toàn bộ UI một lần
Chọn 1 trang ít rủi ro để áp dụng thử
Không xóa style cũ nếu chưa migration xong
Không làm hỏng JS hiện tại
Tạo component dùng lại dần
```

---

## 6. Empty / Loading / Error state

Mỗi module nên có:

### Empty state

```txt
Bạn chưa có bài viết nào.
[ Tạo bài viết đầu tiên ]
```

### Loading state

```txt
Đang phân tích website...
Quá trình này có thể mất 30–90 giây tùy số lượng URL.
```

### Error state

```txt
Không thể kết nối WordPress.
Vui lòng kiểm tra:
- URL website
- Username
- Application Password
- REST API có bật không
```

### Success state

```txt
Đã đăng bài thành công lên WordPress.
[ Xem bài viết ] [ Tạo bài mới ]
```
