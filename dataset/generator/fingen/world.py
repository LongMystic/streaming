"""Builds the initial world: reference data, products, customers and their opening balances."""
from __future__ import annotations

import math
import string
from datetime import date, datetime, timedelta, timezone

from . import refdata, textgen
from .calendar_vn import (add_trading_days, first_trading_day_on_or_after, holidays, is_trading_day, trading_days,
                          vn_time)
from .config import ANCHOR_SYMBOLS, BROKER_CODE
from .market import round_to_tick
from .model import Account, Customer, Instrument

UTC = timezone.utc
EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

# segment: weight, orders/day, logins/day, cash flows/day, median wealth, wealth sigma, P(margin), P(has RM)
SEGMENTS = {
    "DORMANT": (0.28, 0.003, 0.02, 0.002, 30e6, 1.0, 0.00, 0.05),
    "PASSIVE": (0.34, 0.04, 0.25, 0.010, 150e6, 1.0, 0.05, 0.10),
    "ACTIVE": (0.24, 0.35, 1.20, 0.040, 600e6, 0.9, 0.45, 0.50),
    "DAY_TRADER": (0.06, 2.50, 3.00, 0.080, 1.2e9, 0.8, 0.85, 0.30),
    "HNW": (0.05, 0.50, 1.00, 0.040, 8e9, 0.8, 0.50, 1.00),
    "INSTITUTION": (0.03, 1.00, 1.00, 0.030, 40e9, 1.0, 0.00, 1.00),
}
RISK_BY_SEGMENT = {
    "DORMANT": ["CONSERVATIVE", "BALANCED"], "PASSIVE": ["CONSERVATIVE", "BALANCED", "BALANCED"],
    "ACTIVE": ["BALANCED", "AGGRESSIVE"], "DAY_TRADER": ["AGGRESSIVE", "AGGRESSIVE", "BALANCED"],
    "HNW": ["BALANCED", "AGGRESSIVE", "CONSERVATIVE"], "INSTITUTION": ["BALANCED"],
}


def ts(d: date, hour: int = 9, minute: int = 0) -> datetime:
    return vn_time(d, hour, minute)


# ---------------------------------------------------------------- reference

