"""Vietnamese text templates. Every text is generated from structured values so models can be scored."""
from __future__ import annotations

import random
from datetime import date


def vnd(amount: float) -> str:
    return f"{amount:,.0f}".replace(",", ".") + " đồng"


def billions(amount: float) -> str:
    return f"{amount / 1e9:,.1f}".replace(",", "#").replace(".", ",").replace("#", ".") + " tỷ đồng"


def pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",") + "%"


def dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ---------------------------------------------------------------- news

_POSITIVE = [
    ("{name} ({symbol}) ký hợp đồng lớn, kỳ vọng tăng trưởng doanh thu",
     "{name} vừa công bố ký kết hợp đồng trị giá khoảng {deal} với đối tác trong nước. Ban lãnh đạo cho biết "
     "hợp đồng sẽ đóng góp đáng kể vào doanh thu từ quý tới. Giới phân tích đánh giá đây là tín hiệu tích cực "
     "đối với triển vọng kinh doanh của {symbol}."),
    ("{symbol}: lợi nhuận vượt kỳ vọng, nhà đầu tư kỳ vọng mùa cổ tức",
     "Theo số liệu sơ bộ, {name} ghi nhận lợi nhuận tăng mạnh so với cùng kỳ nhờ biên lợi nhuận gộp cải thiện. "
     "Một số công ty chứng khoán đã nâng giá mục tiêu đối với {symbol} sau thông tin này."),
    ("{name} được chấp thuận mở rộng dự án trọng điểm",
     "{name} ({symbol}) cho biết đã nhận được chấp thuận để triển khai giai đoạn mở rộng dự án với tổng vốn đầu tư "
     "khoảng {deal}. Doanh nghiệp kỳ vọng dự án đi vào hoạt động trong vòng 18 tháng tới."),
]
_NEGATIVE = [
    ("{symbol} bị điều chỉnh giảm kế hoạch lợi nhuận",
     "{name} vừa thông qua việc điều chỉnh giảm kế hoạch lợi nhuận năm do chi phí đầu vào tăng và nhu cầu thị trường "
     "suy yếu. Nhiều nhà đầu tư lo ngại kết quả kinh doanh các quý tới của {symbol} sẽ kém khả quan."),
    ("{name} chậm công bố báo cáo tài chính, cổ phiếu chịu áp lực",
     "{name} ({symbol}) thông báo lùi thời hạn công bố báo cáo tài chính do cần thêm thời gian làm việc với đơn vị "
     "kiểm toán. Thông tin này khiến tâm lý nhà đầu tư thận trọng hơn với {symbol}."),
    ("Lãnh đạo {name} đăng ký bán ra lượng lớn cổ phiếu",
     "Một thành viên hội đồng quản trị của {name} vừa đăng ký bán khoảng {shares} cổ phiếu {symbol} với mục đích "
     "cơ cấu tài chính cá nhân. Giao dịch dự kiến thực hiện trong vòng 30 ngày."),
]
_NEUTRAL = [
    ("{name} tổ chức gặp gỡ nhà đầu tư định kỳ",
     "{name} ({symbol}) vừa tổ chức buổi gặp gỡ nhà đầu tư để cập nhật tình hình kinh doanh. Ban lãnh đạo giữ nguyên "
     "kế hoạch kinh doanh đã đề ra và chưa có thông tin mới về chính sách cổ tức."),
    ("{symbol} thay đổi nhân sự cấp cao",
     "{name} thông báo bổ nhiệm phó tổng giám đốc phụ trách tài chính mới. Doanh nghiệp cho biết việc thay đổi nhằm "
     "kiện toàn bộ máy quản lý và không ảnh hưởng đến hoạt động sản xuất kinh doanh."),
]


def news_article(rng: random.Random, name: str, symbol: str, sentiment: str) -> tuple[str, str]:
    pool = {"POSITIVE": _POSITIVE, "NEGATIVE": _NEGATIVE, "NEUTRAL": _NEUTRAL}[sentiment]
    title, body = rng.choice(pool)
    values = {"name": name, "symbol": symbol,
              "deal": billions(rng.randint(80, 3000) * 1e9), "shares": f"{rng.randint(5, 200) * 100_000:,}".replace(",", ".")}
    return title.format(**values), body.format(**values)


