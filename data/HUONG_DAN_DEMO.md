# Bộ dữ liệu cửa hàng online giả lập — tháng 9/2026

Hai file Excel gồm **60 đơn hàng** và **66 dòng giao dịch**. Tất cả mã khách hàng, đơn hàng và giao dịch đều do chương trình tạo; không có dữ liệu cá nhân thật. Mỗi đơn có `Tổng tiền = Tiền hàng + Phí giao hàng − Giảm giá`.

Mở ứng dụng, chọn **Cửa hàng giả lập** để xem kết quả ngay. Bạn cũng có thể tải hai file này về rồi đưa lại vào mục **Tải file của bạn** để thử bước ghép cột và quy tắc trạng thái.

| Mã đơn | Tình huống | Kết quả mong đợi |
| --- | --- | --- |
| `DH2609046`, `DH2609059` | Thu tiền qua hai giao dịch; đơn 59 còn có giao dịch đang chờ | Khớp |
| `DH2609047` | Không có giao dịch | Thiếu thanh toán |
| `DH2609048` | Thu thiếu 90.000 ₫ | Thanh toán thiếu |
| `DH2609049` | Thu dư 60.000 ₫ | Thanh toán dư |
| `DH2609050` | Đơn hủy, thu rồi hoàn đủ | Khớp |
| `DH2609051` | Đơn hủy nhưng chưa hoàn tiền | Đơn đã hủy còn tiền |
| `DH2609052`, `DH2609053` | Chỉ có giao dịch đang chờ hoặc thất bại | Thiếu thanh toán |
| `DH2609054` | Một mã giao dịch xuất hiện hai dòng giống hệt nhau | Trùng mã giao dịch; chỉ tính tiền một lần |
| `DH2609055` | Đơn đang hiệu lực, hoàn một phần 80.000 ₫ | Thanh toán thiếu |
| `DH2609056` | Đơn hủy, mới hoàn một phần 100.000 ₫ | Đơn đã hủy còn tiền |
| `DH2609057` | Đơn hủy trước khi thu tiền | Khớp |
| `DH269999` | Có giao dịch nhưng không có đơn trong file đơn hàng | Thanh toán không có đơn |

Kết quả đối soát mong đợi: **51 đơn khớp**, **10 trường hợp cần xử lý** (trong đó có một khoản thanh toán không có đơn), **2 dòng cùng mã giao dịch**, tổng tiền lệch tuyệt đối **3.848.000 ₫**. Trường hợp trùng mã giao dịch vẫn cần kiểm tra dù số tiền chênh lệch bằng 0.
