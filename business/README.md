# Nghiệp vụ công ty chứng khoán cho người mới

Folder này giải thích **nghiệp vụ** đằng sau bộ dữ liệu ở [../dataset/](../dataset/README.md). Mục tiêu là sau khi đọc xong, bạn trả lời được ba câu hỏi:

1. Mỗi bảng trong schema sinh ra từ hoạt động nào ngoài đời?
2. Các bảng liên quan với nhau thế nào, bảng nào là "trạng thái hiện tại", bảng nào là "nhật ký"?
3. Một sự kiện nghiệp vụ (đặt lệnh, khớp lệnh, chia cổ tức, bị call margin…) để lại dấu vết ở những bảng nào, theo thứ tự nào?

Câu hỏi thứ ba là nền tảng để thiết kế pipeline CDC → Kafka → stream processing, cũng như các bài toán ML/LLM trên bộ dữ liệu này.

**Không cần biết trước về chứng khoán.** Chỉ cần đọc được SQL.

## Lộ trình đọc

| # | Bài | Bạn sẽ hiểu | Schema chính |
|---|---|---|---|
| 1 | [Toàn cảnh](01-toan-canh.md) | CTCK làm gì, ai tham gia thị trường, vì sao dữ liệu chia 2 DB | tất cả |
| 2 | [Sản phẩm và thị trường](02-san-pham-va-thi-truong.md) | Cổ phiếu, ETF, chứng quyền, trái phiếu, quỹ; giá trần/sàn; phiên; loại lệnh | `ref`, `product` |
| 3 | [Khách hàng và tài khoản](03-khach-hang-va-tai-khoan.md) | Mở tài khoản, KYC, số lưu ký, tiểu khoản, phân khúc khách | `customer`, `account` |
| 4 | [Vòng đời lệnh](04-vong-doi-lenh.md) | Từ lúc bấm "Mua" đến khi khớp; trạng thái lệnh; sửa/huỷ/hết hạn | `oms.*` |
| 5 | [Thanh toán T+2, tiền và chứng khoán](05-thanh-toan-tien-va-chung-khoan.md) | Tiền phong toả, tiền chờ về, chứng khoán chờ về, đối soát | `ledger`, `custody` |
| 6 | [Giao dịch ký quỹ (margin)](06-margin.md) | Vay để mua, tỷ lệ ký quỹ, call margin, bán giải chấp | `margin` |
| 7 | [Quyền cổ đông](07-quyen-co-dong.md) | Cổ tức tiền/cổ phiếu, ngày GDKHQ, điều chỉnh giá | `corp_action` |
| 8 | [CSKH, tuân thủ và nội dung](08-cskh-tuan-thu-noi-dung.md) | Ticket hỗ trợ, phòng chống rửa tiền, tin tức, công bố thông tin | `crm`, `compliance`, `content` |
| 9 | [Một ngày giao dịch](09-mot-ngay-giao-dich.md) | Mọi thứ ở trên xảy ra lúc mấy giờ, bảng nào được ghi | tất cả |
| 10 | [Từ điển thuật ngữ](10-thuat-ngu.md) | Tra nhanh tiếng Việt ↔ tiếng Anh ↔ tên cột | — |
| 11 | [Bài tập](11-bai-tap.md) | Tự kiểm tra bằng SQL trên dữ liệu thật của generator | — |

Nếu chỉ có 30 phút: đọc bài 1, 4, 5 và 9. Đó là "xương sống" của hệ thống: lệnh → khớp → thanh toán.

## Cách học hiệu quả

- **Đọc kèm DDL.** Mở [postgres_core.sql](../dataset/ddl/postgres_core.sql) và [mysql_oms.sql](../dataset/ddl/mysql_oms.sql) song song. Mọi cột khó đều có `COMMENT`.
- **Chạy dữ liệu nhỏ.** Sinh dữ liệu preset `XS` (500 khách, 1 tháng) rồi `SELECT` theo các ví dụ trong từng bài. Nhìn dữ liệu thật dễ nhớ hơn đọc mô tả.
- **Đi theo một khách hàng.** Chọn một `customer_id`, lần theo lệnh → khớp → thanh toán → số dư của họ qua từng bảng. Bài tập ở [bài 11](11-bai-tap.md) có gợi ý.

## Quy ước trong các bài

- Tiền tính bằng **VND**, viết theo kiểu Việt Nam: `25.000` là hai mươi lăm nghìn.
- **T** là ngày khớp lệnh. **T+2** là ngày làm việc thứ hai sau T (bỏ qua cuối tuần và ngày lễ).
- Bảng PostgreSQL ghi dạng `schema.table` (ví dụ `ledger.cash_balances`). Bảng MySQL ghi dạng `oms.table`.
- Giờ trong bài là **giờ Việt Nam (UTC+7)**. Trong DB, timestamp lưu theo UTC. Xem lưu ý ở [bài 9](09-mot-ngay-giao-dich.md#95-lưu-ý-múi-giờ).
- Ô ghi chú **"Trong generator"** mô tả cách bộ sinh dữ liệu đơn giản hoá so với thực tế.

## Lưu ý

- Quy tắc nghiệp vụ ở đây dựa trên **thông lệ phổ biến của thị trường Việt Nam** và có thể khác quy định hiện hành. Đừng dùng tài liệu này làm căn cứ pháp lý hay đầu tư.
- Toàn bộ công ty, mã chứng khoán, khách hàng, tin tức là **hư cấu**. Mã chứng khoán bắt đầu bằng `Z` (`ZTC`, `ZAB`, `ZRE`…). Công ty chứng khoán giả lập có mã thành viên `ZSC`.
- Các con số trong ví dụ là minh hoạ để dễ tính nhẩm, không phải số trong dữ liệu sinh ra.