def market_wrap(d: date, market_return: float, gainers: list[str], losers: list[str], value: float) -> tuple[str, str]:
    direction = "tăng" if market_return > 0.002 else "giảm" if market_return < -0.002 else "đi ngang"
    title = f"Thị trường phiên {dmy(d)}: chỉ số {direction} {pct(abs(market_return) * 100, 2)}"
    body = (f"Kết thúc phiên giao dịch ngày {dmy(d)}, thị trường {direction} {pct(abs(market_return) * 100, 2)} "
            f"với tổng giá trị giao dịch khoảng {billions(value)}. ")
    if gainers:
        body += f"Các mã tăng nổi bật gồm {', '.join(gainers)}. "
    if losers:
        body += f"Chiều ngược lại, {', '.join(losers)} chịu áp lực bán mạnh. "
    body += "Dòng tiền tiếp tục phân hóa giữa các nhóm ngành."
    return title, body


# ---------------------------------------------------------------- disclosures

def dividend_disclosure(name: str, symbol: str, ca_type: str, ex_date: date, record_date: date,
                        payment_date: date | None, cash_per_share: float | None,
                        ratio: tuple[int, int] | None) -> tuple[str, str]:
    if ca_type == "CASH_DIVIDEND":
        rate = cash_per_share / 10_000 * 100
        title = f"{symbol}: Thông báo ngày đăng ký cuối cùng trả cổ tức bằng tiền"
        body = (f"{name} thông báo ngày đăng ký cuối cùng để thực hiện quyền nhận cổ tức bằng tiền mặt. "
                f"Ngày giao dịch không hưởng quyền: {dmy(ex_date)}. Ngày đăng ký cuối cùng: {dmy(record_date)}. "
                f"Tỷ lệ thực hiện: {pct(rate, 0)}/cổ phiếu (01 cổ phiếu được nhận {vnd(cash_per_share)}). "
                f"Thời gian thanh toán: {dmy(payment_date)}.")
    else:
        old, new = ratio
        title = f"{symbol}: Thông báo phát hành cổ phiếu để trả cổ tức"
        body = (f"{name} thông báo phát hành cổ phiếu để trả cổ tức theo tỷ lệ {old}:{new} "
                f"(cổ đông sở hữu {old} cổ phiếu được nhận {new} cổ phiếu mới). "
                f"Ngày giao dịch không hưởng quyền: {dmy(ex_date)}. Ngày đăng ký cuối cùng: {dmy(record_date)}. "
                f"Cổ phiếu lẻ phát sinh (nếu có) sẽ bị hủy.")
    return title, body


def financial_statement_disclosure(name: str, symbol: str, year: int, quarter: int, revenue: float,
                                   net_income: float, audited: bool) -> tuple[str, str]:
    period = f"năm {year}" if quarter == 0 else f"quý {quarter}/{year}"
    kind = "đã kiểm toán" if audited else "chưa kiểm toán"
    title = f"{symbol}: Báo cáo tài chính {period}"
    result = "lãi" if net_income >= 0 else "lỗ"
    body = (f"{name} công bố báo cáo tài chính {period} ({kind}). Doanh thu thuần đạt {billions(revenue)}, "
            f"lợi nhuận sau thuế {result} {billions(abs(net_income))}.")
    return title, body


def misc_disclosure(rng: random.Random, name: str, symbol: str) -> tuple[str, str, str]:
    options = [
        ("BOARD_RESOLUTION", f"{symbol}: Nghị quyết Hội đồng quản trị",
         f"Hội đồng quản trị {name} thông qua việc vay vốn ngân hàng để bổ sung vốn lưu động phục vụ sản xuất kinh doanh."),
        ("PERSONNEL_CHANGE", f"{symbol}: Thay đổi nhân sự",
         f"{name} thông báo miễn nhiệm và bổ nhiệm thành viên Ban kiểm soát theo nghị quyết đại hội đồng cổ đông."),
        ("INSIDER_TRADING", f"{symbol}: Báo cáo kết quả giao dịch cổ phiếu của người nội bộ",
         f"Người nội bộ của {name} báo cáo đã hoàn tất giao dịch {rng.randint(1, 50) * 10_000:,} cổ phiếu {symbol}."
         .replace(",", ".")),
    ]
    return rng.choice(options)


