# Ứng dụng đối soát đơn hàng và thanh toán

Ứng dụng Streamlit dành cho cửa hàng bán online: tải hai file CSV/XLSX, ghép cột và trạng thái của từng hệ thống, đối chiếu số tiền phải thu với giao dịch, rồi tải báo cáo Excel.

## Chạy ứng dụng

```powershell
cd D:\AI_App\doi-soat-don-hang
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

Mở `http://127.0.0.1:8501`. Chế độ **Cửa hàng giả lập** hiển thị kết quả của bộ file tháng 9/2026 và cho tải hai file Excel về. Chọn **Tải file của bạn** để dùng file riêng, hoặc **Lịch sử** để xem các lần đã lưu.

## Dữ liệu và quy tắc

Ứng dụng nhận file CSV/XLSX và cho chọn cột gốc tương ứng với:

| Đơn hàng | Thanh toán |
| --- | --- |
| Mã đơn (`order_id`) | Mã giao dịch (`transaction_id`) |
| Ngày đặt (`order_date`) | Mã đơn liên quan (`order_id`) |
| Số tiền phải thu (`expected_amount`) | Ngày giao dịch (`paid_at`) |
| Trạng thái đơn (`order_status`) | Số tiền giao dịch (`amount`) |
| Tên khách hàng tùy chọn (`customer_name`) | Trạng thái giao dịch (`payment_status`) |

Ứng dụng tự gợi ý cột và trạng thái thông dụng bằng tiếng Việt/Anh. Hãy kiểm tra gợi ý trước khi dùng kết quả. Với mỗi trạng thái đơn, chọn **đang hiệu lực** hoặc **đã hủy**. Với mỗi trạng thái giao dịch, chọn **hợp lệ (giữ dấu tiền)**, **hoàn tiền (đổi thành số âm)** hoặc **bỏ qua**. Trạng thái lạ phải được chọn thủ công để tránh tính nhầm.

Ngày: `YYYY-MM-DD` hoặc `DD/MM/YYYY`. Tiền: số VND nguyên, có thể dùng dấu phân cách hàng nghìn. Mã đơn cần duy nhất trong file đơn hàng. Một đơn có thể có nhiều giao dịch. Giao dịch hoàn tiền dạng số dương có thể được chuyển thành số âm qua quy tắc trạng thái.

Xem [đơn hàng mẫu](data/orders_sample.csv), [thanh toán mẫu](data/payments_sample.csv), hoặc bộ file có [cột tiếng Việt](data/orders_vietnamese_sample.csv) và [giao dịch hoàn tiền](data/payments_vietnamese_sample.csv).

Bộ thực hành lớn hơn gồm [60 đơn hàng giả lập](data/demo_orders_2026_09.xlsx), [66 giao dịch giả lập](data/demo_payments_2026_09.xlsx) và [hướng dẫn tình huống](data/HUONG_DAN_DEMO.md). Các mã khách hàng đều là mã giả. Bộ này giúp thử quy trình, chưa xác nhận quy tắc của hệ thống bán hàng thực tế của bạn.

## Cách tính

- Đơn đang hiệu lực phải thu số tiền đơn; đơn đã hủy phải thu 0.
- Chỉ cộng giao dịch được chọn là hợp lệ hoặc hoàn tiền. Một `transaction_id` lặp với cùng nội dung được tính một lần và đánh dấu để kiểm tra.
- Mã giao dịch lặp nhưng có mã đơn, số tiền hoặc trạng thái khác nhau làm dừng đối soát, vì không thể chọn một dòng một cách an toàn.
- Chênh lệch = đã thu ròng − phải thu. “Tổng tiền lệch tuyệt đối” cộng trị tuyệt đối của từng chênh lệch, kể cả thanh toán không có đơn.

## Lịch sử

Bấm **Lưu kết quả vào lịch sử** để lưu bảng kết quả, cấu hình ghép cột/trạng thái và báo cáo Excel vào `data/history.sqlite3` trên máy này. Ứng dụng không lưu file CSV/XLSX gốc. Lịch sử có thể xem lại và tải báo cáo cũ; hiện chưa có đăng nhập hoặc đồng bộ giữa nhiều máy.

## Kiểm tra

```powershell
python -m pytest -q
```
