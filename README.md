# YÊN TRƯỜNG 360

YÊN TRƯỜNG 360 là kênh phản ánh dân sinh phục vụ demo V1.0 cho xã Yên Trường. Người dân có thể gửi phản ánh, nhận mã tra cứu và theo dõi kết quả xử lý. Cán bộ đăng nhập khu vực quản trị để tiếp nhận, phối hợp, cập nhật trạng thái, xem thống kê và xuất Excel.

## Kiến trúc

- Backend: FastAPI, SQLAlchemy, Alembic.
- Database mặc định: SQLite, có thể đổi qua `DATABASE_URL`.
- Frontend: React + Vite, build ra HTML/CSS/JS tĩnh.
- Authentication: token HMAC có hạn dùng, password hash PBKDF2-SHA256.
- Authorization: backend kiểm tra role `ADMIN`, `RECEIVER`, `HANDLER`.
- Upload: lưu file ảnh trong `UPLOAD_DIR`, kiểm tra MIME, extension, chữ ký file và dung lượng.
- Public site: dùng `PUBLIC_SITE_URL` để tạo QR, không hard-code localhost trong production.

## Cài Đặt Backend Trên Windows

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Tạo biến môi trường hoặc file `.env` trong thư mục `backend`:

```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=MatKhauBanTuDat
AUTH_SECRET_KEY=doi-chuoi-bi-mat-dai-va-ngau-nhien
DATABASE_URL=sqlite:///./data/yen_truong_360.db
UPLOAD_DIR=./uploads/reports
PUBLIC_SITE_URL=https://thefour.top
CORS_ORIGINS=https://thefour.top,https://www.thefour.top,http://localhost:5173,http://127.0.0.1:5173
```

Không commit file `.env`. File `.gitignore` đã loại `.env`, database và thư mục upload.

## Migration Và Seed

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
python -m app.db.seed
python -m app.db.check_database
```

Seed tạo danh mục demo, khu vực demo và tài khoản admin development từ `ADMIN_USERNAME` / `ADMIN_PASSWORD`.

## Chạy Development

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```powershell
cd frontend
npm install
$env:VITE_DEV_API_TARGET="http://127.0.0.1:8000"
npm run dev
```

Mở:

- Người dân: `http://localhost:5173`
- Admin: `http://localhost:5173/admin/login`

## Build Production

```powershell
cd frontend
$env:VITE_API_BASE_URL="https://yen-truong-360.onrender.com"
npm run build
```

Upload nội dung trong `frontend/dist` lên hosting tĩnh.

Với Render backend, cấu hình:

- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `alembic upgrade head && python -m app.db.seed && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## API Chính

Public:

- `GET /api/health`
- `GET /api/public/categories`
- `GET /api/public/areas`
- `POST /api/public/reports`
- `GET /api/public/reports/{tracking_code}`

Auth:

- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/auth/logout`

Admin:

- `GET /api/admin/dashboard`
- `GET /api/admin/reports`
- `GET /api/admin/reports/{id}`
- `POST /api/admin/reports/{id}/receive`
- `POST /api/admin/reports/{id}/coordinate`
- `POST /api/admin/reports/{id}/resolve`
- `POST /api/admin/reports/{id}/out-of-scope`
- `GET /api/admin/statistics`
- `GET /api/admin/statistics/export`
- `GET /api/admin/categories`
- `POST /api/admin/categories`
- `PUT /api/admin/categories/{id}`
- `GET /api/admin/areas`
- `POST /api/admin/areas`
- `PUT /api/admin/areas/{id}`
- `GET /api/admin/users`
- `POST /api/admin/users`
- `PUT /api/admin/users/{id}`
- `POST /api/admin/users/{id}/password`
- `GET /api/admin/qr`
- `GET /api/admin/qr/download`

## Roles

- `ADMIN`: quản trị toàn bộ V1.0, gồm danh mục, khu vực, tài khoản, QR, thống kê và xử lý phản ánh.
- `RECEIVER`: xem, tiếp nhận, phân loại, chuyển/phối hợp phản ánh.
- `HANDLER`: xem và cập nhật phản ánh trong phạm vi được phép, đặc biệt bước hoàn thành xử lý.

Backend kiểm tra role ở từng endpoint. Frontend chỉ hỗ trợ trải nghiệm người dùng, không được xem là lớp bảo mật chính.

## Lưu Ý Bảo Mật

- Luôn đổi `ADMIN_PASSWORD` và `AUTH_SECRET_KEY` khi triển khai production.
- Không đưa secret vào biến `VITE_*`; mọi biến `VITE_*` đều là public trong bundle frontend.
- Không commit `.env`, database, thư mục upload hoặc dữ liệu người dân thật.
- Public lookup chỉ trả dữ liệu công khai, không trả `internal_note`, audit log, user, password hash hoặc token.
- Upload chỉ chấp nhận ảnh hợp lệ theo MIME, extension, chữ ký file và giới hạn dung lượng.
- Với production dài hạn, nên dùng PostgreSQL/persistent database và persistent upload storage/object storage.
- Cần có quy trình backup/restore trước khi pilot/production thật.

## Backup

SQLite development:

```powershell
Copy-Item backend\data\yen_truong_360.db backend\data\backup-yen-truong-360.db
```

Production cần backup database theo nền tảng triển khai. Không copy trực tiếp thư mục upload hoặc database vào GitHub nếu có dữ liệu người dân thật.

Restore SQLite development:

```powershell
Copy-Item backend\data\backup-yen-truong-360.db backend\data\yen_truong_360.db
```

Với PostgreSQL production, dùng backup của nhà cung cấp hoặc `pg_dump`/`pg_restore` theo chính hạ tầng triển khai.

## Deployment Checklist

- [ ] Production secret riêng, không dùng giá trị mẫu.
- [ ] `DEBUG`/reload không bật trong production.
- [ ] HTTPS cho frontend và backend.
- [ ] CORS đúng domain production.
- [ ] PostgreSQL hoặc database persistent.
- [ ] Upload storage persistent hoặc object storage.
- [ ] Migration chạy thành công.
- [ ] Admin production được tạo bằng mật khẩu riêng.
- [ ] Backup/restore được xác nhận.
- [ ] Logging đủ chẩn đoán, không log password/token/secret.
- [ ] Rate limit bật cho public endpoints.
- [ ] Frontend API URL đúng backend production.
- [ ] Frontend production build mới.
- [ ] Smoke test sau deployment.
- [ ] QR trỏ đúng public site.
- [ ] Không có demo/test data gây hiểu nhầm.
- [ ] Không có secret trong Git hoặc gói upload.

## Kiểm Thử

Backend:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests
```

Frontend build:

```powershell
cd frontend
$env:VITE_API_BASE_URL="https://yen-truong-360.onrender.com"
npm run build
```

Dependency:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip check

cd ..\frontend
npm audit --omit=dev --audit-level=high
```
