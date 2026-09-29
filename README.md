# YEN TRUONG 360

Nền tảng số hỗ trợ tiếp nhận, phân loại, theo dõi phản ánh dân sinh và phối hợp xử lý trên địa bàn xã Yên Trường.

Thông điệp: **Quét nhanh - Phản ánh dễ - Theo dõi rõ - Phối hợp hiệu quả.**

## Phạm vi V1.0

- Người dân truy cập Web App qua QR, gửi phản ánh không cần đăng nhập.
- Người dân nhận mã tra cứu ngẫu nhiên để theo dõi trạng thái.
- Cán bộ có hệ thống quản trị riêng để tiếp nhận, phân loại, chuyển/phối hợp, cập nhật trạng thái, cập nhật kết quả và thống kê.

Giai đoạn hiện tại chỉ dựng nền tảng kỹ thuật, chưa xây business logic.

## Công nghệ

- Frontend: React, Vite, React Router, responsive/mobile-first.
- Backend: Python, FastAPI, SQLAlchemy, Alembic, Pydantic.
- Database development: SQLite, thiết kế để có thể chuyển sang PostgreSQL sau này.

## Cấu trúc

```text
project/
  frontend/
  backend/
  README.md
  ROADMAP.md
  .env.example
  .gitignore
```

## Chạy backend trên Windows

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item ..\.env.example .env
python -m uvicorn app.main:app --reload
```

Kiểm tra:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

Kết quả mong đợi:

```json
{
  "status": "ok",
  "app": "Yen Truong 360"
}
```

## Database development

Tạo file môi trường cho backend:

```powershell
cd backend
Copy-Item ..\.env.example .env
```

Mở `backend\.env` và đặt mật khẩu admin development:

```text
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="mat-khau-dev-cua-ban"
```

Chạy migration:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m alembic upgrade head
```

Seed dữ liệu ban đầu:

```powershell
python -m app.db.seed
```

Kiểm tra database:

```powershell
python -m app.db.check_database
```

Chạy test backend liên quan:

```powershell
python -m unittest discover -s tests
```

## Chạy frontend trên Windows

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Build:

```powershell
npm.cmd run build
```

## Deploy frontend lên thefour.top

```powershell
cd frontend
npm.cmd install
npm.cmd run build
```

Upload toàn bộ nội dung trong thư mục `frontend/dist/` vào web root của domain `thefour.top`, thường là `public_html/` hoặc thư mục document root mà hosting cấp.

Sau khi upload, `public_html/` cần có:

```text
index.html
index.php
.htaccess
deploy-check.txt
assets/
```

Nếu domain vẫn báo `403 Forbidden`, nguyên nhân nằm ở hosting/domain:

- Chưa upload file trong `frontend/dist/` vào đúng document root.
- Thiếu `index.html` ở web root.
- Hosting chỉ ưu tiên PHP index; bản deploy đã có thêm `index.php` để xử lý trường hợp này.
- Quyền file/thư mục trên hosting đang bị chặn.
- Domain `thefour.top` chưa trỏ đúng hosting.

Sau khi upload, thử mở:

```text
http://thefour.top/deploy-check.txt
```

Nếu đường dẫn này vẫn lỗi 403, file chưa nằm đúng web root hoặc hosting đang chặn quyền truy cập.