# ---------------------------------------------------------------- research

def research_report(name: str, symbol: str, recommendation: str, target_price: int, close: int) -> tuple[str, str]:
    labels = {"BUY": "MUA", "OUTPERFORM": "KHẢ QUAN", "HOLD": "NẮM GIỮ", "UNDERPERFORM": "KÉM KHẢ QUAN", "SELL": "BÁN"}
    upside = (target_price / close - 1) * 100
    title = f"{symbol} - Khuyến nghị {labels[recommendation]}, giá mục tiêu {vnd(target_price)}"
    body = (f"Chúng tôi khuyến nghị {labels[recommendation]} đối với cổ phiếu {symbol} của {name} với giá mục tiêu "
            f"{vnd(target_price)}, tương ứng mức {'tăng' if upside >= 0 else 'giảm'} {pct(abs(upside))} so với giá "
            f"đóng cửa {vnd(close)}. Định giá dựa trên phương pháp chiết khấu dòng tiền và so sánh P/E với các "
            f"doanh nghiệp cùng ngành. Rủi ro chính gồm biến động lãi suất, giá nguyên vật liệu và tiến độ dự án.")
    return title, body


# ---------------------------------------------------------------- CRM

_TICKETS = {
    "ACCOUNT_OPENING": ("Hỏi về mở tài khoản", [
        "Tôi đã đăng ký mở tài khoản qua ứng dụng từ hôm qua nhưng chưa nhận được thông báo kích hoạt.",
        "Cho tôi hỏi mở thêm tiểu khoản ký quỹ thì cần những giấy tờ gì?"]),
    "LOGIN_OTP": ("Không nhận được mã OTP", [
        "Tôi không nhận được mã OTP khi đăng nhập, đã thử nhiều lần vẫn không được.",
        "Tài khoản của tôi bị khóa sau khi nhập sai mật khẩu, nhờ hỗ trợ mở khóa."]),
    "DEPOSIT_WITHDRAWAL": ("Nạp rút tiền", [
        "Tôi đã chuyển tiền vào tài khoản chứng khoán từ sáng nhưng số dư chưa được cập nhật.",
        "Lệnh rút tiền của tôi đã quá 1 ngày mà ngân hàng vẫn chưa nhận được tiền."]),
    "ORDER_ISSUE": ("Vấn đề khi đặt lệnh", [
        "Tôi đặt lệnh mua nhưng hệ thống báo không đủ sức mua dù tài khoản còn tiền.",
        "Lệnh bán của tôi đã khớp nhưng tiền chưa về tài khoản, cho tôi hỏi bao giờ tiền về?"]),
    "MARGIN": ("Hỏi về ký quỹ", [
        "Tôi nhận được tin nhắn yêu cầu bổ sung ký quỹ, cho tôi hỏi cần nộp thêm bao nhiêu và hạn cuối là khi nào?",
        "Lãi suất margin hiện tại là bao nhiêu và tính lãi như thế nào?"]),
    "CORPORATE_ACTION": ("Cổ tức và quyền", [
        "Tôi sở hữu cổ phiếu trước ngày đăng ký cuối cùng nhưng chưa nhận được cổ tức.",
        "Cổ phiếu thưởng của tôi bao giờ thì được giao dịch?"]),
    "FEES": ("Thắc mắc về phí", [
        "Phí giao dịch của tôi bị tính cao hơn mức đã đăng ký, nhờ kiểm tra lại.",
        "Cho tôi hỏi cách chuyển sang gói phí VIP."]),
    "APP_BUG": ("Lỗi ứng dụng", [
        "Ứng dụng bị treo khi tôi mở màn hình danh mục đầu tư.",
        "Bảng giá trên ứng dụng không cập nhật, phải thoát ra vào lại mới thấy giá mới."]),
    "COMPLAINT": ("Khiếu nại dịch vụ", [
        "Tôi rất không hài lòng vì hệ thống chậm đúng lúc thị trường biến động, lệnh của tôi không kịp khớp.",
        "Tôi muốn khiếu nại vì bị bán giải chấp mà không được thông báo đầy đủ.",
        "Phí và lãi margin quá cao, tôi đang cân nhắc chuyển sang công ty khác."]),
    "OTHER": ("Câu hỏi khác", [
        "Cho tôi hỏi giờ giao dịch của sàn HNX khác HOSE như thế nào?",
        "Tôi muốn cập nhật số điện thoại liên hệ."]),
}
_AGENT_REPLIES = [
    "Chào anh/chị, bộ phận hỗ trợ đã tiếp nhận yêu cầu và đang kiểm tra.",
    "Dạ, em đã kiểm tra và chuyển yêu cầu sang bộ phận nghiệp vụ, anh/chị vui lòng chờ trong ngày làm việc.",
    "Yêu cầu của anh/chị đã được xử lý xong. Anh/chị vui lòng kiểm tra lại giúp em.",
    "Em xin lỗi vì sự bất tiện, bên em sẽ phản hồi chi tiết qua email đã đăng ký.",
]


