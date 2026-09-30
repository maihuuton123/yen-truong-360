# TEST REPORT - YÊN TRƯỜNG 360 V1.0

Ngày kiểm thử: 2026-09-30

## Kết Quả Tổng Hợp

| Hạng mục | Kết quả | Ghi chú |
| --- | --- | --- |
| Backend unit/API tests | PASS | `78 tests OK` |
| E2E dữ liệu giả | PASS | Có test `test_citizen_report_to_resolved_admin_flow_statistics_and_export` |
| Migration database trống | PASS | Alembic upgrade thành công |
| Seed database | PASS | 6 categories, 4 areas, 1 admin |
| Frontend production build | PASS | Vite build thành công |
| Python dependency check | PASS | `pip check`: no broken requirements |
| JavaScript dependency audit | PASS | `npm audit --omit=dev`: 0 vulnerabilities |
| Python vulnerability audit | NOT RUN | `pip-audit` không có sẵn trong venv |

## E2E Scenario

| Bước | Kết quả |
| --- | --- |
| Mở health API | PASS |
| Lấy danh mục/khu vực active | PASS |
| Gửi phản ánh cây đổ gây cản trở giao thông | PASS |
| Upload ảnh test | PASS |
| Nhận tracking code | PASS |
| Tra cứu public lần 1 | PASS |
| Đăng nhập admin | PASS |
| Kiểm tra dashboard | PASS |
| Mở danh sách và chi tiết phản ánh | PASS |
| Tiếp nhận `NEW -> RECEIVED` | PASS |
| Chuyển phối hợp `RECEIVED -> COORDINATING` | PASS |
| Tra cứu public thấy trạng thái phối hợp | PASS |
| Xử lý `COORDINATING -> RESOLVED` | PASS |
| Tra cứu public thấy kết quả công khai | PASS |
| Kiểm tra `status_history` | PASS |
| Kiểm tra `audit_log` | PASS |
| Kiểm tra statistics | PASS |
| Xuất Excel | PASS |

## Security Review

### CRITICAL

Không còn vấn đề CRITICAL được phát hiện trong phạm vi kiểm tra local.

### HIGH

Đã xử lý:

- Excel formula injection: các text cell bắt đầu bằng `=`, `+`, `-`, `@` được prefix bằng `'` khi export.

Không còn vấn đề HIGH được phát hiện trong phạm vi kiểm tra local.

### MEDIUM

- Token revocation đang lưu in-memory; sau restart server, token đã logout trước đó không còn trong danh sách revoke. Rủi ro được giảm bằng token expiration. Có thể nâng cấp bằng bảng/session store nếu V1.1 cần kiểm soát phiên bền vững hơn.
- Rate limit hiện là fixed-window in-memory theo process. Đủ cho demo/single instance; nếu scale nhiều instance nên chuyển sang Redis hoặc storage tập trung.
- Một số HTTPException dùng constant `HTTP_422_UNPROCESSABLE_ENTITY` bị cảnh báo deprecation từ Starlette/FastAPI; không ảnh hưởng chức năng V1.0.

### LOW

- Frontend chưa có test tự động riêng; hiện kiểm qua production build và backend E2E/API tests.
- PWA không làm offline submission theo yêu cầu, service worker chỉ pass-through fetch.

## Các Mục Đã Kiểm

| Nhóm | Kết quả |
| --- | --- |
| Password hashing | PASS |
| Không lưu plain-text password | PASS |
| Token/session expiration | PASS |
| Logout | PASS |
| Role authorization backend | PASS |
| Role escalation | PASS |
| Tracking code format khó đoán | PASS |
| Chống lookup format sai | PASS |
| Public response không lộ internal note | PASS |
| Public response không lộ admin/user/audit data | PASS |
| Public submit/lookup rate limit | PASS |
| Upload MIME/extension/signature/size | PASS |
| Upload path traversal | PASS |
| Không public trực tiếp upload | PASS |
| Input validation | PASS |
| SQLAlchemy query binding | PASS |
| CORS qua environment | PASS |
| Không lộ stack trace trong test lỗi thông dụng | PASS |
| `.env` không commit | PASS |
| Audit log thao tác xử lý/danh mục/tài khoản | PASS |
| Transaction rollback khi audit lỗi | PASS |
| Migration có constraints/indexes chính | PASS |

## Lệnh Đã Chạy

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m pip check

$env:DATABASE_URL='sqlite:///./data/step12_empty_check.db'
$env:ADMIN_PASSWORD='Step12Admin!123'
$env:ADMIN_USERNAME='admin'
$env:AUTH_SECRET_KEY='step12-migration-secret'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.db.seed
.\.venv\Scripts\python.exe -m app.db.check_database

cd ..\frontend
$env:VITE_API_BASE_URL='https://yen-truong-360.onrender.com'
npm.cmd run build
npm.cmd audit --omit=dev --audit-level=high
```
