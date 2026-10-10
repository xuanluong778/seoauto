Nâng cấp SEOAuto.vn để chịu tải cao và bảo mật hơn nhưng TUYỆT ĐỐI không làm thay đổi giao diện, UX, URL, API contract và output Content AI hiện tại.

Nguyên tắc:
- Không rewrite frontend.
- Không đổi Jinja2/JS hiện tại.
- Không đổi route hoặc tên endpoint nếu không bắt buộc.
- Không đổi response schema mà frontend đang dùng.
- Không thay prompt/content generation logic nếu không liên quan trực tiếp đến scale.
- Không refactor lớn cùng lúc.
- Mỗi wave phải backup → baseline → implement → test → load test → regression → mới sang wave tiếp.
- Dùng feature flag khi thay kiến trúc.
- Nếu regression thì rollback wave đó.