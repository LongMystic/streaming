# 10. Từ điển thuật ngữ

Tra nhanh: tiếng Việt ↔ tiếng Anh ↔ nơi xuất hiện trong schema. Cột "Bài" trỏ tới bài giải thích chi tiết.

## Thị trường và sản phẩm

| Tiếng Việt | Tiếng Anh | Giải thích ngắn | Trong schema | Bài |
|---|---|---|---|---|
| Công ty chứng khoán (CTCK) | Securities company, broker | Thành viên sở giao dịch, nhận lệnh cho NĐT | (toàn bộ dataset) | [1](01-toan-canh.md) |
| Nhà đầu tư (NĐT) | Investor | Khách hàng của CTCK | `customer.customers` | [3](03-khach-hang-va-tai-khoan.md) |
| Sở giao dịch, sàn | Stock exchange | HOSE, HNX, UPCOM | `ref.exchanges` | [2](02-san-pham-va-thi-truong.md) |
| Mã chứng khoán | Ticker, symbol | Ví dụ `ZTC` | `product.instruments.symbol` | 2 |
| Cổ phiếu | Stock, share | | `instrument_type = 'STOCK'` | 2 |
| Chứng quyền có bảo đảm | Covered warrant (CW) | Quyền mua cổ phiếu cơ sở ở giá thực hiện | `product.warrant_details` | 2 |
| Cổ phiếu cơ sở | Underlying | Cổ phiếu mà chứng quyền tham chiếu | `warrant_details.underlying_instrument_id` | 2 |
| Giá thực hiện | Exercise price | | `warrant_details.exercise_price` | 2 |
| Tỷ lệ chuyển đổi | Conversion ratio | Số chứng quyền đổi 1 cổ phiếu | `warrant_details.conversion_ratio` | 2 |
| Trái phiếu | Bond | | `product.bond_details` | 2 |
| Lãi coupon | Coupon | Lãi trái phiếu trả định kỳ | `bond_details.coupon_rate_pct` | 2 |
| Ngày đáo hạn | Maturity date | | `maturity_date` | 2 |
| Chứng chỉ quỹ mở | Open-ended fund certificate | Mua bán theo NAV, không qua sàn | `instrument_type = 'FUND_CERTIFICATE'` | 2 |
| Quỹ ETF | Exchange-traded fund | Quỹ giao dịch trên sàn như cổ phiếu | `instrument_type = 'ETF'` | 2 |
| Giá trị tài sản ròng | Net asset value (NAV) | Giá một đơn vị quỹ | `product.fund_navs` | 2 |
| Tổ chức phát hành | Issuer | | `product.issuers` | 2 |
| Vốn điều lệ | Charter capital | | `issuers.charter_capital` | 2 |
| Báo cáo tài chính (BCTC) | Financial statements | | `product.financial_statements` | 2 |
| Mệnh giá | Par value | 10.000đ với cổ phiếu Việt Nam | | 7 |
| Room ngoại | Foreign ownership limit | Tỷ lệ sở hữu tối đa của NĐT nước ngoài | `instruments.foreign_ownership_limit_pct` | 2 |

## Giá và phiên

| Tiếng Việt | Tiếng Anh | Giải thích ngắn | Trong schema | Bài |
|---|---|---|---|---|
| Giá tham chiếu | Reference price | Thường là giá đóng cửa phiên trước | `eod_prices.reference_price` | 2 |
| Giá trần | Ceiling price | Giá cao nhất được phép trong ngày | `eod_prices.ceiling_price` | 2 |
| Giá sàn | Floor price | Giá thấp nhất được phép trong ngày | `eod_prices.floor_price` | 2 |
| Biên độ | Price band, daily limit | ±7% HOSE, ±10% HNX, ±15% UPCOM | `ref.exchanges.price_band_pct` | 2 |
| Bước giá | Tick size | Đơn vị thay đổi giá nhỏ nhất | | 2 |
| Lô chẵn | Board lot, round lot | 100 cổ phiếu | `lot_size` | 2 |
| Phiên ATO / ATC | Opening / closing auction | Khớp định kỳ mở cửa / đóng cửa | `order_type` | 2 |
| Khớp lệnh liên tục | Continuous matching | | | 2 |
| Giá trị giao dịch | Trading value | | `eod_prices.trading_value` | 2 |
| Khối ngoại mua / bán | Foreign buy / sell | | `eod_prices.foreign_buy_volume` | 2 |
| Ngày giao dịch | Trading day | | `ref.trading_calendar.is_trading_day` | 2 |

## Lệnh và khớp lệnh

