"""Static reference data. Every company name here is fictional."""
from __future__ import annotations

EXCHANGES = [
    # code, name, price band %, lot size
    ("HOSE", "Sở Giao dịch Chứng khoán TP. Hồ Chí Minh", 7.00, 100),
    ("HNX", "Sở Giao dịch Chứng khoán Hà Nội", 10.00, 100),
    ("UPCOM", "Thị trường UPCoM", 15.00, 100),
]
EXCHANGE_WEIGHTS = {"HOSE": 0.5, "HNX": 0.2, "UPCOM": 0.3}

# level-1 industry -> level-2 sectors: (code, name_vi, name_en, beta, daily vol, issuer prefix, legal prefix)
SECTORS = [
    ("1000", "Tài chính", "Financials", [
        ("1010", "Ngân hàng", "Banks", 1.2, 0.020, "Ngân hàng", "Ngân hàng Thương mại Cổ phần"),
        ("1020", "Chứng khoán", "Securities brokerage", 1.6, 0.032, "Chứng khoán", "Công ty Cổ phần Chứng khoán"),
        ("1030", "Bảo hiểm", "Insurance", 0.8, 0.018, "Bảo hiểm", "Tổng Công ty Cổ phần Bảo hiểm"),
        ("1040", "Quản lý quỹ", "Asset management", 0.9, 0.015, "Quản lý Quỹ", "Công ty TNHH Quản lý Quỹ"),
    ]),
    ("2000", "Bất động sản", "Real Estate", [
        ("2010", "Bất động sản dân cư", "Residential real estate", 1.4, 0.030, "Địa ốc", "Công ty Cổ phần Đầu tư Địa ốc"),
        ("2020", "Khu công nghiệp", "Industrial parks", 1.2, 0.026, "KCN", "Công ty Cổ phần Phát triển Khu công nghiệp"),
    ]),
    ("3000", "Công nghệ", "Technology", [
        ("3010", "Phần mềm và dịch vụ CNTT", "Software and IT services", 1.0, 0.020, "Công nghệ", "Công ty Cổ phần Công nghệ"),
        ("3020", "Viễn thông", "Telecommunications", 0.9, 0.022, "Viễn thông", "Tổng Công ty Cổ phần Viễn thông"),
    ]),
    ("4000", "Hàng tiêu dùng", "Consumer", [
        ("4010", "Thực phẩm và đồ uống", "Food and beverage", 0.7, 0.015, "Thực phẩm", "Công ty Cổ phần Thực phẩm"),
        ("4020", "Bán lẻ", "Retail", 1.0, 0.022, "Bán lẻ", "Công ty Cổ phần Thương mại Bán lẻ"),
    ]),
    ("5000", "Công nghiệp", "Industrials", [
        ("5010", "Xây dựng", "Construction", 1.2, 0.027, "Xây dựng", "Công ty Cổ phần Xây dựng"),
        ("5020", "Vận tải và logistics", "Transport and logistics", 1.0, 0.024, "Logistics", "Công ty Cổ phần Vận tải và Logistics"),
    ]),
    ("6000", "Nguyên vật liệu", "Materials", [
        ("6010", "Thép", "Steel", 1.3, 0.028, "Thép", "Công ty Cổ phần Thép"),
        ("6020", "Hóa chất", "Chemicals", 1.1, 0.024, "Hóa chất", "Công ty Cổ phần Hóa chất"),
    ]),
    ("7000", "Năng lượng và tiện ích", "Energy and utilities", [
        ("7010", "Dầu khí", "Oil and gas", 1.0, 0.024, "Dầu khí", "Tổng Công ty Cổ phần Dầu khí"),
        ("7020", "Điện", "Power", 0.6, 0.016, "Điện lực", "Công ty Cổ phần Điện lực"),
    ]),
    ("8000", "Y tế", "Health care", [
        ("8010", "Dược phẩm", "Pharmaceuticals", 0.6, 0.016, "Dược", "Công ty Cổ phần Dược phẩm"),
    ]),
]
TRADABLE_SECTORS = [s for _, _, _, subs in SECTORS for s in subs if s[0] != "1040"]
SECTOR_BY_CODE = {s[0]: s for _, _, _, subs in SECTORS for s in subs}

