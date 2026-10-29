# 11. Bài tập

Bài tập chia ba phần: câu hỏi hiểu nghiệp vụ, truy vấn SQL trên dữ liệu generator, và câu hỏi thiết kế streaming. Lời giải nằm trong các khối thu gọn; hãy tự làm trước khi mở.

Phần B cần dữ liệu đã sinh (preset `XS` hoặc `S` là đủ) và **generator đã dừng**, để snapshot và journal không lệch nhau vì đang ghi dở.

## A. Hiểu nghiệp vụ

**A1.** Khách có 50.000.000đ khả dụng, gói phí 0,15%, đặt lệnh LO mua 1.900 cổ phiếu giá 26.300. Lệnh có được nhận không?

<details><summary>Lời giải</summary>

Cần `1.900 × 26.300 × 1,0015 = 50.044.955đ` > 50.000.000đ. Nếu là tiểu khoản thường, lệnh bị từ chối với `INSUFFICIENT_BUYING_POWER`. Nếu là tiểu khoản margin còn hạn mức, lệnh được nhận với `is_margin = TRUE`. Về bước giá: trên HOSE, vùng 10.000–49.950 có bước 50đ, và 26.300 = 526 × 50 nên giá hợp lệ. Đặt 26.320 thì không hợp lệ.
</details>

**A2.** Khách mua cổ phiếu khớp sáng thứ Sáu. Sáng thứ Hai tuần sau, khách bán được số cổ phiếu đó chưa?

<details><summary>Lời giải</summary>

Chưa. T = thứ Sáu, T+1 = thứ Hai, T+2 = thứ Ba (nếu không có lễ). Đến thứ Ba cổ phiếu mới chuyển từ `receiving_quantity` sang `available_quantity`.
</details>

**A3.** Vì sao không thể cộng dồn `ledger.cash_transactions.amount` để ra `cash_balances.available_amount`?

<details><summary>Lời giải</summary>