def build_reference(e) -> None:
    p = e.preset
    for code, name, band, lot in refdata.EXCHANGES:
        e.out("ref.exchanges", {"exchange_code": code, "name": name, "price_band_pct": band, "lot_size": lot,
                                "created_at": EPOCH, "updated_at": EPOCH})
    cal_start, cal_end = date(p.start.year - 1, 1, 1), date(min(p.end.year + 1, 2026), 12, 31)
    hol = holidays()
    d = cal_start
    while d <= cal_end:
        for code, *_ in refdata.EXCHANGES:
            e.out("ref.trading_calendar", {"calendar_date": d, "exchange_code": code,
                                           "is_trading_day": is_trading_day(d), "holiday_name": hol.get(d)})
        d += timedelta(days=1)
    for code, name_vi, name_en, subs in refdata.SECTORS:
        e.out("ref.sectors", {"sector_code": code, "parent_sector_code": None, "level": 1,
                              "name_en": name_en, "name_vi": name_vi})
        for sub in subs:
            e.out("ref.sectors", {"sector_code": sub[0], "parent_sector_code": code, "level": 2,
                                  "name_en": sub[2], "name_vi": sub[1]})
    for code, name, province in refdata.BRANCHES:
        bid = e.nid("ref.branches")
        e.branches.append(bid)
        e.out("ref.branches", {"branch_id": bid, "branch_code": code, "name": name, "province": province,
                               "opened_on": date(2008 + bid, 3, 1)})
    roles = [r for r, _ in refdata.EMPLOYEE_ROLES]
    weights = [w for _, w in refdata.EMPLOYEE_ROLES]
    for i in range(p.employees):
        eid = e.nid("ref.employees")
        role = roles[i] if i < len(roles) else e.r.choices(roles, weights)[0]
        hired = date(e.r.randint(2012, 2024), e.r.randint(1, 12), e.r.randint(1, 28))
        inactive = e.r.random() < 0.05
        name = e.fake.name()
        e.employees.setdefault(role, []).append(eid)
        e.out("ref.employees", {
            "employee_id": eid, "employee_code": f"NV{eid:05d}", "full_name": name,
            "email": f"nv{eid:05d}@{BROKER_CODE.lower()}sec.vn", "role": role,
            "branch_id": e.r.choice(e.branches), "hired_on": hired,
            "terminated_on": p.start - timedelta(days=e.r.randint(30, 400)) if inactive else None,
            "status": "INACTIVE" if inactive else "ACTIVE", "created_at": EPOCH, "updated_at": EPOCH})
        if inactive:
            e.employees[role].remove(eid)
    for code, name, fee in refdata.FEE_SCHEDULES:
        fid = e.nid("product.fee_schedules")
        e.fee[code] = (fid, fee / 100)
        e.out("product.fee_schedules", {"fee_schedule_id": fid, "fee_schedule_code": code, "name": name,
                                        "channel": None, "trading_fee_pct": fee, "min_fee_per_order": 0,
                                        "effective_from": date(2023, 1, 1), "effective_to": None})
    for code, name, rate, initial, maint, force, max_loan, term in refdata.LOAN_PRODUCTS:
        lid = e.nid("margin.loan_products")
        e.loan_products[lid] = {"code": code, "rate": rate, "maintenance": maint, "force": force,
                                "max_loan": max_loan, "term": term}
        e.loan_product_by_code[code] = lid
        e.out("margin.loan_products", {
            "loan_product_id": lid, "loan_product_code": code, "name": name, "annual_interest_rate_pct": rate,
            "overdue_interest_rate_pct": round(rate * 1.5, 4), "initial_margin_ratio_pct": initial,
            "maintenance_ratio_pct": maint, "force_sell_ratio_pct": force, "max_loan_amount": max_loan,
            "loan_term_days": term, "effective_from": date(2023, 1, 1), "effective_to": None})
    for code, name, desc, severity in refdata.AML_RULES:
        e.aml_severity[code] = severity
        e.out("compliance.aml_rules", {"rule_code": code, "name": name, "description": desc,
                                       "severity": severity, "is_active": True})
    docs = textgen.product_documents(refdata.FEE_SCHEDULES, refdata.LOAN_PRODUCTS, refdata.EXCHANGES)
    for doc in docs:
        did = e.nid("content.product_documents")
        e.out("content.product_documents", {
            "document_id": did, "document_type": doc["document_type"], "title": doc["title"], "body": doc["body"],
            "version_label": "v1.0", "effective_from": date(2024, 1, 1), "effective_to": None})
        for q, a in doc["qa"]:
            e.gt.rag_qa.append({"document_id": did, "question": q, "answer": a})


# ---------------------------------------------------------------- products

def _issuer(e, sector_code: str | None, short: str | None = None) -> tuple[int, str, str]:
    """sector_code None creates a non-corporate issuer (e.g. the simulated State Treasury) named `short`."""
    iid = e.nid("product.issuers")
    if sector_code is None:
        short_name = legal = short
        description = f"{legal}: tổ chức phát hành trái phiếu chính phủ trong bộ dữ liệu mô phỏng."
    else:
        sector = refdata.SECTOR_BY_CODE[sector_code]
        while True:
            core = e.r.choice(refdata.NAME_CORES)
            if (sector_code, core) not in e.used_issuer_names:
                break
        e.used_issuer_names.add((sector_code, core))
        short_name, legal = f"{sector[5]} {core}", f"{sector[6]} {core}"
        description = f"{legal} hoạt động trong lĩnh vực {sector[1].lower()}. Đây là doanh nghiệp hư cấu trong bộ dữ liệu mô phỏng."
    e.out("product.issuers", {
        "issuer_id": iid, "short_name": short_name, "legal_name": legal, "sector_code": sector_code,
        "tax_code": f"{e.r.randint(1, 9)}{e.r.randint(0, 999_999_999):09d}",
        "headquarters_province": e.r.choices([p[0] for p in refdata.PROVINCES], [p[2] for p in refdata.PROVINCES])[0],
        "founded_year": e.r.randint(1990, 2015), "charter_capital": e.r.randint(30, 30_000) * 1_000_000_000,
        "website": f"https://issuer{iid}.example.vn", "description": description,
        "created_at": EPOCH, "updated_at": EPOCH})
    return iid, short_name, legal


def _symbol(e) -> str:
    while True:
        sym = "Z" + "".join(e.r.choices(string.ascii_uppercase, k=2))
        if sym not in e.used_symbols:
            e.used_symbols.add(sym)
            return sym


