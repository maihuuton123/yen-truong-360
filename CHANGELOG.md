# CHANGELOG

## YÊN TRƯỜNG 360 V1.0 - 2026-09-30

### Hoàn Thành

- Public site cho người dân: gửi phản ánh, upload ảnh, nhận mã tra cứu, tra cứu kết quả.
- Backend quản lý danh mục/khu vực active từ API, không hard-code ở frontend.
- Admin authentication với password hashing, token expiration, logout.
- Authorization backend theo role `ADMIN`, `RECEIVER`, `HANDLER`.
- Dashboard quản trị, danh sách phản ánh, lọc/sắp xếp/phân trang từ backend.
- Chi tiết phản ánh và xử lý trạng thái có kiểm soát:
  - `NEW -> RECEIVED`
  - `RECEIVED -> COORDINATING`
  - `COORDINATING -> RESOLVED`
  - `NEW/RECEIVED/COORDINATING -> OUT_OF_SCOPE`
- Ghi `status_history` và `audit_log` trong transaction.
- Quản lý categories, areas và tài khoản cán bộ.
- Thống kê theo status/category/area/khoảng thời gian.
- Xuất Excel theo filter đang dùng.
- QR public site cho admin tải về.
- PWA manifest, icon placeholder và service worker không cache dữ liệu nhạy cảm.
- UI/UX hoàn thiện cho người dân mobile-first và admin desktop-first responsive.

### Security

- Kiểm tra upload: MIME, extension, chữ ký file, dung lượng, tên file random.
- Public lookup không trả `internal_note`, audit log, password, hash, token hoặc dữ liệu admin.
- Rate limit public submit và public lookup.
- Chống Excel formula injection khi export.
- `.env`, database, upload và thư mục build/cache được loại khỏi Git.

### Kiểm Thử

- Backend: `78 tests OK`.
- E2E dữ liệu giả: PASS.
- Migration database trống: PASS.
- Seed database: PASS.
- Frontend production build: PASS.
- `pip check`: PASS.
- `npm audit --omit=dev`: PASS, 0 vulnerabilities.

### Ghi Chú

- `pip-audit` chưa có sẵn trong venv nên chưa chạy được vulnerability audit chuyên sâu cho Python.
- Token revocation và rate limit đang in-memory, phù hợp demo/single instance. Nếu lên production dài hạn nên dùng storage tập trung.
