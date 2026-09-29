# Roadmap YEN TRUONG 360

## Bước 1: Nền tảng kỹ thuật

- Tạo cấu trúc `frontend/` và `backend/`.
- Backend FastAPI có module rõ ràng, config từ environment, CORS development.
- Endpoint `GET /api/health`.
- Frontend React/Vite có các route placeholder:
  - `/`
  - `/phan-anh`
  - `/tra-cuu`
  - `/admin/login`
  - `/admin/dashboard`
- Tài liệu khởi động dự án: `README.md`, `ROADMAP.md`, `.env.example`, `.gitignore`.

## Bước 2: Mô hình dữ liệu phản ánh

- Thiết kế bảng phản ánh, trạng thái, lịch sử xử lý.
- Tạo migration Alembic đầu tiên.
- Chưa thêm GPS, bản đồ, AI, chatbot hoặc app native.

## Bước 3: Luồng người dân

- Form gửi phản ánh không cần đăng nhập.
- Sinh mã tra cứu ngẫu nhiên.
- Trang tra cứu trạng thái bằng mã.

## Bước 4: Quản trị cán bộ

- Đăng nhập quản trị.
- Tiếp nhận, phân loại, chuyển/phối hợp.
- Cập nhật trạng thái và kết quả xử lý.

## Bước 5: Thống kê V1.0

- Dashboard tổng quan.
- Thống kê theo trạng thái, nhóm phản ánh, thời gian.