def ticket(rng: random.Random, category: str, account_no: str | None) -> tuple[str, list[tuple[str, str]]]:
    subject, openings = _TICKETS[category]
    opening = rng.choice(openings)
    if account_no and rng.random() < 0.4:
        opening += f" Số tài khoản của tôi là {account_no}."
    messages = [("CUSTOMER", opening)]
    for _ in range(rng.randint(1, 4)):
        messages.append(("AGENT", rng.choice(_AGENT_REPLIES)))
        if rng.random() < 0.4:
            messages.append(("CUSTOMER", rng.choice(["Cảm ơn bạn.", "Mình vẫn chưa thấy thay đổi.", "Ok, mình chờ."])))
    return subject, messages


def rm_note(rng: random.Random, note_type: str, holdings: list[str]) -> str:
    focus = ", ".join(holdings[:3]) if holdings else "danh mục hiện tại"
    options = {
        "CALL": f"Gọi điện chăm sóc khách hàng. Khách quan tâm đến {focus}, muốn được cập nhật tin tức doanh nghiệp.",
        "MEETING": f"Gặp trực tiếp tại chi nhánh. Trao đổi về chiến lược phân bổ tài sản, khách cân nhắc giảm tỷ trọng {focus}.",
        "ADVICE": f"Tư vấn cơ cấu danh mục: giữ {focus}, cân nhắc bổ sung trái phiếu để giảm rủi ro.",
        "FOLLOW_UP": f"Nhắc khách theo dõi tỷ lệ ký quỹ và kế hoạch bổ sung tiền khi thị trường biến động. Danh mục chính: {focus}.",
    }
    return options[note_type]


# ---------------------------------------------------------------- knowledge base