# Words combined with a sector prefix to build fictional issuer names.
NAME_CORES = [
    "Sao Mai Xanh", "Thái Bình Dương Mới", "Ngọc Lam", "Hướng Dương", "Cát Tường", "Phúc Lộc Thọ", "Đông Phong",
    "Lam Sơn Mới", "Trúc Xanh", "Hải Âu", "Bạch Dương", "Kim Cương Việt", "Thiên Ân", "Hoa Sen Vàng",
    "Phong Vũ Mới", "Mặt Trời Hồng", "Sông Hàn Xanh", "Đỉnh Cao", "Vươn Xa", "Tầm Nhìn", "Lá Phong",
    "Nhật Quang", "Bình An Phát", "Tân Kỷ Nguyên", "Hợp Nhất", "Đông Dương Xanh", "Tây Nguyên Mới", "Cửu Long Xanh",
    "Hồng Hà Mới", "Trường An", "Vạn Phúc Mới", "Ánh Trăng", "Sao Kim", "Thịnh Vượng Mới", "Đồng Tâm Việt",
    "Minh Khai Mới", "Quang Minh Xanh", "Hưng Long Phát", "Thăng Long Mới", "Gia Định Xanh", "Phương Đông Mới",
    "Bắc Sơn Xanh", "Nam Cường Phát", "Hoàng Gia Xanh", "Bảo Tín Mới", "Tín Nghĩa Xanh", "An Phú Gia",
    "Đại Dương Xanh", "Song Long", "Tam Đảo Mới", "Cầu Vồng", "Thủy Tiên", "Ngân Hà", "Hải Vân Mới",
    "Phù Sa", "Đất Việt Mới", "Sen Hồng", "Nắng Mới", "Mây Trắng", "Ngọn Hải Đăng",
]

BRANCHES = [
    ("HN01", "Chi nhánh Hà Nội", "Hà Nội"),
    ("HN02", "Chi nhánh Hoàn Kiếm", "Hà Nội"),
    ("HCM01", "Chi nhánh TP. Hồ Chí Minh", "TP. Hồ Chí Minh"),
    ("HCM02", "Chi nhánh Sài Gòn", "TP. Hồ Chí Minh"),
    ("HCM03", "Phòng giao dịch Phú Mỹ Hưng", "TP. Hồ Chí Minh"),
    ("DN01", "Chi nhánh Đà Nẵng", "Đà Nẵng"),
    ("HP01", "Chi nhánh Hải Phòng", "Hải Phòng"),
    ("CT01", "Chi nhánh Cần Thơ", "Cần Thơ"),
]

# province, CCCD province code, weight
PROVINCES = [
    ("Hà Nội", "001", 0.28), ("TP. Hồ Chí Minh", "079", 0.34), ("Hải Phòng", "031", 0.05),
    ("Đà Nẵng", "048", 0.05), ("Cần Thơ", "092", 0.03), ("Quảng Ninh", "022", 0.03),
    ("Đồng Nai", "075", 0.04), ("Khánh Hòa", "056", 0.03), ("Nghệ An", "040", 0.04),
    ("Huế", "046", 0.03), ("Lâm Đồng", "068", 0.03), ("Bắc Ninh", "027", 0.05),
]
WARDS = ["Phường Bến Thành", "Phường Hoàn Kiếm", "Phường Ba Đình", "Phường Cầu Giấy", "Phường Tân Định",
         "Phường Hải Châu", "Phường Ninh Kiều", "Phường Ngô Quyền", "Phường Thủ Đức", "Phường Đống Đa",
         "Xã Tân Phú", "Xã Hòa Phước", "Phường An Khánh", "Phường Linh Xuân", "Phường Tây Hồ"]