def _instrument_row(inst: Instrument, isin: str, listed_on: date | None, delisted_on: date | None,
                    foreign_limit: float | None) -> dict:
    return {"instrument_id": inst.instrument_id, "symbol": inst.symbol, "isin": isin, "instrument_type": inst.itype,
            "exchange_code": inst.exchange, "issuer_id": inst.issuer_id, "name": inst.name, "currency_code": "VND",
            "lot_size": inst.lot, "listed_shares": inst.listed_shares, "foreign_ownership_limit_pct": foreign_limit,
            "status": inst.status, "listed_on": listed_on, "delisted_on": delisted_on,
            "created_at": EPOCH, "updated_at": EPOCH, "version": inst.version}


def build_products(e) -> None:
    p = e.preset
    e.used_symbols.update(ANCHOR_SYMBOLS)
    band = {code: b for code, _, b, _ in refdata.EXCHANGES}
    sub_codes = [s[0] for s in refdata.TRADABLE_SECTORS]
    plan = [(sym, sec) for sym, sec in ANCHOR_SYMBOLS.items()]
    plan += [(None, e.r.choice(sub_codes)) for _ in range(p.stocks - len(plan))]
    for symbol, sector_code in plan:
        sector = refdata.SECTOR_BY_CODE[sector_code]
        issuer_id, short, legal = _issuer(e, sector_code)
        symbol = symbol or _symbol(e)
        exchange = "HOSE" if symbol in ANCHOR_SYMBOLS else e.r.choices(list(refdata.EXCHANGE_WEIGHTS),
                                                                         list(refdata.EXCHANGE_WEIGHTS.values()))[0]
        price = round_to_tick(min(250_000, max(3_000, math.exp(e.rng.normal(math.log(20_000), 0.7)))), exchange, "STOCK")
        shares_median = {"HOSE": 300e6, "HNX": 80e6, "UPCOM": 50e6}[exchange]
        listed = int(round(math.exp(e.rng.normal(math.log(shares_median), 0.9)), -4))
        turnover = {"HOSE": 0.006, "HNX": 0.003, "UPCOM": 0.0015}[exchange] * math.exp(e.rng.normal(0, 0.6))
        status = "ACTIVE"
        if symbol not in ANCHOR_SYMBOLS:
            status = e.r.choices(["ACTIVE", "SUSPENDED", "DELISTED"], [0.975, 0.015, 0.01])[0]
        inst = Instrument(
            instrument_id=e.nid("product.instruments"), symbol=symbol, itype="STOCK", exchange=exchange,
            issuer_id=issuer_id, name=legal, sector_code=sector_code, lot=100, band=band[exchange],
            mu=float(e.rng.normal(0.0002, 0.0008)),
            sigma=sector[4] * e.r.uniform(0.8, 1.3) * (1.3 if exchange == "UPCOM" else 1.0),
            beta=sector[3] * e.r.uniform(0.8, 1.2), liquidity=listed * turnover, last_close=price,
            listed_shares=listed, status=status)
        e.add_instrument(inst)
        listed_on = date(e.r.randint(2006, 2022), e.r.randint(1, 12), e.r.randint(1, 28))
        e.out("product.instruments", _instrument_row(
            inst, f"VN{inst.instrument_id:09d}{inst.instrument_id % 10}", listed_on,
            p.start - timedelta(days=e.r.randint(30, 600)) if status == "DELISTED" else None,
            30.0 if sector_code == "1010" else 49.0))
        _financial_statements(e, inst)

    # standard margin list: the more liquid HOSE/HNX stocks
    candidates = sorted((i for i in e.instruments.values() if i.itype == "STOCK" and i.status == "ACTIVE"
                         and i.exchange in ("HOSE", "HNX")), key=lambda i: -i.liquidity)
    for rank, inst in enumerate(candidates[: int(len(candidates) * 0.6)]):
        inst.margin_ratio = [50, 40, 30, 20][min(3, rank * 4 // max(1, len(candidates)))] / 100
        for lid in e.loan_products:
            e.out("margin.marginable_instruments", {
                "loan_product_id": lid, "instrument_id": inst.instrument_id, "loan_ratio_pct": inst.margin_ratio * 100,
                "max_price": None, "effective_from": p.start - timedelta(days=180), "effective_to": None})

    managers = [_issuer(e, "1040") for _ in range(max(2, p.funds // 2))]
    for k in range(p.etfs):
        mgr = managers[k % len(managers)]
        price = round_to_tick(e.r.uniform(12_000, 30_000), "HOSE", "ETF")
        inst = Instrument(e.nid("product.instruments"), f"FUEZ{string.ascii_uppercase[k % 26]}{k // 26 or ''}", "ETF",
                          "HOSE", mgr[0], f"Quỹ ETF {mgr[1]} {k + 1}", None, 100, band["HOSE"], 0.0002, 0.012,
                          1.0, 2e6 * e.r.uniform(0.3, 2), price, int(e.r.uniform(20e6, 200e6)))
        e.add_instrument(inst)
        e.out("product.instruments", _instrument_row(inst, f"VN{inst.instrument_id:09d}{inst.instrument_id % 10}",
                                                     date(2018 + k % 6, 6, 1), None, 100.0))
        e.out("product.fund_details", {"instrument_id": inst.instrument_id, "fund_type": "EQUITY",
                                       "management_fee_pct": 0.65, "subscription_fee_pct": 0, "redemption_fee_pct": 0,
                                       "nav_frequency": "DAILY", "inception_date": date(2018 + k % 6, 5, 1)})
    for k in range(p.funds):
        mgr = managers[k % len(managers)]
        ftype = ["EQUITY", "BOND", "BALANCED", "MONEY_MARKET"][k % 4]
        inst = Instrument(e.nid("product.instruments"), f"ZF{k + 1:02d}{ftype[0]}", "FUND_CERTIFICATE", None,
                          mgr[0], f"Quỹ đầu tư {ftype.lower().replace('_', ' ')} {mgr[1]} {k + 1}", None, 1, 0,
                          0.0003 if ftype == "EQUITY" else 0.0002, 0.009 if ftype == "EQUITY" else 0.002, 0.6,
                          0, int(e.r.uniform(10_000, 30_000)), 0)
        inst.status = "ACTIVE"
        e.add_instrument(inst)
        e.funds[inst.instrument_id] = {"nav": float(inst.last_close), "units": e.r.uniform(5e6, 80e6),
                                       "weekly": ftype in ("BOND", "MONEY_MARKET")}
        e.out("product.instruments", _instrument_row(inst, f"VN{inst.instrument_id:09d}{inst.instrument_id % 10}",
                                                     None, None, None))
        e.out("product.fund_details", {
            "instrument_id": inst.instrument_id, "fund_type": ftype,
            "management_fee_pct": {"EQUITY": 1.75, "BOND": 0.9, "BALANCED": 1.5, "MONEY_MARKET": 0.5}[ftype],
            "subscription_fee_pct": 0.5 if ftype != "MONEY_MARKET" else 0, "redemption_fee_pct": 1.0,
            "nav_frequency": "WEEKLY" if e.funds[inst.instrument_id]["weekly"] else "DAILY",
            "inception_date": date(2015 + k % 9, 3, 1)})

    gov = _issuer(e, None, short="Kho bạc Nhà nước (giả lập)")
    bank_issuers = [i for i in e.instruments.values() if i.sector_code in ("1010", "2010") and i.itype == "STOCK"]
    for k in range(p.bonds):
        government = k % 3 == 0 or not bank_issuers
        issue = date(e.r.randint(2020, 2024), e.r.randint(1, 12), e.r.randint(1, 28))
        years = e.r.choice([3, 5, 7, 10, 15]) if government else e.r.choice([2, 3, 5])
        if government:
            symbol, issuer_id, name = f"ZGB{issue.year % 100}{k:03d}", gov[0], f"Trái phiếu Chính phủ (giả lập) kỳ hạn {years} năm"
        else:
            under = bank_issuers[k % len(bank_issuers)]
            symbol, issuer_id, name = (f"{under.symbol}{issue.year % 100}{k:03d}", under.issuer_id,
                                       f"Trái phiếu doanh nghiệp {under.name} {issue.year}")
        inst = Instrument(e.nid("product.instruments"), symbol, "BOND", "HNX" if government or k % 2 else None,
                          issuer_id, name, None, 1, 0, 0, 0, 0, 0, 100_000, int(e.r.uniform(1e6, 50e6)))
        maturity = date(issue.year + years, issue.month, issue.day)
        inst.status = "ACTIVE" if maturity > p.start else "MATURED"
        e.add_instrument(inst)
        e.out("product.instruments", _instrument_row(inst, f"VN{inst.instrument_id:09d}{inst.instrument_id % 10}",
                                                     issue if inst.exchange else None, None, None))
        e.out("product.bond_details", {
            "instrument_id": inst.instrument_id, "bond_type": "GOVERNMENT" if government else "CORPORATE",
            "face_value": 100_000, "coupon_rate_pct": round(e.r.uniform(2.0, 4.5) if government else e.r.uniform(6.5, 11.5), 4),
            "coupon_frequency": 1 if government else e.r.choice([2, 4]), "issue_date": issue, "maturity_date": maturity,
            "credit_rating": None if government else e.r.choice(["A", "A-", "BBB+", "BBB", "BB+"]),
            "is_secured": (not government) and e.r.random() < 0.6})

    brokers = [i for i in e.instruments.values() if i.sector_code == "1020" and i.itype == "STOCK"]
    underlyings = [i for i in candidates if i.exchange == "HOSE"][:20]
    for k in range(p.covered_warrants if underlyings else 0):
        under = underlyings[k % len(underlyings)]
        issuer_id = (brokers[k % len(brokers)].issuer_id if brokers else under.issuer_id)
        issue = p.start - timedelta(days=e.r.randint(10, 150))
        maturity = issue + timedelta(days=e.r.choice([180, 270, 365]))
        ratio = float(e.r.choice([2, 4, 5, 8, 10]))
        strike = round_to_tick(under.last_close * e.r.uniform(0.9, 1.2), "HOSE", "STOCK")
        inst = Instrument(e.nid("product.instruments"), f"C{under.symbol}{issue.year % 100}{k + 1:02d}",
                          "COVERED_WARRANT", "HOSE", issuer_id, f"Chứng quyền {under.symbol} kỳ hạn {(maturity - issue).days} ngày",
                          None, 100, band["HOSE"], 0, 0, 0, 0, 0, int(e.r.uniform(2e6, 20e6)))
        inst.status = "ACTIVE" if maturity > p.start else "MATURED"
        e.add_instrument(inst)
        e.warrants[inst.instrument_id] = {"underlying": under, "strike": strike, "ratio": ratio, "maturity": maturity}
        inst.last_close = e.warrant_price(inst.instrument_id, under.last_close, p.start)
        e.out("product.instruments", _instrument_row(inst, f"VN{inst.instrument_id:09d}{inst.instrument_id % 10}",
                                                     issue + timedelta(days=7), None, 100.0))
        e.out("product.warrant_details", {
            "instrument_id": inst.instrument_id, "underlying_instrument_id": under.instrument_id, "warrant_type": "CALL",
            "exercise_price": strike, "conversion_ratio": ratio, "issue_date": issue, "maturity_date": maturity,
            "last_trading_date": add_trading_days(maturity, -2)})


def _financial_statements(e, inst: Instrument) -> None:
    mcap = inst.last_close * inst.listed_shares
    bank = inst.sector_code == "1010"
    assets = mcap * (e.r.uniform(6, 12) if bank else e.r.uniform(0.8, 3))
    equity_ratio = e.r.uniform(0.07, 0.12) if bank else e.r.uniform(0.3, 0.6)
    margin = e.r.uniform(0.1, 0.4)
    loss_maker = e.r.random() < 0.08
    # (fiscal year, quarter, publish date); quarter 0 = audited full year
    periods = []
    for year in range(e.preset.start.year - 1, e.preset.end.year + 1):
        periods += [(year, 1, date(year, 4, 25)), (year, 2, date(year, 7, 25)), (year, 3, date(year, 10, 25)),
                    (year, 4, date(year + 1, 1, 25)), (year, 0, date(year + 1, 3, 28))]
    for year, quarter, published in periods:
        if published > e.preset.end:
            continue
        published += timedelta(days=e.r.randint(-5, 5))
        growth = (1 + inst.mu * 250) ** (year - 2023)
        revenue = assets * e.r.uniform(0.04, 0.12) * growth * (4 if quarter == 0 else 1)
        gross = revenue * margin * e.r.uniform(0.85, 1.15)
        net = gross * e.r.uniform(0.3, 0.6) * (-0.5 if loss_maker and e.r.random() < 0.6 else 1)
        row = {"issuer_id": inst.issuer_id, "fiscal_year": year, "fiscal_quarter": quarter,
               "revenue": round(revenue, -6), "gross_profit": round(gross, -6), "net_income": round(net, -6),
               "total_assets": round(assets * growth, -6), "total_liabilities": round(assets * growth * (1 - equity_ratio), -6),
               "owner_equity": round(assets * growth * equity_ratio, -6),
               "operating_cash_flow": round(net * e.r.uniform(0.4, 1.6), -6),
               "eps": round(net / inst.listed_shares, 2), "is_audited": quarter == 0, "published_on": published}
        e.out("product.financial_statements", row)
        if published >= e.preset.start - timedelta(days=120):
            day = first_trading_day_on_or_after(published)
            e.pending_fs_disclosures.setdefault(day, []).append((inst, row))


# ---------------------------------------------------------------- customers

def _phone(e) -> str:
    return e.r.choice(refdata.PHONE_PREFIXES) + f"{e.r.randint(0, 9_999_999):07d}"


def build_customers(e) -> None:
    p = e.preset
    seg_names = list(SEGMENTS)
    seg_weights = [SEGMENTS[s][0] for s in seg_names]
    provinces = refdata.PROVINCES
    days = trading_days(p.start, p.end)
    foreign_seq = 0
    rms = e.employees.get("RELATIONSHIP_MANAGER", []) + e.employees.get("BROKER", [])
    sector_codes = [s[0] for s in refdata.TRADABLE_SECTORS]
    for n in range(p.customers):
        cid = e.nid("customer.customers")
        segment = e.r.choices(seg_names, seg_weights)[0]
        weight, rate, login, cash_rate, wealth_med, wealth_sigma, p_margin, p_rm = SEGMENTS[segment]
        institution = segment == "INSTITUTION"
        foreign = (not institution) and e.r.random() < 0.04
        in_window = e.r.random() < 0.08 and segment not in ("DORMANT", "INSTITUTION")
        if in_window:
            opened = e.r.choice(days[:-5])
        else:
            opened = p.start - timedelta(days=e.r.randint(30, 3000))
        opened_at = vn_time(opened, e.r.randint(8, 20), e.r.randint(0, 59))
        status = "DORMANT" if segment == "DORMANT" else "ACTIVE"
        if not in_window and segment in ("DORMANT", "PASSIVE") and e.r.random() < 0.02:
            status = "CLOSED"
        province, prov_code, _ = e.r.choices(provinces, [x[2] for x in provinces])[0]
        gender = e.r.choice(["MALE", "FEMALE"])
        nationality, locale = ("VN", "vi_VN")
        if foreign:
            nationality, locale = e.r.choice(refdata.FOREIGN_NATIONALITIES)
        if institution:
            name = f"{e.r.choice(['Công ty Cổ phần Đầu tư', 'Công ty TNHH Đầu tư', 'Quỹ Đầu tư'])} {e.r.choice(refdata.NAME_CORES)} {n}"
            dob, gender = None, None
        else:
            faker = e.fakers[locale]
            name = faker.name_male() if gender == "MALE" else faker.name_female()
            age = e.r.randint(20, 35) if segment == "DAY_TRADER" else e.r.randint(22, 72)
            dob = date(p.start.year - age, e.r.randint(1, 12), e.r.randint(1, 28))
        rm = e.r.choice(rms) if rms and e.r.random() < p_rm else None
        risk = e.r.choice(RISK_BY_SEGMENT[segment])
        custody = f"{BROKER_CODE}{'F' if foreign else 'C'}{cid:06d}"
        devices = [f"dev-{e.r.getrandbits(48):012x}" for _ in range(e.r.randint(1, 2))]
        c = Customer(
            customer_id=cid, customer_code=f"KH{cid:07d}", custody_code=custody, segment=segment,
            ctype="INSTITUTION" if institution else "INDIVIDUAL", is_foreign=foreign,
            branch_id=e.r.choice(e.branches), rm_employee_id=rm, opened=opened, status=status,
            order_rate=rate * p.rate_scale, login_rate=login, cash_flow_rate=cash_rate,
            wealth=int(math.exp(e.rng.normal(math.log(wealth_med), wealth_sigma))), risk_appetite=risk,
            sectors=e.r.sample(sector_codes, 3), devices=devices, ips=[e.fake.ipv4_public() for _ in devices],
            bank_account_id=0)
        if foreign:
            foreign_seq += 1
        onboarding = ("BRANCH" if institution or opened.year < 2019 else
                      e.r.choices(["EKYC_MOBILE", "EKYC_WEB", "BRANCH", "PARTNER"], [0.6, 0.2, 0.1, 0.1])[0])
        c.row = {
            "customer_id": cid, "customer_code": c.customer_code, "custody_code": custody, "customer_type": c.ctype,
            "full_name": name, "date_of_birth": dob, "gender": gender, "nationality": nationality,
            "is_foreign": foreign, "foreign_trading_code": f"CA{foreign_seq:05d}" if foreign else None,
            "occupation": None if institution else e.r.choice(["Nhân viên văn phòng", "Kinh doanh tự do", "Kỹ sư", "Giáo viên",
                                                               "Bác sĩ", "Chủ doanh nghiệp", "Hưu trí", "Sinh viên"]),
            "annual_income_band": None if institution else _income_band(c.wealth),
            "email": f"{e.fake.user_name()}{cid}@{e.r.choice(['gmail.com', 'yahoo.com', 'outlook.com'])}",
            "phone": _phone(e), "status": status, "onboarding_channel": onboarding,
            "referred_by_customer_id": e.r.randint(1, cid - 1) if cid > 10 and e.r.random() < 0.1 else None,
            "rm_employee_id": rm, "branch_id": c.branch_id, "opened_at": opened_at,
            "closed_at": opened_at + timedelta(days=e.r.randint(100, 900)) if status == "CLOSED" else None,
            "created_at": opened_at, "updated_at": opened_at, "version": 1}
        if c.row["closed_at"] and c.row["closed_at"] >= vn_time(p.start, 0):
            c.row["closed_at"] = vn_time(p.start - timedelta(days=3), 10)
        e.customers.append(c)
        e.customer_by_id[cid] = c
        e.out("customer.customers", c.row)
        _customer_details(e, c, province, prov_code, opened_at)
        _accounts(e, c, opened_at, p_margin, in_window)


def _income_band(wealth: int) -> str:
    for limit, band in [(300e6, "UNDER_200M"), (1e9, "200M_500M"), (3e9, "500M_1B"), (20e9, "1B_5B")]:
        if wealth < limit:
            return band
    return "OVER_5B"


def _customer_details(e, c: Customer, province: str, prov_code: str, opened_at: datetime) -> None:
    if c.ctype == "INSTITUTION":
        doc_type, number = "BUSINESS_REGISTRATION", f"0{e.r.randint(100_000_000, 999_999_999)}"
    elif c.is_foreign:
        doc_type, number = "PASSPORT", f"{c.row['nationality']}{e.r.randint(10_000_000, 99_999_999)}"
    else:
        century = (0 if c.row["date_of_birth"].year < 2000 else 2) + (0 if c.row["gender"] == "MALE" else 1)
        number = f"{prov_code}{century}{c.row['date_of_birth'].year % 100:02d}{e.r.randint(0, 999_999):06d}"
        doc_type = "CCCD"
    issued = (opened_at - timedelta(days=e.r.randint(30, 2000))).date()
    e.out("customer.identity_documents", {
        "document_id": e.nid("customer.identity_documents"), "customer_id": c.customer_id, "document_type": doc_type,
        "document_number": number, "issued_on": issued,
        "issued_place": "Cục Cảnh sát quản lý hành chính về trật tự xã hội" if doc_type == "CCCD" else None,
        "expires_on": issued + timedelta(days=15 * 365) if doc_type != "BUSINESS_REGISTRATION" else None,
        "is_primary": True, "created_at": opened_at})
    e.out("customer.addresses", {
        "address_id": e.nid("customer.addresses"), "customer_id": c.customer_id,
        "address_type": "REGISTERED_OFFICE" if c.ctype == "INSTITUTION" else "PERMANENT",
        "address_line": f"Số {e.r.randint(1, 300)} {e.r.choice(refdata.STREETS)}", "ward": e.r.choice(refdata.WARDS),
        "province": province, "country_code": "VN", "created_at": opened_at, "updated_at": opened_at})
    for k in range(e.r.choice([1, 1, 1, 2])):
        bid = e.nid("customer.bank_accounts")
        if k == 0:
            c.bank_account_id = bid
        e.out("customer.bank_accounts", {
            "bank_account_id": bid, "customer_id": c.customer_id, "bank_code": e.r.choice(refdata.BANKS),
            "account_number": f"{e.r.randint(10**9, 10**13 - 1)}", "account_name": c.row["full_name"].upper(),
            "is_default": k == 0, "verified_at": opened_at + timedelta(minutes=30), "created_at": opened_at})
    e.kyc[c.customer_id] = _kyc_row(e, c, opened_at)
    e.out("customer.kyc_profiles", e.kyc[c.customer_id])


def _kyc_row(e, c: Customer, valid_from: datetime) -> dict:
    exp = {"DAY_TRADER": "1_3Y", "HNW": "OVER_5Y", "INSTITUTION": "OVER_5Y", "ACTIVE": "3_5Y"}.get(
        c.segment, e.r.choice(["NONE", "UNDER_1Y", "1_3Y"]))
    objective = {"CONSERVATIVE": "CAPITAL_PRESERVATION", "BALANCED": "INCOME", "AGGRESSIVE": "GROWTH"}[c.risk_appetite]
    if c.segment == "DAY_TRADER":
        objective = "SPECULATION"
    return {"kyc_profile_id": e.nid("customer.kyc_profiles"), "customer_id": c.customer_id,
            "risk_rating": "HIGH" if c.fraud_pattern else e.r.choices(["LOW", "MEDIUM", "HIGH"], [0.75, 0.22, 0.03])[0],
            "risk_appetite": c.risk_appetite, "investment_experience": exp, "investment_objective": objective,
            "source_of_funds": "BUSINESS" if c.ctype == "INSTITUTION" else e.r.choice(["SALARY", "BUSINESS", "INVESTMENT", "SALARY"]),
            "is_pep": e.r.random() < 0.003, "is_professional_investor": c.segment in ("HNW", "INSTITUTION"),
            "reviewed_by_employee_id": e.r.choice(e.employees.get("COMPLIANCE", [None])),
            "valid_from": valid_from, "valid_to": None}


def _accounts(e, c: Customer, opened_at: datetime, p_margin: float, in_window: bool) -> None:
    if c.segment == "INSTITUTION":
        fee_code = "INSTITUTION"
    elif c.segment == "HNW":
        fee_code = "VIP"
    elif c.rm_employee_id:
        fee_code = "BROKER_ASSIST"
    else:
        fee_code = "ONLINE_STD"
    fee_id, fee_pct = e.fee[fee_code]
    types = ["CASH"] + (["MARGIN"] if e.r.random() < p_margin else [])
    for atype in types:
        lp = None
        if atype == "MARGIN":
            code = "MR_VIP" if c.segment == "HNW" else ("MR_PROMO" if e.r.random() < 0.1 else "MR_STD")
            lp = e.loan_product_by_code[code]
        acc = Account(account_id=e.nid("account.accounts"), account_no=c.custody_code + ("6" if atype == "MARGIN" else "1"),
                      customer_id=c.customer_id, atype=atype, fee_pct=fee_pct, fee_schedule_id=fee_id,
                      loan_product_id=lp, opened_at=opened_at,
                      status="CLOSED" if c.status == "CLOSED" else "ACTIVE")
        c.accounts[atype] = acc.account_id
        e.accounts[acc.account_id] = acc
        e.out("account.accounts", e.account_row(acc, opened_at))
    if c.status == "CLOSED":
        for acc_id in c.accounts.values():
            e.out("ledger.cash_balances", e.cash_row(e.accounts[acc_id], opened_at))
        return
    cash_share = e.r.uniform(0.3, 0.6)
    cash_total = int(round(c.wealth * cash_share, -5))
    when = vn_time(c.opened, 10) if in_window else vn_time(e.preset.start - timedelta(days=1), 16)
    accs = [e.accounts[a] for a in c.accounts.values()]
    for k, acc in enumerate(accs):
        amount = cash_total // len(accs)
        if in_window:
            e.at(when + timedelta(minutes=k), e.deposit, acc, amount, "BANK_TRANSFER", "Nạp tiền lần đầu")
            e.out("ledger.cash_balances", e.cash_row(acc, opened_at))
        else:
            acc.available += amount
            e.journal(acc, "ADJUSTMENT", amount, when, e.preset.start - timedelta(days=1), "OPENING_BALANCE", None,
                      "SYSTEM", "Số dư đầu kỳ chuyển sang hệ thống mới")
            e.touch_cash(acc, when)
    if not in_window and c.segment != "DORMANT":
        _initial_positions(e, c, accs[0], int(c.wealth * (1 - cash_share)), when)


def _initial_positions(e, c: Customer, acc: Account, budget: int, when: datetime) -> None:
    n = {"HNW": e.r.randint(5, 12), "INSTITUTION": e.r.randint(8, 20)}.get(c.segment, e.r.randint(1, 6))
    for _ in range(n):
        inst = e.pick_instrument(c)
        qty = int(budget / n / inst.last_close / 100) * 100
        if qty <= 0:
            continue
        cost = inst.last_close * math.exp(e.rng.normal(0, 0.15))
        e.add_position(acc, inst, qty, cost, when, "DEPOSIT", "OPENING_BALANCE")