| Tiếng Việt | Tiếng Anh | Giải thích ngắn | Trong schema | Bài |
|---|---|---|---|---|
| Lệnh | Order | | `oms.orders` | [4](04-vong-doi-lenh.md) |
| Lệnh giới hạn | Limit order (LO) | | `order_type = 'LO'` | 4 |
| Lệnh thị trường | Market order (MP, MTL, MOK, MAK) | | `order_type` | 2 |
| Khớp lệnh | Execution, fill, match | | `oms.executions` | 4 |
| Khớp một phần | Partial fill | | `status = 'PARTIALLY_FILLED'` | 4 |
| Huỷ lệnh / sửa lệnh | Cancel / modify | | `order_events.event_type` | 4 |
| Lệnh bị từ chối | Rejected order | | `orders.reject_reason` | 4 |
| Sức mua | Buying power | Tiền khả dụng + hạn mức vay còn lại | | 4, 6 |
| Kênh đặt lệnh | Channel | Web, mobile, môi giới, API | `orders.channel` | 4 |
| Danh mục theo dõi | Watchlist | | `oms.watchlists` | 4 |

## Tiền, chứng khoán, thanh toán

| Tiếng Việt | Tiếng Anh | Giải thích ngắn | Trong schema | Bài |
|---|---|---|---|---|
| Tiểu khoản | Sub-account | Mỗi khách có thể có tiểu khoản thường, margin… | `account.accounts` | 3 |
| Số lưu ký | Custody code | Mã định danh với VSDC, ví dụ `ZSCC001234` | `customers.custody_code` | 3 |
| Lưu ký | Custody | Giữ hộ chứng khoán | schema `custody` | [5](05-thanh-toan-tien-va-chung-khoan.md) |
| Thanh toán bù trừ | Clearing and settlement | | `custody.settlement_instructions` | 5 |
| T+2 | T+2 settlement | Thanh toán sau 2 ngày làm việc | `settle_date` | 5 |
| Tiền khả dụng | Available cash | | `cash_balances.available_amount` | 5 |
| Tiền phong toả | Blocked cash | | `cash_balances.blocked_amount` | 5 |
| Tiền chờ về | Receivable | Tiền bán chưa thanh toán | `cash_balances.receivable_amount` | 5 |
| Tiền chờ thanh toán | Payable | Tiền mua chưa thanh toán | `cash_balances.payable_amount` | 5 |
| Chứng khoán khả dụng | Available quantity | Bán được ngay | `positions.available_quantity` | 5 |
| Chứng khoán chờ về | Receiving quantity | Mua chưa thanh toán | `positions.receiving_quantity` | 5 |
| Cầm cố | Pledge | | `positions.pledged_quantity` | 5 |
| Giá vốn | Average cost | Giá mua bình quân, gồm phí | `positions.average_cost` | 5 |
| Phí môi giới | Brokerage fee | | `fee_schedules.trading_fee_pct`, `TRADING_FEE` | 2, 5 |
| Thuế bán | Selling tax | 0,1% giá trị bán | `SELLING_TAX` | 5 |
| Ứng trước tiền bán | Cash advance | Dùng trước tiền bán chưa về (không mô phỏng) | | 5 |
| Ngày hiệu lực | Value date | Ngày nghiệp vụ của bút toán tiền | `cash_transactions.value_date` | 5 |

## Margin

| Tiếng Việt | Tiếng Anh | Giải thích ngắn | Trong schema | Bài |
|---|---|---|---|---|
| Giao dịch ký quỹ | Margin trading | Vay CTCK để mua chứng khoán | schema `margin` | [6](06-margin.md) |
| Danh mục ký quỹ | Marginable list | Mã được cho vay | `margin.marginable_instruments` | 6 |
| Tỷ lệ cho vay | Loan ratio | | `marginable_instruments.loan_ratio_pct` | 6 |
| Dư nợ | Outstanding | | `loans.outstanding_amount` | 6 |
| Giải ngân | Disbursement | | `LOAN_DISBURSEMENT` | 6 |
| Tỷ lệ ký quỹ | Margin ratio | Tài sản ròng / Tổng tài sản | `margin_calls.margin_ratio_pct` | 6 |
| Tỷ lệ duy trì | Maintenance ratio | Dưới mức này bị call | `loan_products.maintenance_ratio_pct` | 6 |
| Tỷ lệ xử lý | Force-sell ratio | Dưới mức này bị bán giải chấp | `loan_products.force_sell_ratio_pct` | 6 |
| Gọi ký quỹ, call margin | Margin call | | `margin.margin_calls` | 6 |
| Bán giải chấp | Force sell | CTCK tự bán CK của khách để thu nợ | `margin_calls.status = 'FORCE_SOLD'` | 6 |