STREETS = ["Lê Lợi", "Nguyễn Huệ", "Trần Hưng Đạo", "Hai Bà Trưng", "Lý Thường Kiệt", "Điện Biên Phủ",
           "Nguyễn Trãi", "Cách Mạng Tháng Tám", "Phan Đình Phùng", "Võ Văn Tần", "Lạc Long Quân",
           "Nguyễn Văn Linh", "Hoàng Diệu", "Trần Phú", "Quang Trung"]

BANKS = ["VCB", "BIDV", "CTG", "TCB", "MBB", "ACB", "VPB", "TPB", "STB", "VIB"]

PHONE_PREFIXES = ["090", "091", "093", "094", "096", "097", "098", "086", "088", "032", "033", "035",
                  "070", "077", "079", "081", "083", "084", "085"]

FOREIGN_NATIONALITIES = [("KR", "ko_KR"), ("JP", "ja_JP"), ("SG", "en_US"), ("US", "en_US"), ("TW", "zh_TW"),
                         ("FR", "fr_FR"), ("AU", "en_US")]

FEE_SCHEDULES = [
    # code, name, trading fee %
    ("ONLINE_STD", "Gói giao dịch trực tuyến tiêu chuẩn", 0.15),
    ("BROKER_ASSIST", "Gói có chuyên viên môi giới chăm sóc", 0.25),
    ("VIP", "Gói khách hàng VIP", 0.10),
    ("INSTITUTION", "Gói khách hàng tổ chức", 0.08),
]

LOAN_PRODUCTS = [
    # code, name, rate %, initial %, maintenance %, force-sell %, max loan, term days
    ("MR_STD", "Margin tiêu chuẩn", 13.5, 50, 40, 30, 5_000_000_000, 90),
    ("MR_VIP", "Margin VIP", 11.5, 50, 40, 30, 50_000_000_000, 180),
    ("MR_PROMO", "Margin ưu đãi 30 ngày", 9.9, 50, 40, 30, 1_000_000_000, 30),
]

AML_RULES = [
    ("STRUCTURING", "Chia nhỏ giao dịch nạp tiền",
     "Từ 3 lần nạp tiền trở lên trong cùng một ngày, mỗi lần từ 250 triệu đến dưới 300 triệu đồng, "
     "dấu hiệu né ngưỡng báo cáo giao dịch giá trị lớn.", "HIGH"),
    ("LARGE_CASH", "Nạp tiền giá trị lớn",
     "Một lần nạp tiền từ 1 tỷ đồng trở lên.", "LOW"),
    ("RAPID_IN_OUT", "Nạp vào rút ra nhanh",
     "Nạp từ 500 triệu đồng trở lên rồi rút ra ít nhất 90% số tiền trong vòng 2 ngày mà không giao dịch chứng khoán.",
     "HIGH"),
    ("SHARED_DEVICE", "Nhiều khách hàng dùng chung thiết bị",
     "Một thiết bị đăng nhập thành công vào hơn 3 khách hàng khác nhau trong 30 ngày.", "MEDIUM"),
    ("SPOOFING", "Đặt và hủy lệnh bất thường",
     "Hơn 20 lệnh bị hủy trong vòng 5 giây sau khi đặt trong cùng một ngày.", "HIGH"),
    ("WASH_TRADE", "Giao dịch tự tạo cung cầu",
     "Các tài khoản dùng chung thiết bị mua và bán cùng một mã trong vòng 5 phút, từ 3 lần trở lên trong ngày.",
     "HIGH"),
]

EMPLOYEE_ROLES = [
    ("BROKER", 0.35), ("RELATIONSHIP_MANAGER", 0.25), ("SUPPORT", 0.15), ("OPERATIONS", 0.10),
    ("ANALYST", 0.08), ("COMPLIANCE", 0.07),
]

NEWS_SOURCES = ["Bản tin Thị trường", "Nhịp sống Đầu tư", "Tài chính Số", "Kinh tế 24h", "Tin nhanh Chứng khoán"]