Nhật ký chỉ ghi khi tiền thực sự di chuyển (nạp, rút, thanh toán T+2, cổ tức, lãi…). Snapshot còn thay đổi khi tiền chỉ chuyển ngăn: đặt lệnh mua (khả dụng → phong toả), khớp (phong toả → chờ thanh toán). Quan hệ đúng là `balance_after cuối = available + blocked + payable`. Xem [bài 5](05-thanh-toan-tien-va-chung-khoan.md#56-đối-soát-snapshot-với-nhật-ký).
</details>

**A4.** Cổ phiếu `ZAB` có ngày GDKHQ là thứ Tư 18/06/2025. Khách A mua vào thứ Ba 17/06, khách B mua vào thứ Tư 18/06. Ai được nhận cổ tức (theo thực tế)?

<details><summary>Lời giải</summary>

Ngày chốt là thứ Năm 19/06. Khách A thanh toán vào T+2 = 19/06, có tên trong danh sách → **được nhận**. Khách B thanh toán vào 20/06, sau ngày chốt → **không** được nhận. (Generator đơn giản hoá chỗ này, xem [bài 7](07-quyen-co-dong.md#72-các-ngày-quan-trọng).)
</details>

**A5.** Tiểu khoản margin có 50 triệu tiền khả dụng, cổ phiếu trị giá 250 triệu, dư nợ 150 triệu. Gói `MR_STD`. Tỷ lệ ký quỹ bao nhiêu? Có bị call không? Nếu bị call, phải nộp bao nhiêu?

<details><summary>Lời giải</summary>

Tổng tài sản = 50 + 250 = 300 triệu. Tài sản ròng = 300 − 150 = 150 triệu. Tỷ lệ = 50% ≥ 40% → **không** bị call.

Nếu cổ phiếu giảm còn 180 triệu: tổng tài sản 230, tài sản ròng 80, tỷ lệ 34,8% → bị call. Phải nộp `(0,4 × 230 − 80) / 0,6 = 20 triệu`.
</details>

**A6.** Lệnh có `status = 'CANCELLED'` nhưng `filled_quantity = 1.200`. Chuyện gì đã xảy ra? Lệnh này có sinh `settlement_instructions` không?

<details><summary>Lời giải</summary>

Lệnh đã khớp một phần 1.200 rồi khách huỷ phần còn lại (hoặc là lệnh MAK bị huỷ phần dư). Phần đã khớp vẫn là giao dịch thật: có `executions` và có `settlement_instructions` tương ứng, thanh toán T+2 như bình thường.
</details>

## B. Truy vấn SQL

### B1. Danh mục sản phẩm (PostgreSQL)

Có bao nhiêu mã theo từng sàn và từng loại?

<details><summary>Lời giải</summary>

```sql
SELECT coalesce(exchange_code, '(không lên sàn)') AS san, instrument_type, count(*) AS so_ma
FROM product.instruments
GROUP BY 1, 2
ORDER BY 1, 2;
```

Chứng chỉ quỹ mở sẽ nằm ở dòng "(không lên sàn)".
</details>

### B2. Giá trần, sàn có nằm trong biên độ không? (PostgreSQL)

Tìm các dòng `eod_prices` của cổ phiếu có trần hoặc sàn vượt biên độ của sàn. Kỳ vọng: **0 dòng**.

<details><summary>Lời giải</summary>

```sql
SELECT i.symbol, p.trade_date, p.reference_price, p.ceiling_price, p.floor_price, e.price_band_pct
FROM product.eod_prices p
JOIN product.instruments i USING (instrument_id)
JOIN ref.exchanges e ON e.exchange_code = i.exchange_code
WHERE i.instrument_type = 'STOCK'
  AND (p.ceiling_price > p.reference_price * (1 + e.price_band_pct / 100)
    OR p.floor_price   < p.reference_price * (1 - e.price_band_pct / 100));
```

Thử bỏ điều kiện `instrument_type = 'STOCK'` và giải thích vì sao chứng quyền có thể xuất hiện.
</details>

### B3. Đi theo một khách hàng (PostgreSQL)

Chọn một khách đang hoạt động có tiểu khoản margin. Liệt kê các tiểu khoản, số dư tiền và danh mục cổ phiếu đang nắm giữ.

<details><summary>Lời giải</summary>

```sql
-- Tìm một khách có tiểu khoản margin
SELECT c.customer_id, c.customer_code
FROM customer.customers c
JOIN account.accounts a USING (customer_id)
WHERE c.status = 'ACTIVE' AND a.account_type = 'MARGIN'
LIMIT 5;

-- Số dư tiền
SELECT a.account_no, a.account_type, b.available_amount, b.blocked_amount,
       b.receivable_amount, b.payable_amount
FROM account.accounts a
JOIN ledger.cash_balances b USING (account_id)
WHERE a.customer_id = :customer_id;

-- Danh mục đang nắm giữ
SELECT a.account_no, i.symbol, p.total_quantity, p.available_quantity,
       p.receiving_quantity, p.blocked_quantity, p.average_cost
FROM account.accounts a
JOIN custody.positions p USING (account_id)
JOIN product.instruments i USING (instrument_id)
WHERE a.customer_id = :customer_id AND p.total_quantity > 0
ORDER BY a.account_no, i.symbol;
```

Thay `:customer_id` bằng id vừa tìm được. Tiếp tục lần theo khách này ở B9.
</details>

### B4. KYC tại một thời điểm (PostgreSQL)

Khẩu vị rủi ro của mỗi khách **tại ngày 01/05/2025** là gì? Có bao nhiêu khách đã đổi hồ sơ KYC ít nhất một lần?

<details><summary>Lời giải</summary>

```sql
SELECT k.customer_id, k.risk_appetite, k.risk_rating
FROM customer.kyc_profiles k
WHERE k.valid_from <= TIMESTAMPTZ '2025-05-01 00:00+07'
  AND (k.valid_to IS NULL OR k.valid_to > TIMESTAMPTZ '2025-05-01 00:00+07');

SELECT count(*) AS khach_doi_kyc
FROM (SELECT customer_id FROM customer.kyc_profiles GROUP BY customer_id HAVING count(*) > 1) t;
```
</details>

### B5. Ngày thanh toán có đúng T+2 không? (PostgreSQL)

Tìm các lệnh thanh toán có `settle_date` khác ngày giao dịch thứ hai sau `trade_date`. Kỳ vọng: **0 dòng**.

<details><summary>Lời giải</summary>

```sql
SELECT s.settlement_id, s.trade_date, s.settle_date
FROM custody.settlement_instructions s
WHERE s.settle_date <> (
  SELECT c.calendar_date
  FROM ref.trading_calendar c
  WHERE c.exchange_code = 'HOSE' AND c.is_trading_day AND c.calendar_date > s.trade_date
  ORDER BY c.calendar_date
  OFFSET 1 LIMIT 1
);
```

Mở rộng: đếm số giao dịch có khoảng cách `settle_date − trade_date` (theo ngày lịch) bằng 2, 4, 5… và giải thích vì sao có số 4 (cuối tuần) và lớn hơn (ngày lễ).
</details>

### B6. Đối soát tiền (PostgreSQL)

Kiểm tra quy tắc `balance_after cuối = available + blocked + payable` cho mọi tiểu khoản. Kỳ vọng: **0 dòng**.

<details><summary>Lời giải</summary>

```sql
WITH last_txn AS (
  SELECT DISTINCT ON (account_id) account_id, balance_after
  FROM ledger.cash_transactions
  ORDER BY account_id, cash_txn_id DESC
)
SELECT b.account_id, l.balance_after,
       b.available_amount + b.blocked_amount + b.payable_amount AS snapshot_total,
       b.receivable_amount
FROM ledger.cash_balances b
JOIN last_txn l USING (account_id)
WHERE l.balance_after <> b.available_amount + b.blocked_amount + b.payable_amount;
```

Nếu ra dòng, hãy kiểm tra xem generator đã dừng hẳn chưa. Nếu đã dừng mà vẫn lệch, đó là manh mối đáng điều tra: lần ngược `cash_transactions` của tiểu khoản đó.
</details>

### B7. Tỷ lệ ký quỹ hiện tại (PostgreSQL)

Tính tỷ lệ ký quỹ của mọi tiểu khoản đang có nợ margin, theo giá đóng cửa gần nhất. Tài khoản nào đang dưới 40%?

<details><summary>Lời giải</summary>

```sql
WITH px AS (
  SELECT DISTINCT ON (instrument_id) instrument_id, close_price
  FROM product.eod_prices
  WHERE close_price IS NOT NULL
  ORDER BY instrument_id, trade_date DESC
),
sec AS (
  SELECT p.account_id, sum(p.total_quantity * px.close_price) AS securities
  FROM custody.positions p
  JOIN px USING (instrument_id)
  GROUP BY p.account_id
),
debt AS (
  SELECT account_id, sum(outstanding_amount) AS debt
  FROM margin.loans
  WHERE status IN ('ACTIVE', 'OVERDUE')
  GROUP BY account_id
),
x AS (
  SELECT a.account_no, d.debt,
         b.available_amount + b.receivable_amount + coalesce(s.securities, 0) AS assets
  FROM debt d
  JOIN account.accounts a USING (account_id)
  JOIN ledger.cash_balances b USING (account_id)
  LEFT JOIN sec s USING (account_id)
)
SELECT account_no, assets, debt,
       round(100 * (assets - debt) / nullif(assets, 0), 2) AS margin_ratio_pct
FROM x
ORDER BY margin_ratio_pct;
```

So kết quả với `margin.margin_calls` của ngày gần nhất. Kết quả có thể lệch một chút vì generator còn tính khoản "giải ngân chờ" (mua margin đã khớp, chưa đến T+2) không lưu trong DB.
</details>

### B8. Giá tham chiếu ngày GDKHQ (PostgreSQL)

Với mỗi đợt cổ tức tiền mặt, so giá đóng cửa phiên trước ngày GDKHQ với giá tham chiếu ngày GDKHQ.

<details><summary>Lời giải</summary>

```sql
SELECT i.symbol, ev.ex_date, ev.cash_per_share,
       prev.close_price      AS dong_cua_phien_truoc,
       cur.reference_price   AS tham_chieu_ngay_gdkhq,
       prev.close_price - cur.reference_price AS chenh_lech
FROM corp_action.events ev
JOIN product.instruments i ON i.instrument_id = ev.instrument_id
JOIN product.eod_prices cur ON cur.instrument_id = ev.instrument_id AND cur.trade_date = ev.ex_date
CROSS JOIN LATERAL (
  SELECT p.close_price
  FROM product.eod_prices p
  WHERE p.instrument_id = ev.instrument_id AND p.trade_date < ev.ex_date
  ORDER BY p.trade_date DESC
  LIMIT 1
) prev
WHERE ev.ca_type = 'CASH_DIVIDEND'
ORDER BY ev.ex_date;
```

`chenh_lech` phải xấp xỉ `cash_per_share` (lệch một chút do làm tròn bước giá). Làm tương tự cho `STOCK_DIVIDEND`, kiểm tra `tham_chieu ≈ dong_cua × ratio_numerator / (ratio_numerator + ratio_denominator)`.
</details>

### B9. Dấu vết một lệnh qua hai DB

Chọn một lệnh khớp nhiều lần. In toàn bộ sự kiện của nó theo giờ Việt Nam, rồi tìm các lệnh thanh toán tương ứng bên PostgreSQL.

<details><summary>Lời giải</summary>

```sql
-- MySQL: lệnh khớp nhiều lần
SELECT order_id, COUNT(*) AS so_lan_khop
FROM oms.executions
GROUP BY order_id
HAVING COUNT(*) > 1
ORDER BY so_lan_khop DESC
LIMIT 5;

-- MySQL: lịch sử lệnh
SELECT event_time + INTERVAL 7 HOUR AS gio_vn, event_type, new_quantity, new_price, source, reason
FROM oms.order_events
WHERE order_id = :order_id
ORDER BY event_time, order_event_id;

-- MySQL: các lần khớp
SELECT execution_id, matched_at + INTERVAL 7 HOUR AS gio_vn, matched_quantity, matched_price, fee_amount, tax_amount
FROM oms.executions
WHERE order_id = :order_id;
```

```sql
-- PostgreSQL: thanh toán tương ứng (dán danh sách execution_id từ trên)
SELECT settlement_id, execution_id, side, gross_amount, fee_amount, tax_amount, net_amount,
       trade_date, settle_date, status, settled_at
FROM custody.settlement_instructions
WHERE execution_id IN (:execution_ids);

-- PostgreSQL: bút toán tiền sinh ra lúc thanh toán
SELECT txn_type, amount, balance_after, value_date
FROM ledger.cash_transactions
WHERE reference_type = 'SETTLEMENT' AND reference_id IN (:settlement_ids_as_text)
ORDER BY cash_txn_id;
```

Việc phải copy id bằng tay giữa hai DB chính là lý do cần lớp hợp nhất (Trino, lakehouse) hoặc join trên stream.
</details>

### B10. Nhịp chữ U (MySQL)

Đếm số lệnh theo từng khung 15 phút, giờ Việt Nam.

<details><summary>Lời giải</summary>

```sql
SELECT SEC_TO_TIME(FLOOR(TIME_TO_SEC(TIME(created_at + INTERVAL 7 HOUR)) / 900) * 900) AS khung_15_phut,
       COUNT(*) AS so_lenh
FROM oms.orders
GROUP BY khung_15_phut
ORDER BY khung_15_phut;
```

Thử bỏ `+ INTERVAL 7 HOUR` để thấy biểu đồ bị dịch sang 02:00–07:45, một lỗi rất hay gặp.
</details>

### B11. Trạng thái lệnh và khớp một phần (MySQL)

Với mỗi trạng thái lệnh, có bao nhiêu lệnh và bao nhiêu trong số đó đã khớp ít nhất một phần?

<details><summary>Lời giải</summary>

```sql
SELECT status, COUNT(*) AS so_lenh, SUM(filled_quantity > 0) AS co_khop
FROM oms.orders
GROUP BY status
ORDER BY so_lenh DESC;
```

Bạn sẽ thấy `CANCELLED` và `EXPIRED` có `co_khop > 0`. Đó là lý do không được đếm "lệnh có khớp" bằng `status = 'FILLED'`.
</details>

### B12. Lệnh bán giải chấp (MySQL)

Tìm các lệnh do hệ thống tự đặt. Chúng có đặc điểm gì chung?

<details><summary>Lời giải</summary>

```sql
SELECT o.order_id, o.account_id, o.symbol, o.side, o.order_type, o.price, o.quantity,
       o.status, o.channel, o.placed_by_employee_id, o.trade_date
FROM oms.orders o
JOIN oms.order_events e
  ON e.order_id = o.order_id AND e.event_type = 'SUBMITTED' AND e.source = 'SYSTEM'
ORDER BY o.trade_date, o.account_id;
```

Đặc điểm: lệnh bán, `LO`, kênh `BROKER`, đặt lúc 09:05, giá bằng giá sàn ngày hôm đó. Đối chiếu `account_id` với `margin.margin_calls` (`status = 'FORCE_SOLD'`) bên PostgreSQL.
</details>

## C. Thiết kế streaming

Các câu này không có đáp án duy nhất. Gợi ý chỉ là một hướng.

**C1. Phí môi giới theo chi nhánh, cập nhật mỗi phút.** Cần những topic CDC nào? Join thế nào khi `oms.executions` không có `branch_id`?

<details><summary>Gợi ý</summary>

Stream `oms.executions` (key `account_id`) join với bảng `account.accounts` (KTable, key `account_id`) để lấy `customer_id`, rồi join với `customer.customers` (KTable) để lấy `branch_id`. `ref.branches` gần như tĩnh, dùng GlobalKTable/broadcast. Tổng `fee_amount` theo `branch_id` trên tumbling window 1 phút. Câu hỏi thêm: chuyện gì xảy ra nếu event `executions` đến trước khi CDC của `accounts` tương ứng được nạp?
</details>

**C2. Phát hiện spoofing gần real-time.** Quy tắc: > 20 lệnh bị huỷ trong vòng 5 giây sau khi đặt, trong một ngày.

<details><summary>Gợi ý</summary>

Từ `oms.order_events`, key theo `order_id`, ghép `SUBMITTED` với `CANCELLED` trong window 5 giây (interval join). Phát ra một event "fast cancel" có `account_id` (lấy từ `oms.orders`). Đếm theo `account_id` trên window 1 ngày giao dịch, cảnh báo khi vượt 20. So kết quả với `compliance.aml_alerts` mà generator chạy theo lô lúc 23:00.
</details>

**C3. Cảnh báo tỷ lệ ký quỹ trong phiên.** Thay vì chờ 15:00, tính lại tỷ lệ ký quỹ mỗi khi giá đổi.

<details><summary>Gợi ý</summary>

Ba nguồn: `marketdata.ticks` (key `symbol`/`instrument_id`), CDC `custody.positions` (key `account_id, instrument_id`), CDC `margin.loans` và `ledger.cash_balances` (key `account_id`). Khó khăn chính: một tick của một mã ảnh hưởng tới **mọi** tài khoản nắm mã đó. Cần re-key positions theo `instrument_id` để join với tick, rồi re-key kết quả về `account_id` để cộng tổng tài sản. Cân nhắc giới hạn tần suất tính (mỗi N giây) thay vì mỗi tick.
</details>

**C4. Tái tạo `cash_balances` chỉ từ `cash_transactions`.** Có làm được không?

<details><summary>Gợi ý</summary>

Không đầy đủ. Nhật ký không ghi các lần chuyển ngăn (phong toả, chờ thanh toán, chờ về), nên chỉ tái tạo được tổng `available + blocked + payable`, không tách được từng ngăn. Muốn có đủ, dùng CDC của chính `cash_balances` (changelog → KTable), hoặc kết hợp thêm `oms.orders` và `oms.executions` để suy ra phần phong toả và chờ thanh toán.
</details>

---

← [10. Từ điển thuật ngữ](10-thuat-ngu.md) · [Về đầu](README.md)