## Quyền cổ đông

| Tiếng Việt | Tiếng Anh | Giải thích ngắn | Trong schema | Bài |
|---|---|---|---|---|
| Sự kiện quyền | Corporate action | | `corp_action.events` | [7](07-quyen-co-dong.md) |
| Cổ tức tiền mặt | Cash dividend | | `ca_type = 'CASH_DIVIDEND'` | 7 |
| Cổ tức cổ phiếu | Stock dividend | | `ca_type = 'STOCK_DIVIDEND'` | 7 |
| Quyền mua | Rights issue | | `ca_type = 'RIGHTS_ISSUE'` | 7 |
| Ngày GDKHQ | Ex-date | Từ ngày này mua vào không được hưởng quyền | `events.ex_date` | 7 |
| Ngày đăng ký cuối cùng | Record date | Ngày chốt danh sách cổ đông | `events.record_date` | 7 |
| Ngày thanh toán | Payment date | | `events.payment_date` | 7 |
| Quyền được hưởng | Entitlement | | `corp_action.entitlements` | 7 |
| Thuế TNCN cổ tức | Dividend withholding tax | 5% | `entitlements.tax_withheld` | 7 |
| Công bố thông tin | Disclosure | | `content.disclosures` | 8 |

## Khách hàng, CSKH, tuân thủ

| Tiếng Việt | Tiếng Anh | Giải thích ngắn | Trong schema | Bài |
|---|---|---|---|---|
| Định danh khách hàng | KYC (Know Your Customer) | | `customer.kyc_profiles` | 3 |
| Định danh điện tử | eKYC | Mở tài khoản online | `onboarding_channel = 'EKYC_%'` | 3 |
| Căn cước công dân | Citizen ID (CCCD) | 12 số | `identity_documents` | 3 |
| Khẩu vị rủi ro | Risk appetite | Thận trọng / cân bằng / mạo hiểm | `kyc_profiles.risk_appetite` | 3 |
| Người có ảnh hưởng chính trị | PEP | | `kyc_profiles.is_pep` | 3 |
| Nhà đầu tư chuyên nghiệp | Professional investor | | `kyc_profiles.is_professional_investor` | 3 |
| Môi giới | Broker | | `employees.role = 'BROKER'` | 1 |
| Chuyên viên quản lý khách hàng | Relationship manager (RM) | | `customers.rm_employee_id` | 1, 3 |
| Khách hàng giàu có | High net worth (HNW) | | (phân khúc ẩn) | 3 |
| Mức độ hài lòng | CSAT | 1–5 | `support_tickets.csat_score` | 8 |
| Rời bỏ | Churn | | (nhãn suy ra) | 8 |
| Phòng chống rửa tiền | Anti-money laundering (AML) | | schema `compliance` | 8 |
| Chia nhỏ giao dịch | Structuring | | `rule_code = 'STRUCTURING'` | 8 |
| Giao dịch giả tạo | Wash trade | Mua bán qua lại để tạo thanh khoản giả | `rule_code = 'WASH_TRADE'` | 8 |
| Đặt lệnh ảo | Spoofing | Đặt rồi huỷ nhanh để tạo cung cầu giả | `rule_code = 'SPOOFING'` | 8 |
| Kết luận cảnh báo | Disposition | Đúng / nhầm / chưa rõ | `aml_alerts.disposition` | 8 |

## Thuật ngữ kỹ thuật dữ liệu

| Thuật ngữ | Giải thích | Ví dụ trong dataset |
|---|---|---|
| Snapshot | Bảng trạng thái hiện tại, bị update | `cash_balances`, `positions`, `orders` |
| Journal, append-only | Bảng nhật ký, chỉ insert | `cash_transactions`, `position_movements`, `order_events` |
| SCD type 2 | Lưu lịch sử bằng `valid_from` / `valid_to` | `kyc_profiles` |
| Supertype / subtype | Bảng chung + bảng chi tiết theo loại | `instruments` + `bond_details`… |
| Tham chiếu logic | Quan hệ không có khoá ngoại thật (khác DB) | `oms.orders.account_id` |
| Denormalize | Lưu trùng dữ liệu để đọc nhanh | `oms.orders.symbol` |
| Optimistic locking | Cột `version` tăng mỗi lần update | `orders.version`, `cash_balances.version` |
| PII | Dữ liệu cá nhân | cột có `[PII]` trong comment |
| Ground truth | Sự thật do generator biết, nằm ngoài DB | `ground_truth/*.parquet` |

---

← [9. Một ngày giao dịch](09-mot-ngay-giao-dich.md) · Tiếp theo: [11. Bài tập →](11-bai-tap.md)