def product_documents(fee_schedules, loan_products, exchanges) -> list[dict]:
    """Knowledge-base documents built from the same parameters the simulator uses, plus RAG Q&A pairs."""
    fee_lines = "\n".join(f"- {name} (mã {code}): phí giao dịch {pct(fee, 2)} giá trị khớp lệnh."
                          for code, name, fee in fee_schedules)
    margin_lines = "\n".join(
        f"- {name} (mã {code}): lãi suất {pct(rate, 1)}/năm, tỷ lệ ký quỹ ban đầu {initial}%, "
        f"tỷ lệ duy trì {maint}%, tỷ lệ xử lý {force}%, hạn mức tối đa {billions(max_loan)}, kỳ hạn {term} ngày."
        for code, name, rate, initial, maint, force, max_loan, term in loan_products)
    band_lines = "\n".join(f"- {code}: biên độ ±{pct(band, 0)}, lô chẵn {lot} cổ phiếu." for code, _, band, lot in exchanges)
    std = next(f for f in fee_schedules if f[0] == "ONLINE_STD")
    mr = next(p for p in loan_products if p[0] == "MR_STD")
    docs = [
        {"document_type": "FEE_POLICY", "title": "Biểu phí giao dịch chứng khoán",
         "body": "Phí giao dịch được tính trên giá trị khớp lệnh và thu khi thanh toán.\n" + fee_lines +
                 "\nThuế thu nhập cá nhân khi bán chứng khoán: 0,1% giá trị bán. Thuế cổ tức bằng tiền: 5%.",
         "qa": [("Phí giao dịch trực tuyến tiêu chuẩn là bao nhiêu?", f"{pct(std[2], 2)} giá trị khớp lệnh."),
                ("Thuế khi bán cổ phiếu là bao nhiêu?", "0,1% giá trị bán.")]},
        {"document_type": "MARGIN_POLICY", "title": "Chính sách giao dịch ký quỹ (margin)",
         "body": "Các gói vay ký quỹ:\n" + margin_lines +
                 "\nKhi tỷ lệ ký quỹ thấp hơn tỷ lệ duy trì, công ty gửi thông báo yêu cầu bổ sung ký quỹ qua SMS, "
                 "email và ứng dụng. Khách hàng có 2 ngày làm việc để nộp thêm tiền hoặc bán bớt chứng khoán. "
                 "Nếu tỷ lệ giảm xuống dưới tỷ lệ xử lý hoặc quá hạn, công ty bán giải chấp vào phiên kế tiếp.",
         "qa": [("Lãi suất margin tiêu chuẩn là bao nhiêu?", f"{pct(mr[2], 1)}/năm."),
                ("Bao lâu phải bổ sung ký quỹ sau khi nhận thông báo?", "2 ngày làm việc.")]},
        {"document_type": "REGULATION_SUMMARY", "title": "Tóm tắt quy định giao dịch",
         "body": "Biên độ dao động giá và lô giao dịch theo sàn:\n" + band_lines +
                 "\nChu kỳ thanh toán T+2: chứng khoán mua về tài khoản sau 2 ngày làm việc, tiền bán về sau 2 ngày làm việc."
                 "\nBước giá HOSE: dưới 10.000 đồng là 10 đồng; từ 10.000 đến dưới 50.000 đồng là 50 đồng; "
                 "từ 50.000 đồng trở lên là 100 đồng.",
         "qa": [("Biên độ giá sàn HOSE là bao nhiêu?", "±7% so với giá tham chiếu."),
                ("Mua cổ phiếu bao lâu thì về tài khoản?", "Sau 2 ngày làm việc (T+2).")]},
        {"document_type": "FAQ", "title": "Câu hỏi thường gặp về phiên giao dịch",
         "body": "Phiên khớp lệnh định kỳ mở cửa (ATO) 9:00-9:15, khớp lệnh liên tục 9:15-11:30 và 13:00-14:30, "
                 "khớp lệnh định kỳ đóng cửa (ATC) 14:30-14:45, giao dịch thỏa thuận đến 15:00. "
                 "Lệnh ATO chỉ đặt trong phiên mở cửa, lệnh ATC chỉ đặt trong phiên đóng cửa. "
                 "Lệnh LO chưa khớp hết sẽ tự hủy khi hết ngày giao dịch.",
         "qa": [("Phiên ATC diễn ra lúc nào?", "14:30 đến 14:45."),
                ("Lệnh LO chưa khớp có được giữ sang ngày hôm sau không?", "Không, lệnh tự hủy khi hết ngày.")]},
        {"document_type": "USER_GUIDE", "title": "Hướng dẫn nạp và rút tiền",
         "body": "Nạp tiền bằng cách chuyển khoản từ tài khoản ngân hàng đã đăng ký đến tài khoản chuyên dùng của "
                 "công ty, ghi nội dung là số tiểu khoản. Tiền được cập nhật trong vòng 15 phút trong giờ làm việc. "
                 "Rút tiền trên ứng dụng về tài khoản ngân hàng đã đăng ký; yêu cầu trước 16:00 được xử lý trong ngày.",
         "qa": [("Rút tiền trước mấy giờ thì được xử lý trong ngày?", "Trước 16:00.")]},
        {"document_type": "TERMS_AND_CONDITIONS", "title": "Điều khoản sử dụng dịch vụ giao dịch trực tuyến",
         "body": "Khách hàng chịu trách nhiệm bảo mật mật khẩu và mã OTP. Tài khoản bị khóa tạm thời sau 5 lần nhập "
                 "sai mật khẩu liên tiếp. Công ty không chịu trách nhiệm với thiệt hại phát sinh do khách hàng tiết lộ "
                 "thông tin đăng nhập cho người khác.",
         "qa": [("Nhập sai mật khẩu bao nhiêu lần thì bị khóa?", "5 lần liên tiếp.")]},
    ]
    return docs
