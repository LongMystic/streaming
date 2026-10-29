# fingen: generator dữ liệu công ty chứng khoán

`fingen` mô phỏng hoạt động của công ty chứng khoán theo thiết kế ở [../README.md](../README.md). Nó ghi thẳng vào Postgres (`appdb`) và MySQL (`oms`) của stack, đồng thời ghi ground truth ra file.

## Cài đặt (một lần)

Chạy từ thư mục `streaming/`:

```bash
bash dataset/scripts/init_db.sh                 # tạo schema + cấp quyền app/reader/cdc, chạy lại được
cd dataset/generator
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Linux/WSL: .venv/bin/python
```

Generator đọc thông tin kết nối từ `streaming/.env` và đăng nhập bằng user `app`. Muốn trỏ sang DB khác thì đặt các biến `GEN_PG_HOST/PORT/DB/USER/PASSWORD`, `GEN_MYSQL_*`, `GEN_KAFKA_BOOTSTRAP`.

## Chạy

```bash
.venv/Scripts/python -m fingen backfill --preset S     # dựng thế giới + mô phỏng lịch sử của preset
.venv/Scripts/python -m fingen live --speed 60         # chạy tiếp theo thời gian thực, nhanh gấp 60 lần, Ctrl+C để dừng
.venv/Scripts/python -m fingen reset                   # xoá sạch dữ liệu các bảng dataset
```

| Preset | Khách hàng | Giai đoạn | Lệnh | Thời gian backfill (đo trên máy này) |
|---|---|---|---|---|
| `XS` | 500 | 06/2025 | ~8,6 nghìn | ~12 giây |
| `S` | 5.000 | 04–06/2025 | ~250 nghìn | ~5 phút |
| `M`, `L` | 50k / 300k | 1–2 năm | hàng triệu | chưa đo, dự kiến hàng giờ |

**`backfill`:**
- Chỉ chạy khi các bảng còn trống.
- Ghi theo lô mỗi ngày mô phỏng, mỗi dòng chỉ ghi trạng thái cuối ngày của nó.
- Cuối cùng lưu state ra `output/state.pkl`.

**`live`:**
- Nạp `state.pkl` và chạy tiếp từ ngày giao dịch kế tiếp.
- Ghi **từng thay đổi** theo đúng thứ tự, nên CDC thấy được NEW → PARTIALLY_FILLED → FILLED, tiền chuyển từ phong toả sang chờ thanh toán…
- Tự bỏ qua các khoảng không có sự kiện (đêm, nghỉ trưa).
- Bắn `marketdata.ticks` và `app.clickstream` vào Kafka. Dùng `--no-kafka` để tắt, `--duration N` để tự dừng sau N giây.
- Chỉ chạy khi DB khớp đúng với state đã lưu. Nếu không khớp thì phải `reset` rồi `backfill` lại.

## CDC khi nạp dữ liệu

- **Postgres:** publication `FOR ALL TABLES` đã tự gồm các bảng mới. Connector đang chạy sẽ stream toàn bộ dữ liệu backfill, preset `S` khoảng 3 triệu dòng, nên sẽ có một đợt dữ liệu lớn.
- **MySQL:** connector hiện chỉ đọc `appdb`. Cần đổi `database.include.list` thành `appdb,oms` thì mới có CDC cho OMS.

## Kết quả

- **Database:** 42 bảng trong `appdb` (Postgres) và 6 bảng trong `oms` (MySQL).
- **`output/ground_truth/`:** những gì chỉ simulator biết, không nằm trong DB.
  - `customer_hidden_profile.parquet`: phân khúc thật, ngày churn, loại gian lận.
  - `injected_patterns.parquet`: các pattern AML/thao túng đã cài và đợt điều chỉnh thị trường.
  - `news_sentiment_truth.parquet`: sentiment và cú sốc giá thật của từng tin.
  - `disclosure_extraction_truth.parquet`: giá trị đúng của từng văn bản công bố thông tin.
  - `margin_call_context.parquet`.
  - `rag_qa.jsonl`: câu hỏi và đáp án cho knowledge base.

## Đã kiểm chứng (preset S, DB tạm)

- **Sổ cái tiền:** `balance_after` của mọi giao dịch bằng tổng luỹ kế, và số dư cuối khớp `available + blocked + payable`.
- **Tiền:** không có số dư âm, không còn tiền bị phong toả sau khi đóng phiên.
- **Vị thế:** bằng tổng nhật ký chứng khoán đã thanh toán cộng phần đang chờ T+2.
- **Lệnh:** khối lượng khớp của mọi lệnh bằng tổng các execution. Không có lệnh khớp ngoài giờ giao dịch.
- **Giá:** mọi giá cuối ngày nằm trong biên độ trần/sàn, OHLC hợp lệ.
- Có một số lần khớp "vượt giá giới hạn", nhưng đều là khớp xảy ra trước khi lệnh bị sửa giá.

## Đơn giản hoá cần biết

- **Khớp lệnh:** không có sổ lệnh. Lệnh được khớp dựa trên đường giá trong phiên do simulator sinh ra, khối lượng thị trường cũng được mô phỏng.
- **Khoản vay margin:** mỗi lần giải ngân (khi thanh toán lệnh mua margin) tạo một khoản vay riêng, nên số khoản vay rất nhiều.
- **Margin call:** chủ yếu phát sinh trong đợt điều chỉnh 3–5 phiên mà simulator cài sẵn. Ở preset `S`, số lượng khoảng vài chục.
- **Lịch nghỉ:** lịch nghỉ lễ năm 2026 là ước tính.
- **Kafka:** đường gửi tick và clickstream mới được chạy thử với broker không tồn tại, chưa chạy với Kafka thật.
