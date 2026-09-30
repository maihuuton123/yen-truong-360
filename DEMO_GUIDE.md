# DEMO GUIDE - YÊN TRƯỜNG 360 V1.0

Kịch bản demo 5 phút dùng dữ liệu giả.

## Chuẩn Bị

- Backend đang chạy và `/api/health` trả `{"status":"ok","app":"Yen Truong 360"}`.
- Frontend đã trỏ `VITE_API_BASE_URL` về backend production hoặc backend local.
- Có tài khoản admin development từ biến môi trường `ADMIN_USERNAME` và `ADMIN_PASSWORD`.

## Kịch Bản

1. Mở trang chủ người dân.
2. Chọn **Gửi phản ánh**.
3. Chọn nhóm **Giao thông - vật cản**.
4. Chọn **Khu vực demo 1**.
5. Nhập mô tả: `Cây đổ chắn ngang đường, gây cản trở giao thông.`
6. Upload một ảnh test.
7. Bấm gửi và ghi lại mã tra cứu dạng `YT360-XXXXXX`.
8. Chọn **Tra cứu**, nhập mã vừa nhận.
9. Xác nhận màn hình tra cứu hiển thị trạng thái ban đầu.
10. Mở `/admin/login`.
11. Đăng nhập bằng tài khoản admin development.
12. Vào **Tổng quan**, kiểm tra số phản ánh mới tăng.
13. Vào **Phản ánh**, tìm mã tra cứu vừa tạo.
14. Mở chi tiết phản ánh.
15. Bấm **Tiếp nhận**, nhập ghi chú phù hợp.
16. Bấm **Chuyển / phối hợp**, nhập đầu mối, ghi chú nội bộ và nội dung công khai.
17. Quay lại trang tra cứu người dân, xác nhận trạng thái đã đổi sang **Đang phối hợp**.
18. Trên admin, nhập kết quả công khai và bấm **Đã xử lý**.
19. Quay lại trang tra cứu người dân, xác nhận trạng thái **Đã xử lý** và thấy kết quả công khai.
20. Vào **Thống kê**, xác nhận số liệu cập nhật.
21. Bấm **Xuất Excel**, mở file tải về và kiểm tra mã phản ánh có trong file.

## Điểm Cần Nói Khi Demo

- Người dân không cần đăng nhập.
- Mã tra cứu khó đoán và không liệt kê toàn bộ phản ánh public.
- Backend kiểm soát chuyển trạng thái, không cho nhảy trực tiếp `NEW -> RESOLVED`.
- Nội dung nội bộ và audit log không hiển thị ở trang người dân.
- Admin có phân quyền theo role.
- Danh mục và khu vực lấy từ API active, không hard-code ở frontend.
