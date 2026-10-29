"""Event-driven simulation of the brokerage.

Everything that happens is an event on a time-ordered heap. Backfill drains the heap as fast as
possible; live mode drains it in step with a (sped-up) wall clock. Both write through the same sink.
"""
from __future__ import annotations

import heapq
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np
from faker import Faker

from . import refdata, textgen, world
from .calendar_vn import (N_MINUTES, VN_TZ, add_trading_days, is_trading_day, minute_index, minute_time,
                          next_trading_day, trading_days, vn_time)
from .config import DIVIDEND_TAX_RATE, SELLING_TAX_RATE, SETTLEMENT_DAYS, Preset
from .groundtruth import GroundTruth
from .market import intraday_path, price_limits, round_to_tick, tick_size
from .model import Account, Customer, Instrument, Loan, MarginCall, Order, Position, Settlement

UTC = timezone.utc
SEC = timedelta(seconds=1)


class Engine:
    def __init__(self, preset: Preset, seed: int, sink, kafka=None):
        self.preset = preset
        self.seed = seed
        self.sink = sink
        self.kafka = kafka
        self.live = False
        self.rng = np.random.default_rng(seed)
        self.r = random.Random(seed)
        self._init_fakers()
        self.gt = GroundTruth()
        self.ids: dict[str, int] = defaultdict(int)
        self.heap: list = []
        self.seq = itertools.count()
        self.now: datetime = vn_time(preset.start, 0)
        self.day: date = preset.start
        self.last_day_scheduled: date | None = None
        # world
        self.branches: list[int] = []
        self.employees: dict[str, list[int]] = {}
        self.fee: dict[str, tuple[int, float]] = {}
        self.loan_products: dict[int, dict] = {}
        self.loan_product_by_code: dict[str, int] = {}
        self.aml_severity: dict[str, str] = {}
        self.instruments: dict[int, Instrument] = {}
        self.by_sector: dict[str, list[Instrument]] = defaultdict(list)
        self.funds: dict[int, dict] = {}
        self.warrants: dict[int, dict] = {}
        self.customers: list[Customer] = []
        self.customer_by_id: dict[int, Customer] = {}
        self.accounts: dict[int, Account] = {}
        self.positions: dict[tuple[int, int], Position] = {}
        self.acc_holdings: dict[int, set[int]] = defaultdict(set)
        self.kyc: dict[int, dict] = {}
        self.used_symbols: set[str] = set()
        self.used_issuer_names: set[tuple[str, str]] = set()
        self.pending_fs_disclosures: dict[date, list] = {}
        # activity state
        self.open_orders: dict[int, Order] = {}
        self.settlements: dict[date, list[Settlement]] = defaultdict(list)
        self.loans: dict[int, list[Loan]] = defaultdict(list)
        self.calls: dict[int, MarginCall] = {}
        self.ca_events: list[dict] = []
        self.tickets: dict[int, dict] = {}
        self.watch_items: dict[int, list[dict]] = defaultdict(list)
        self.market_return = 0.0
        # AML observation state
        self.deposits_today: dict[int, list[int]] = defaultdict(list)
        self.recent_deposits: list[tuple[date, int, int]] = []
        self.withdrawals_today: dict[int, int] = defaultdict(int)
        self.last_trade_day: dict[int, date] = {}
        self.device_logins: dict[str, dict[int, date]] = defaultdict(dict)
        self.devices_today: set[str] = set()
        self.fast_cancels: Counter = Counter()
        self.execs_today: dict[int, list[tuple[int, str, datetime]]] = defaultdict(list)
        self.alerted: dict[tuple, date] = {}
        self.pattern_plan: dict[date, list[tuple]] = defaultdict(list)
        self.ticket_plan: dict[date, list[tuple]] = defaultdict(list)

    # ------------------------------------------------------------ plumbing
    def _init_fakers(self) -> None:
        locales = {loc for _, loc in refdata.FOREIGN_NATIONALITIES} | {"vi_VN"}
        self.fakers = {loc: Faker(loc) for loc in locales}
        for i, f in enumerate(self.fakers.values()):
            f.seed_instance(self.seed + i)
        self.fake = self.fakers["vi_VN"]

    def __getstate__(self):
        state = self.__dict__.copy()
        for key in ("sink", "kafka", "fakers", "fake"):
            state.pop(key, None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self.sink, self.kafka = None, None
        self._init_fakers()

    def nid(self, table: str) -> int:
        self.ids[table] += 1
        return self.ids[table]

    def out(self, table: str, row: dict) -> None:
        self.sink.upsert(table, row)

    def at(self, when: datetime, fn, *args) -> None:
        heapq.heappush(self.heap, (when, next(self.seq), fn, args))

    def run_until(self, until: datetime) -> None:
        while self.heap and self.heap[0][0] <= until:
            when, _, fn, args = heapq.heappop(self.heap)
            self.now = when
            fn(*args)

    def emit(self, topic: str, key: str, value: dict) -> None:
        if self.kafka is not None:
            self.kafka.produce(topic, key=key, value=json.dumps(value, ensure_ascii=False, default=str))

    # ------------------------------------------------------------ world
    def add_instrument(self, inst: Instrument) -> None:
        self.instruments[inst.instrument_id] = inst
        if inst.tradable and inst.sector_code:
            self.by_sector[inst.sector_code].append(inst)

    def build_world(self) -> None:
        world.build_reference(self)
        world.build_products(self)
        self.tradable = [i for i in self.instruments.values() if i.tradable]
        self.tradable_weights = np.array([i.liquidity for i in self.tradable], dtype=float)
        self.tradable_weights /= self.tradable_weights.sum()
        world.build_customers(self)
        self._watchlists()
        self._schedule_corporate_actions()
        self._plan_market_correction()
        self._plan_churn()
        self._plan_patterns()
        self._customer_arrays()
        self.sink.flush()

    def pick_instrument(self, c: Customer) -> Instrument:
        if self.r.random() < 0.75:
            pool = [i for code in c.sectors for i in self.by_sector.get(code, [])]
            if pool:
                weights = [i.liquidity for i in pool]
                return self.r.choices(pool, weights)[0]
        return self.tradable[int(self.rng.choice(len(self.tradable), p=self.tradable_weights))]

    def warrant_price(self, inst_id: int, underlying_close: int, d: date) -> int:
        w = self.warrants[inst_id]
        days_left = max(1, (w["maturity"] - d).days)
        intrinsic = max(0.0, underlying_close - w["strike"]) / w["ratio"]
        time_value = underlying_close * 0.25 * math.sqrt(days_left / 365) * 0.4 / w["ratio"]
        return round_to_tick(max(10, intrinsic + time_value), "HOSE", "COVERED_WARRANT")

    def _customer_arrays(self) -> None:
        cs = self.customers
        self.c_rate = np.array([c.order_rate for c in cs])
        self.c_login = np.array([c.login_rate for c in cs])
        self.c_cash = np.array([c.cash_flow_rate for c in cs])
        self.c_opened = np.array([c.opened.toordinal() for c in cs])
        self.c_churn = np.array([c.churn_date.toordinal() if c.churn_date else 10**9 for c in cs])
        self.c_blocked = np.array([c.status in ("CLOSED", "BLOCKED") for c in cs])

    def _watchlists(self) -> None:
        for c in self.customers:
            if c.order_rate < 0.03 or c.status == "CLOSED":
                continue
            for k in range(self.r.choice([1, 1, 2])):
                wid = self.nid("oms.watchlists")
                created = vn_time(max(c.opened, self.preset.start - timedelta(days=200)), 20)
                c.watchlist_ids.append(wid)
                self.out("oms.watchlists", {"watchlist_id": wid, "customer_id": c.customer_id,
                                            "name": ["Danh mục theo dõi", "Cổ phiếu tiềm năng", "Lướt sóng"][k],
                                            "created_at": created})
                for _ in range(self.r.randint(3, 12)):
                    inst = self.pick_instrument(c)
                    if inst.instrument_id in c.watch_symbols:
                        continue
                    c.watch_symbols.append(inst.instrument_id)
                    self._watch_add(c, wid, inst, created)

    def _watch_add(self, c: Customer, wid: int, inst: Instrument, t: datetime) -> None:
        item = {"watchlist_id": wid, "instrument_id": inst.instrument_id, "symbol": inst.symbol,
                "added_at": t, "removed_at": None}
        self.watch_items[c.customer_id].append(item)
        self.out("oms.watchlist_items", item)

    def _schedule_corporate_actions(self) -> None:
        days = trading_days(self.preset.start, self.preset.end)
        if len(days) < 15:
            return
        for inst in self.tradable:
            if inst.itype != "STOCK":
                continue
            roll = self.r.random()
            if roll > 0.30:
                continue
            ca_type = "CASH_DIVIDEND" if roll < 0.24 else "STOCK_DIVIDEND"
            ex = self.r.choice(days[5:-3])
            event = {"ca_event_id": self.nid("corp_action.events"), "inst": inst, "ca_type": ca_type,
                     "announced_on": add_trading_days(ex, -10), "ex_date": ex, "record_date": add_trading_days(ex, 1),
                     "payment_date": None, "cash_per_share": None, "num": None, "den": None, "status": "ANNOUNCED"}
            if ca_type == "CASH_DIVIDEND":
                event["cash_per_share"] = self.r.choice([500, 700, 800, 1000, 1200, 1500, 2000, 2500, 3000])
                pay = event["record_date"] + timedelta(days=self.r.randint(10, 30))
                event["payment_date"] = pay if is_trading_day(pay) else next_trading_day(pay)
            else:
                event["num"], event["den"] = 100, self.r.choice([5, 10, 12, 15, 20, 25, 30])
                event["payment_date"] = add_trading_days(event["record_date"], self.r.randint(8, 20))
            self.ca_events.append(event)
            if event["announced_on"] < self.preset.start:
                self._announce_ca(event)
            else:
                self.at(vn_time(event["announced_on"], 17), self._announce_ca, event)

    def _plan_market_correction(self) -> None:
        """A sell-off of a few consecutive sessions, the main source of margin calls and force sells."""
        days = trading_days(self.preset.start, self.preset.end)
        self.correction_days: set[date] = set()
        if len(days) < 30:
            return
        start = self.r.randrange(len(days) // 5, len(days) // 2)
        chosen = days[start:start + self.r.randint(3, 5)]
        self.correction_days = set(chosen)
        self.gt.pattern(0, "MARKET_CORRECTION", [], chosen, "Market return -2.5% to -5.5% per session")

    def _plan_churn(self) -> None:
        days = trading_days(self.preset.start, self.preset.end)
        for c in self.customers:
            if c.segment in ("ACTIVE", "PASSIVE", "HNW") and c.status == "ACTIVE" and self.r.random() < 0.12:
                c.churn_date = self.r.choice(days[len(days) // 5: -3])
                if self.r.random() < 0.35:
                    before = add_trading_days(c.churn_date, -self.r.randint(1, 10))
                    self.ticket_plan[before].append((c, "COMPLAINT"))
                if self.r.random() < 0.6:
                    self.pattern_plan[add_trading_days(c.churn_date, self.r.randint(0, 3))].append(("CHURN_WITHDRAW", c))

    def _plan_patterns(self) -> None:
        days = trading_days(self.preset.start, self.preset.end)
        pool = [c for c in self.customers if c.ctype == "INDIVIDUAL" and c.status == "ACTIVE"
                and c.churn_date is None and c.opened < self.preset.start]
        self.r.shuffle(pool)
        n = max(1, len(self.customers) // 1000)
        pattern_id = itertools.count(1)

        def take(k):
            chosen = [pool.pop() for _ in range(min(k, len(pool)))]
            return chosen

        for c in take(n):
            c.fraud_pattern, c.order_rate = "STRUCTURING", 0.05
            chosen = sorted(self.r.sample(days[1:], min(3, len(days) - 1)))
            for k, d in enumerate(chosen):
                self.pattern_plan[d].append(("STRUCTURING", c, 2 if k == 0 else self.r.randint(3, 5)))
            self.gt.pattern(next(pattern_id), "STRUCTURING", [c.customer_id], chosen,
                            "First day uses only 2 deposits and evades the >=3 rule")
        for c in take(n):
            c.fraud_pattern, c.order_rate = "RAPID_IN_OUT", 0.02
            chosen = sorted(self.r.sample(days[1:-2], min(2, len(days) - 3)))
            for d in chosen:
                self.pattern_plan[d].append(("RAPID_IN", c))
            self.gt.pattern(next(pattern_id), "RAPID_IN_OUT", [c.customer_id], chosen, "Withdrawal on the next trading day")
        for c in take(n):
            c.fraud_pattern = "SPOOFING"
            chosen = sorted(self.r.sample(days[1:], min(3, len(days) - 1)))
            for d in chosen:
                self.pattern_plan[d].append(("SPOOFING", c))
            self.gt.pattern(next(pattern_id), "SPOOFING", [c.customer_id], chosen, "25-40 orders cancelled within 1-4.5s")
            self._fund(c, 20_000_000_000)
        for g in range(max(1, len(self.customers) // 2500)):
            ring = take(self.r.randint(4, 6))
            if len(ring) < 2:
                break
            device, ip = f"dev-{self.r.getrandbits(48):012x}", self.fake.ipv4_public()
            inst = max(self.tradable[:30], key=lambda i: i.liquidity * self.r.random())
            for c in ring:
                c.fraud_pattern, c.fraud_group = "WASH_TRADE_RING", g + 1
                c.devices.append(device)
                c.ips.append(ip)
                acc = self.accounts[c.accounts["CASH"]]
                self._fund(c, 5_000_000_000)
                self.add_position(acc, inst, 30_000, inst.last_close, vn_time(self.preset.start - timedelta(days=1), 16),
                                  "DEPOSIT", "OPENING_BALANCE")
            chosen = sorted(self.r.sample(days[1:], min(4, len(days) - 1)))
            for d in chosen:
                self.pattern_plan[d].append(("WASH_TRADE", ring, inst))
            self.gt.pattern(next(pattern_id), "WASH_TRADE_RING", [c.customer_id for c in ring], chosen,
                            f"Shared device {device}, wash trades in {inst.symbol}")

    def _fund(self, c: Customer, amount: int) -> None:
        acc = self.accounts[c.accounts["CASH"]]
        when = vn_time(self.preset.start - timedelta(days=1), 16, 30)
        acc.available += amount
        self.journal(acc, "ADJUSTMENT", amount, when, self.preset.start - timedelta(days=1), "OPENING_BALANCE", None,
                     "SYSTEM", "Số dư đầu kỳ chuyển sang hệ thống mới")
        self.touch_cash(acc, when)

    # ------------------------------------------------------------ rows
    def account_row(self, a: Account, t: datetime) -> dict:
        return {"account_id": a.account_id, "account_no": a.account_no, "customer_id": a.customer_id,
                "account_type": a.atype, "status": a.status, "fee_schedule_id": a.fee_schedule_id,
                "opened_at": a.opened_at, "closed_at": None, "created_at": a.opened_at, "updated_at": t,
                "version": 1}

    def cash_row(self, a: Account, t: datetime) -> dict:
        return {"account_id": a.account_id, "available_amount": a.available, "blocked_amount": a.blocked,
                "receivable_amount": a.receivable, "payable_amount": a.payable, "updated_at": t, "version": a.version}

    def touch_cash(self, a: Account, t: datetime) -> None:
        a.version += 1
        self.out("ledger.cash_balances", self.cash_row(a, t))

    def touch_pos(self, acc_id: int, inst_id: int, t: datetime) -> None:
        p = self.positions[(acc_id, inst_id)]
        p.version += 1
        self.out("custody.positions", {
            "account_id": acc_id, "instrument_id": inst_id, "total_quantity": p.total,
            "available_quantity": p.available, "receiving_quantity": p.receiving, "blocked_quantity": p.blocked,
            "pledged_quantity": p.pledged, "average_cost": round(p.avg_cost, 4), "updated_at": t, "version": p.version})

    def pos(self, acc_id: int, inst_id: int) -> Position:
        key = (acc_id, inst_id)
        if key not in self.positions:
            self.positions[key] = Position(version=0)
        return self.positions[key]

    def journal(self, acc: Account, txn_type: str, amount: int, t: datetime, value_date: date, ref_type: str | None,
                ref_id, channel: str = "SYSTEM", description: str | None = None, bank_account_id: int | None = None) -> None:
        if amount == 0:
            return
        acc.ledger_balance += amount
        self.out("ledger.cash_transactions", {
            "cash_txn_id": self.nid("ledger.cash_transactions"), "account_id": acc.account_id, "txn_type": txn_type,
            "amount": amount, "balance_after": acc.ledger_balance, "value_date": value_date, "reference_type": ref_type,
            "reference_id": None if ref_id is None else str(ref_id), "bank_account_id": bank_account_id,
            "channel": channel, "description": description, "created_at": t})

    def movement(self, acc_id: int, inst_id: int, mtype: str, qty: int, t: datetime, settle: date,
                 ref_type: str | None = None, ref_id=None, trade_date: date | None = None) -> None:
        self.out("custody.position_movements", {
            "movement_id": self.nid("custody.position_movements"), "account_id": acc_id, "instrument_id": inst_id,
            "movement_type": mtype, "quantity": qty, "reference_type": ref_type,
            "reference_id": None if ref_id is None else str(ref_id), "trade_date": trade_date, "settle_date": settle,
            "created_at": t})

    def add_position(self, acc: Account, inst: Instrument, qty: int, cost: float, t: datetime, mtype: str,
                     ref_type: str) -> None:
        p = self.pos(acc.account_id, inst.instrument_id)
        p.avg_cost = (p.avg_cost * p.total + cost * qty) / (p.total + qty)
        p.total += qty
        p.available += qty
        self.acc_holdings[acc.account_id].add(inst.instrument_id)
        self.movement(acc.account_id, inst.instrument_id, mtype, qty, t, t.astimezone(VN_TZ).date(), ref_type)
        self.touch_pos(acc.account_id, inst.instrument_id, t)

    # ------------------------------------------------------------ day cycle
    def schedule_day(self, d: date) -> None:
        self.last_day_scheduled = d
        self.at(vn_time(d, 7, 0), self.start_day, d)

    def start_day(self, d: date) -> None:
        self.day = d
        r, rng = self.r, self.rng
        mret = rng.normal(0.0004, 0.011)
        if d in self.correction_days:
            mret = -r.uniform(0.025, 0.055)
        elif r.random() < 0.025:
            mret -= r.uniform(0.025, 0.05)
        elif r.random() < 0.02:
            mret += r.uniform(0.02, 0.035)
        self.market_return = mret
        for ev in self.ca_events:
            if ev["ex_date"] == d:
                inst = ev["inst"]
                if ev["ca_type"] == "CASH_DIVIDEND":
                    inst.last_close = max(100, inst.last_close - ev["cash_per_share"])
                else:
                    inst.last_close = int(inst.last_close * ev["num"] / (ev["num"] + ev["den"]))
        movers = []
        for inst in self.tradable:
            inst.news_shock = 0.0
            if inst.itype == "STOCK" and r.random() < 0.03:
                sentiment = r.choices(["POSITIVE", "NEGATIVE", "NEUTRAL"], [0.4, 0.35, 0.25])[0]
                inst.news_shock = {"POSITIVE": r.uniform(0.01, 0.04), "NEGATIVE": -r.uniform(0.01, 0.04),
                                   "NEUTRAL": 0.0}[sentiment]
                self.at(vn_time(d, 7, r.randint(5, 50)), self._news, inst, sentiment, inst.news_shock)
            inst.ref = round_to_tick(inst.last_close, inst.exchange, inst.itype)
            inst.floor, inst.ceiling = price_limits(inst.ref, inst.band, inst.exchange, inst.itype)
            ret = inst.mu + inst.beta * mret + rng.normal(0, inst.sigma) + inst.news_shock
            inst.open, inst.path, inst.close = intraday_path(rng, inst.ref, inst.floor, inst.ceiling, ret, inst.sigma,
                                                             inst.exchange, inst.itype)
            inst.client_volume = inst.client_value = 0
            movers.append(inst)
        self.at(vn_time(d, 8, 0), self._corporate_actions, d)
        self.at(vn_time(d, 8, 30), self.settle, d)
        if d.month != add_trading_days(d, -1).month:
            self.at(vn_time(d, 8, 15), self._charge_interest, d)
        for past in [k for k in self.pending_fs_disclosures if k < d]:
            for inst, row in self.pending_fs_disclosures.pop(past):
                self._fs_disclosure(inst, row, vn_time(row["published_on"], 18))
        for inst, row in self.pending_fs_disclosures.pop(d, []):
            self.at(vn_time(d, 18, r.randint(0, 59)), self._fs_disclosure, inst, row)
        self._customer_activity(d)
        for item in self.pattern_plan.pop(d, []):
            self._run_pattern(d, item)
        self._crm_day(d)
        if self.live:
            for i in range(N_MINUTES):
                self.at(minute_time(d, i, 59.9), self._ticks, i)
        self.at(vn_time(d, 15, 0), self.end_of_session, d)
        self.at(vn_time(d, 23, 0), self._aml_rules, d)
        self.at(vn_time(d, 23, 59, 59), self.end_of_day, d)

    def end_of_day(self, d: date) -> None:
        self.sink.flush()
        nxt = next_trading_day(d)
        if self.live or nxt <= self.preset.end:
            self.schedule_day(nxt)
        self.deposits_today.clear()
        self.withdrawals_today.clear()
        self.fast_cancels.clear()
        self.execs_today.clear()
        self.devices_today.clear()

    # ------------------------------------------------------------ customer activity
    def _customer_activity(self, d: date) -> None:
        o = d.toordinal()
        active = (self.c_opened <= o) & ~self.c_blocked
        factor = np.where(o >= self.c_churn, 0.02, 1.0) * active
        orders = self.rng.poisson(self.c_rate * factor)
        logins = self.rng.poisson(self.c_login * factor)
        flows = self.rng.poisson(self.c_cash * factor)
        for idx in np.flatnonzero(orders + logins + flows):
            c = self.customers[idx]
            times = sorted(self._order_time(d) for _ in range(orders[idx]))
            if times:
                self.at(times[0] - timedelta(minutes=self.r.uniform(1, 20)), self.login, c)
            for t in times:
                self.at(t, self.random_order, c)
            for _ in range(logins[idx]):
                self.at(vn_time(d, self.r.randint(7, 21), self.r.randint(0, 59), self.r.uniform(0, 59)), self.login, c)
            for _ in range(flows[idx]):
                self.at(vn_time(d, self.r.randint(8, 16), self.r.randint(0, 59), self.r.uniform(0, 59)), self._cash_flow, c)

    def _order_time(self, d: date) -> datetime:
        u = self.r.random()
        if u < 0.12:
            return vn_time(d, 9, 0, self.r.uniform(0, 900))
        if u < 0.40:
            return vn_time(d, 9, 15, self.r.uniform(0, 3600))
        if u < 0.70:
            return minute_time(d, self.r.randrange(N_MINUTES), self.r.uniform(0, 59.9))
        if u < 0.88:
            return vn_time(d, 13, 45, self.r.uniform(0, 2700))
        return vn_time(d, 14, 30, self.r.uniform(0, 899))

    def login(self, c: Customer, device: str | None = None) -> int | None:
        t = self.now
        if device is None:
            device = c.devices[-1] if c.fraud_group and self.r.random() < 0.8 else self.r.choice(c.devices)
        ip = c.ips[c.devices.index(device)] if device in c.devices else c.ips[0]
        result = self.r.choices(["SUCCESS", "WRONG_PASSWORD", "WRONG_OTP", "LOCKED"], [0.95, 0.03, 0.017, 0.003])[0]
        sid = self.nid("oms.client_sessions")
        channel = "API" if c.segment == "INSTITUTION" and self.r.random() < 0.5 else self.r.choice(["MOBILE", "MOBILE", "WEB"])
        self.out("oms.client_sessions", {
            "session_id": sid, "customer_id": c.customer_id, "channel": channel, "device_id": device, "ip_address": ip,
            "user_agent": {"MOBILE": "ZSCTrade/5.2 (Android 14)", "WEB": "Mozilla/5.0 (Windows NT 10.0) Chrome/126.0",
                           "API": "zsc-openapi-client/1.4"}[channel],
            "login_result": result, "login_at": t,
            "logout_at": t + timedelta(minutes=1 + self.r.expovariate(1 / 25)) if result == "SUCCESS" else None})
        if result != "SUCCESS":
            if result != "LOCKED":
                self.at(t + timedelta(seconds=self.r.uniform(20, 90)), self.login, c, device)
            return None
        self.device_logins[device][c.customer_id] = self.day
        self.devices_today.add(device)
        if self.live and c.watch_symbols:
            for inst_id in self.r.sample(c.watch_symbols, min(3, len(c.watch_symbols))):
                self.emit("app.clickstream", str(c.customer_id), {
                    "event_type": "VIEW_SYMBOL", "customer_id": c.customer_id, "session_id": sid,
                    "symbol": self.instruments[inst_id].symbol, "event_time": t.isoformat()})
        return sid

    def _cash_flow(self, c: Customer) -> None:
        accs = [self.accounts[a] for a in c.accounts.values()]
        acc = accs[-1] if len(accs) > 1 and self.r.random() < 0.6 else accs[0]
        if self.r.random() < 0.6:
            amount = max(1_000_000, int(round(c.wealth * self.r.uniform(0.02, 0.2), -6)))
            self.deposit(acc, amount, "BANK_TRANSFER")
        else:
            amount = int(round(acc.available * self.r.uniform(0.1, 0.6), -6))
            if amount >= 1_000_000:
                self.withdraw(acc, amount, self.r.choice(["MOBILE", "WEB"]))

    def deposit(self, acc: Account, amount: int, channel: str = "BANK_TRANSFER", description: str | None = None) -> None:
        t, c = self.now, self.customer_by_id[acc.customer_id]
        acc.available += amount
        self.journal(acc, "DEPOSIT", amount, t, self.day, "BANK_TRANSFER", None, channel,
                     description or f"Nộp tiền vào tài khoản {acc.account_no}", c.bank_account_id)
        self.touch_cash(acc, t)
        self.deposits_today[c.customer_id].append(amount)
        self.recent_deposits.append((self.day, c.customer_id, amount))
        if acc.open_call_id and acc.open_call_id in self.calls:
            self.calls[acc.open_call_id].deposited = True

    def withdraw(self, acc: Account, amount: int, channel: str) -> None:
        amount = min(amount, acc.available)
        if amount <= 0:
            return
        t, c = self.now, self.customer_by_id[acc.customer_id]
        acc.available -= amount
        self.journal(acc, "WITHDRAWAL", -amount, t, self.day, "BANK_TRANSFER", None, channel,
                     "Rút tiền về tài khoản ngân hàng", c.bank_account_id)
        self.touch_cash(acc, t)
        self.withdrawals_today[c.customer_id] += amount

    # ------------------------------------------------------------ orders
    def market_price(self, inst: Instrument, t: datetime) -> int:
        local = t.astimezone(VN_TZ)
        if (local.hour, local.minute) < (9, 15):
            return inst.ref
        return int(inst.path[minute_index(self.day, t)])

    def margin_capacity(self, acc: Account, inst: Instrument) -> int:
        if acc.atype != "MARGIN" or inst.margin_ratio <= 0:
            return 0
        product = self.loan_products[acc.loan_product_id]
        debt = sum(l.outstanding for l in self.loans[acc.account_id]) + acc.margin_pending + acc.margin_reserved
        collateral = sum(self.positions[(acc.account_id, i)].total * self.instruments[i].last_close
                         * self.instruments[i].margin_ratio for i in self.acc_holdings[acc.account_id])
        return max(0, int(min(product["max_loan"], collateral + acc.available) - debt))

    def _order_type(self, inst: Instrument, t: datetime) -> str:
        local = t.astimezone(VN_TZ)
        hm, u = (local.hour, local.minute), self.r.random()
        if inst.exchange == "UPCOM":
            return "LO"
        if hm < (9, 15):
            return "ATO" if inst.exchange == "HOSE" and u < 0.15 else "LO"
        if hm >= (14, 30):
            return "ATC" if u < 0.25 else "LO"
        if inst.exchange == "HOSE":
            return "MP" if u < 0.08 else "LO"
        return "MTL" if u < 0.04 else "MAK" if u < 0.06 else "MOK" if u < 0.08 else "LO"

    def random_order(self, c: Customer) -> None:
        if c.status in ("CLOSED", "BLOCKED"):
            return
        t, r = self.now, self.r
        acc = self.accounts[c.accounts["MARGIN"] if "MARGIN" in c.accounts and r.random() < 0.7 else c.accounts["CASH"]]
        sellable = [i for i in self.acc_holdings[acc.account_id]
                    if self.positions[(acc.account_id, i)].available >= 100 and self.instruments[i].tradable]
        side = "SELL" if sellable and r.random() < 0.45 else "BUY"
        if side == "SELL":
            inst = self.instruments[r.choice(sellable)]
            avail = self.positions[(acc.account_id, inst.instrument_id)].available
            qty = max(100, int(avail * r.uniform(0.3, 1.0) / 100) * 100)
            if r.random() < 0.02:
                qty = avail + 1_000
        else:
            u = r.random()
            if u < 0.35 and c.watch_symbols:
                inst = self.instruments[r.choice(c.watch_symbols)]
            elif u < 0.55 and sellable:
                inst = self.instruments[r.choice(sellable)]
            else:
                inst = self.pick_instrument(c)
            if not inst.tradable:
                return
        otype = self._order_type(inst, t)
        market = self.market_price(inst, t)
        tick = tick_size(inst.exchange, inst.itype, market)
        price = None
        if otype == "LO":
            if r.random() < 0.35:
                k = r.randint(0, 2) if side == "BUY" else -r.randint(0, 2)
            else:
                k = -int(r.expovariate(0.6)) if side == "BUY" else int(r.expovariate(0.6))
            price = min(inst.ceiling, max(inst.floor, market + k * tick))
            if r.random() < 0.004:
                price = inst.ceiling + tick if side == "BUY" else max(tick, inst.floor - tick)
        if side == "BUY":
            buying_power = acc.available + self.margin_capacity(acc, inst)
            if acc.atype == "MARGIN" and c.risk_appetite == "AGGRESSIVE":
                fraction = (0.6, 1.0)   # aggressive margin users run close to full leverage
            else:
                fraction = {"DAY_TRADER": (0.2, 0.7), "HNW": (0.05, 0.3), "INSTITUTION": (0.02, 0.15)}.get(c.segment, (0.1, 0.5))
            spend = buying_power * r.uniform(*fraction)
            qty = int(spend / ((price or inst.ceiling) * (1 + acc.fee_pct)) / 100) * 100
            if qty < 100:
                if r.random() > 0.3:
                    return
                qty = 100
        employee = c.rm_employee_id if c.rm_employee_id and c.segment in ("HNW", "INSTITUTION", "ACTIVE") and r.random() < 0.4 else None
        channel = "BROKER" if employee else ("API" if c.segment in ("INSTITUTION", "DAY_TRADER") and r.random() < 0.3
                                             else r.choices(["MOBILE", "WEB"], [0.7, 0.3])[0])
        o = self.submit_order(c, acc, inst, side, otype, price, qty, channel, employee)
        if o and o.is_open and otype == "LO":
            if r.random() < 0.10:
                self.at(t + timedelta(minutes=r.expovariate(1 / 25)), self.client_cancel, o)
            elif r.random() < 0.045:
                self.at(t + timedelta(minutes=r.expovariate(1 / 15)), self.modify, o)

    def submit_order(self, c: Customer, acc: Account, inst: Instrument, side: str, otype: str, price: int | None,
                     qty: int, channel: str, employee: int | None, source: str = "CLIENT") -> Order:
        t = self.now
        oid = self.nid("oms.orders")
        o = Order(oid, f"{self.day:%Y%m%d}-{oid:09d}", acc, c, inst, side, otype, price, qty, channel, employee,
                  self.day, t, source=source, updated_at=t)
        self.emit_order(o, t)
        self.order_event(o, "SUBMITTED", t, "BROKER" if channel == "BROKER" and source == "CLIENT" else source)
        reason = None
        if price is not None and not (inst.floor <= price <= inst.ceiling):
            reason = "PRICE_OUT_OF_BAND"
        elif side == "BUY":
            need = math.ceil(qty * (price or inst.ceiling) * (1 + acc.fee_pct))
            capacity = self.margin_capacity(acc, inst)
            if c.is_foreign and self.r.random() < 0.03:
                reason = "FOREIGN_ROOM_EXCEEDED"
            elif acc.available >= need:
                o.cash_blocked = need
            elif acc.available + capacity >= need:
                o.cash_blocked, o.margin_reserved, o.is_margin = acc.available, need - acc.available, True
            else:
                reason = "INSUFFICIENT_BUYING_POWER"
        else:
            if self.positions.get((acc.account_id, inst.instrument_id), Position()).available < qty:
                reason = "INSUFFICIENT_SECURITIES"
        if reason:
            o.status, o.reject_reason = "REJECTED", reason
            self.order_event(o, "REJECTED", t + timedelta(milliseconds=40), "SYSTEM", reason=reason)
            self.emit_order(o, t + timedelta(milliseconds=40))
            return o
        if side == "BUY":
            acc.available -= o.cash_blocked
            acc.blocked += o.cash_blocked
            acc.margin_reserved += o.margin_reserved
            self.touch_cash(acc, t)
        else:
            p = self.positions[(acc.account_id, inst.instrument_id)]
            p.available -= qty
            p.blocked += qty
            self.touch_pos(acc.account_id, inst.instrument_id, t)
        o.status = "NEW"
        self.open_orders[oid] = o
        self.order_event(o, "ACCEPTED", t + timedelta(milliseconds=60), "EXCHANGE")
        self.emit_order(o, t + timedelta(milliseconds=60))
        self.plan_fills(o, t)
        return o

    def emit_order(self, o: Order, t: datetime) -> None:
        o.version += 1
        o.updated_at = t
        self.out("oms.orders", {
            "order_id": o.order_id, "order_no": o.order_no, "account_id": o.account.account_id,
            "customer_id": o.customer.customer_id, "instrument_id": o.inst.instrument_id, "symbol": o.inst.symbol,
            "exchange_code": o.inst.exchange, "side": o.side, "order_type": o.otype, "price": o.price,
            "quantity": o.qty, "filled_quantity": o.filled,
            "average_fill_price": round(o.fill_value / o.filled, 4) if o.filled else None, "status": o.status,
            "is_margin": o.is_margin, "channel": o.channel, "placed_by_employee_id": o.employee_id,
            "trade_date": o.trade_date, "reject_reason": o.reject_reason, "created_at": o.created_at,
            "updated_at": t, "version": o.version})

    def order_event(self, o: Order, event_type: str, t: datetime, source: str, old_price=None, new_price=None,
                    old_qty=None, new_qty=None, reason=None) -> None:
        self.out("oms.order_events", {
            "order_event_id": self.nid("oms.order_events"), "order_id": o.order_id, "event_type": event_type,
            "old_price": old_price, "new_price": new_price, "old_quantity": old_qty, "new_quantity": new_qty,
            "reason": reason, "source": source, "event_time": t})

    def _crosses(self, o: Order, px: int) -> bool:
        if o.price is None:
            return True
        return px <= o.price if o.side == "BUY" else px >= o.price

    def plan_fills(self, o: Order, t: datetime) -> None:
        inst, d, r = o.inst, self.day, self.r
        path, rem = inst.path, o.remaining
        local = t.astimezone(VN_TZ)
        hm = (local.hour, local.minute)
        epoch = o.epoch

        def lots(q):
            return max(100, int(q / 100) * 100)

        if o.otype == "ATC" or hm >= (14, 30):
            if self._crosses(o, inst.close) and (o.otype == "ATC" or r.random() < 0.6):
                self.at(vn_time(d, 14, 45, r.uniform(0, 2)), self.on_fill, o, epoch, rem, inst.close)
            return
        start = minute_index(d, t)
        if hm < (9, 15):
            if self._crosses(o, inst.open):
                q = rem if r.random() < 0.85 else lots(rem * r.uniform(0.2, 0.9))
                self.at(vn_time(d, 9, 15, r.uniform(0, 2)), self.on_fill, o, epoch, min(q, rem), inst.open)
                rem -= min(q, rem)
            if o.otype == "ATO":
                self.at(vn_time(d, 9, 15, 3), self.expire, o, epoch, "ATO_UNMATCHED")
                return
            start = 0
        if rem <= 0:
            return
        if o.otype in ("MP", "MTL", "MAK", "MOK"):
            px = int(path[start])
            tick = tick_size(inst.exchange, inst.itype, px)
            px = min(inst.ceiling, px + tick) if o.side == "BUY" else max(inst.floor, px - tick)
            when = t + timedelta(seconds=r.uniform(0.2, 1.5))
            if o.otype == "MOK" and r.random() < 0.1:
                self.at(when, self.expire, o, epoch, "MOK_NOT_FULLY_MATCHED")
                return
            q = lots(rem * r.uniform(0.5, 1)) if o.otype == "MAK" else rem
            self.at(when, self.on_fill, o, epoch, min(q, rem), px)
            if o.otype == "MAK" and q < rem:
                self.at(when + timedelta(milliseconds=10), self.expire, o, epoch, "MAK_REMAINDER_CANCELLED")
            return
        seg = path[start:]
        hits = seg <= o.price if o.side == "BUY" else seg >= o.price
        if hits.any():
            first = start + int(np.argmax(hits))
            marketable = first == start and hm >= (9, 15)
            total = rem if r.random() < 0.8 else lots(rem * r.uniform(0.15, 0.9))
            total = min(total, rem)
            chunks = 1 if r.random() < 0.65 else r.randint(2, 3)
            minute = first
            for k in range(chunks):
                q = total if k == chunks - 1 else lots(total / chunks)
                q = min(q, total)
                if q <= 0:
                    break
                total -= q
                if marketable:
                    px = int(path[minute])
                    px = min(px, o.price) if o.side == "BUY" else max(px, o.price)
                else:
                    px = o.price
                when = (max(t + timedelta(seconds=r.uniform(0.2, 2.0)), minute_time(d, minute))
                        if (k == 0 and marketable) else max(t + SEC, minute_time(d, minute, r.uniform(0, 59))))
                self.at(when, self.on_fill, o, epoch, q, px)
                minute = min(N_MINUTES - 1, minute + r.randint(1, 10))
        if self._crosses(o, inst.close) and r.random() < 0.5:
            self.at(vn_time(d, 14, 45, r.uniform(0, 2)), self.on_fill, o, epoch, rem, inst.close)

    def on_fill(self, o: Order, epoch: int, qty: int, px: int) -> None:
        if o.epoch != epoch or not o.is_open:
            return
        qty = min(qty, o.remaining)
        if qty <= 0:
            return
        t, acc, inst, c = self.now, o.account, o.inst, o.customer
        value = qty * px
        fee = round(value * acc.fee_pct)
        tax = round(value * SELLING_TAX_RATE) if o.side == "SELL" else 0
        cash_part = loan_part = 0
        p = self.pos(acc.account_id, inst.instrument_id)
        if o.side == "BUY":
            cost = value + fee
            from_block = min(cost, o.cash_blocked)
            rest = cost - from_block
            from_margin = min(rest, o.margin_reserved)
            rest -= from_margin
            from_avail = min(rest, acc.available)
            rest -= from_avail
            o.cash_blocked -= from_block
            o.margin_reserved -= from_margin
            acc.blocked -= from_block
            acc.available -= from_avail
            acc.margin_reserved -= from_margin
            cash_part = from_block + from_avail
            loan_part = from_margin + rest
            acc.payable += cash_part
            acc.margin_pending += loan_part
            p.avg_cost = (p.avg_cost * p.total + cost) / (p.total + qty)
            p.total += qty
            p.receiving += qty
            self.acc_holdings[acc.account_id].add(inst.instrument_id)
        else:
            p.blocked -= qty
            p.total -= qty
            acc.receivable += value - fee - tax
            call = self.calls.get(acc.open_call_id) if acc.open_call_id else None
            if call:
                call.sold = True
        o.filled += qty
        o.fill_value += value
        eid = self.nid("oms.executions")
        self.out("oms.executions", {
            "execution_id": eid, "exchange_exec_no": f"{inst.exchange[0]}{self.day:%m%d}{eid:010d}", "order_id": o.order_id,
            "account_id": acc.account_id, "instrument_id": inst.instrument_id, "symbol": inst.symbol, "side": o.side,
            "matched_quantity": qty, "matched_price": px, "matched_value": value, "fee_amount": fee,
            "tax_amount": tax, "trade_date": self.day, "matched_at": t})
        settle_date = add_trading_days(self.day, SETTLEMENT_DAYS)
        s = Settlement(self.nid("custody.settlement_instructions"), eid, acc, inst, o.side, qty, px, value, fee, tax,
                       self.day, settle_date, cash_part, loan_part, t)
        self.settlements[settle_date].append(s)
        self._settlement_row(s, "PENDING", None, t)
        inst.client_volume += qty
        inst.client_value += value
        self.execs_today[c.customer_id].append((inst.instrument_id, o.side, t))
        self.last_trade_day[c.customer_id] = self.day
        if o.remaining == 0:
            o.status = "FILLED"
            self.order_event(o, "FILLED", t, "EXCHANGE", new_qty=qty, new_price=px)
            self._release(o, t)
        else:
            o.status = "PARTIALLY_FILLED"
            self.order_event(o, "PARTIALLY_FILLED", t, "EXCHANGE", new_qty=qty, new_price=px)
        self.emit_order(o, t)
        self.touch_cash(acc, t)
        self.touch_pos(acc.account_id, inst.instrument_id, t)

    def _release(self, o: Order, t: datetime) -> None:
        """Return whatever the order still holds (cash, margin reservation or shares) and close it."""
        acc = o.account
        if o.side == "BUY":
            acc.blocked -= o.cash_blocked
            acc.available += o.cash_blocked
            acc.margin_reserved -= o.margin_reserved
            o.cash_blocked = o.margin_reserved = 0
        elif o.remaining > 0:
            p = self.positions[(acc.account_id, o.inst.instrument_id)]
            p.blocked -= o.remaining
            p.available += o.remaining
            self.touch_pos(acc.account_id, o.inst.instrument_id, t)
        self.touch_cash(acc, t)
        self.open_orders.pop(o.order_id, None)

    def client_cancel(self, o: Order) -> None:
        if not o.is_open:
            return
        t = self.now
        self.order_event(o, "CANCEL_REQUESTED", t, "BROKER" if o.channel == "BROKER" else "CLIENT")
        o.status = "CANCELLED"
        self.order_event(o, "CANCELLED", t + timedelta(milliseconds=150), "EXCHANGE")
        self._release(o, t)
        self.emit_order(o, t + timedelta(milliseconds=150))
        if (t - o.created_at).total_seconds() <= 5:
            self.fast_cancels[o.account.account_id] += 1

    def expire(self, o: Order, epoch: int | None, reason: str) -> None:
        if not o.is_open or (epoch is not None and epoch != o.epoch):
            return
        t = self.now
        o.status = "CANCELLED" if reason.startswith(("MOK", "MAK")) else "EXPIRED"
        self.order_event(o, o.status, t, "EXCHANGE" if o.status == "CANCELLED" else "SYSTEM", reason=reason)
        self._release(o, t)
        self.emit_order(o, t)

    def modify(self, o: Order) -> None:
        if not o.is_open or o.is_margin:
            return
        t, acc, inst = self.now, o.account, o.inst
        market = self.market_price(inst, t)
        new_price = min(inst.ceiling, max(inst.floor, market))
        if new_price == o.price:
            return
        if o.side == "BUY":
            need = math.ceil(o.remaining * new_price * (1 + acc.fee_pct))
            extra = need - o.cash_blocked
            if extra > acc.available:
                return
            acc.available -= extra
            acc.blocked += extra
            o.cash_blocked += extra
            self.touch_cash(acc, t)
        self.order_event(o, "MODIFIED", t, "BROKER" if o.channel == "BROKER" else "CLIENT",
                         old_price=o.price, new_price=new_price, old_qty=o.qty, new_qty=o.qty)
        o.price = new_price
        o.epoch += 1
        self.emit_order(o, t)
        self.plan_fills(o, t)

    # ------------------------------------------------------------ settlement & margin
    def _settlement_row(self, s: Settlement, status: str, settled_at: datetime | None, t: datetime) -> None:
        net = s.gross + s.fee if s.side == "BUY" else s.gross - s.fee - s.tax
        self.out("custody.settlement_instructions", {
            "settlement_id": s.settlement_id, "execution_id": s.execution_id, "account_id": s.account.account_id,
            "instrument_id": s.inst.instrument_id, "side": s.side, "quantity": s.qty, "price": s.price,
            "gross_amount": s.gross, "fee_amount": s.fee, "tax_amount": s.tax, "net_amount": net,
            "trade_date": s.trade_date, "settle_date": s.settle_date, "status": status, "settled_at": settled_at,
            "created_at": s.created_at, "updated_at": t})

    def settle(self, d: date) -> None:
        t = self.now
        touched = set()
        for s in self.settlements.pop(d, []):
            acc, inst = s.account, s.inst
            p = self.positions[(acc.account_id, inst.instrument_id)]
            if s.side == "BUY":
                acc.payable -= s.cash_part
                if s.loan_part > 0:
                    loan = self._new_loan(acc, s.loan_part, t)
                    acc.margin_pending -= s.loan_part
                    self.journal(acc, "LOAN_DISBURSEMENT", s.loan_part, t, d, "LOAN", loan.loan_id,
                                 description=f"Giải ngân margin cho lệnh mua {inst.symbol}")
                self.journal(acc, "BUY_SETTLEMENT", -s.gross, t, d, "SETTLEMENT", s.settlement_id,
                             description=f"Thanh toán mua {s.qty} {inst.symbol}")
                self.journal(acc, "TRADING_FEE", -s.fee, t, d, "SETTLEMENT", s.settlement_id)
                p.receiving -= s.qty
                p.available += s.qty
                self.movement(acc.account_id, inst.instrument_id, "BUY_SETTLED", s.qty, t, d, "SETTLEMENT",
                              s.settlement_id, s.trade_date)
            else:
                net = s.gross - s.fee - s.tax
                acc.receivable -= net
                acc.available += net
                self.journal(acc, "SELL_SETTLEMENT", s.gross, t, d, "SETTLEMENT", s.settlement_id,
                             description=f"Tiền bán {s.qty} {inst.symbol}")
                self.journal(acc, "TRADING_FEE", -s.fee, t, d, "SETTLEMENT", s.settlement_id)
                self.journal(acc, "SELLING_TAX", -s.tax, t, d, "SETTLEMENT", s.settlement_id)
                self.movement(acc.account_id, inst.instrument_id, "SELL_SETTLED", -s.qty, t, d, "SETTLEMENT",
                              s.settlement_id, s.trade_date)
                self._auto_repay(acc, t)
            self._settlement_row(s, "SETTLED", t, t)
            touched.add((acc.account_id, inst.instrument_id))
        for acc_id, inst_id in touched:
            self.touch_pos(acc_id, inst_id, t)
            self.touch_cash(self.accounts[acc_id], t)

    def _loan_row(self, loan: Loan, t: datetime) -> None:
        loan.version += 1
        self.out("margin.loans", {
            "loan_id": loan.loan_id, "account_id": loan.account.account_id, "loan_product_id": loan.loan_product_id,
            "principal_amount": loan.principal, "outstanding_amount": loan.outstanding,
            "annual_interest_rate_pct": loan.rate_pct, "disbursed_at": loan.disbursed_at, "due_date": loan.due_date,
            "status": loan.status, "closed_at": loan.closed_at, "created_at": loan.disbursed_at, "updated_at": t,
            "version": loan.version})

    def _new_loan(self, acc: Account, amount: int, t: datetime) -> Loan:
        product = self.loan_products[acc.loan_product_id]
        loan = Loan(self.nid("margin.loans"), acc, acc.loan_product_id, amount, amount, product["rate"], t,
                    self.day + timedelta(days=product["term"]), version=0)
        self.loans[acc.account_id].append(loan)
        self._loan_row(loan, t)
        return loan

    def _auto_repay(self, acc: Account, t: datetime) -> None:
        for loan in self.loans[acc.account_id]:
            if acc.available <= 0:
                break
            if loan.status not in ("ACTIVE", "OVERDUE") or loan.outstanding <= 0:
                continue
            pay = min(acc.available, loan.outstanding)
            acc.available -= pay
            loan.outstanding -= pay
            self.journal(acc, "LOAN_REPAYMENT", -pay, t, self.day, "LOAN", loan.loan_id,
                         description="Tự động trả nợ margin từ tiền bán")
            if loan.outstanding == 0:
                loan.status, loan.closed_at = "REPAID", t
            self._loan_row(loan, t)

    def _accrue_interest(self, d: date) -> None:
        prev = add_trading_days(d, -1)
        days = max(1, (d - prev).days)
        for loans in self.loans.values():
            for loan in loans:
                if loan.status not in ("ACTIVE", "OVERDUE") or loan.outstanding <= 0:
                    continue
                overdue = d > loan.due_date
                rate = loan.rate_pct * (1.5 if overdue else 1)
                interest = round(loan.outstanding * rate / 100 / 365 * days)
                loan.accrued += interest
                self.out("margin.interest_accruals", {"loan_id": loan.loan_id, "accrual_date": d,
                                                      "outstanding_amount": loan.outstanding,
                                                      "interest_amount": interest, "is_overdue": overdue})
                if overdue and loan.status == "ACTIVE":
                    loan.status = "OVERDUE"
                    self._loan_row(loan, self.now)

    def _charge_interest(self, d: date) -> None:
        t = self.now
        for acc_id, loans in self.loans.items():
            due = sum(l.accrued for l in loans)
            if due <= 0:
                continue
            acc = self.accounts[acc_id]
            pay = min(acc.available, due)
            acc.available -= pay
            self.journal(acc, "MARGIN_INTEREST", -pay, t, d, "LOAN", None, description=f"Thu lãi margin tháng {add_trading_days(d, -1):%m/%Y}")
            unpaid = due - pay
            for loan in loans:
                loan.accrued = 0
            open_loans = [l for l in loans if l.status in ("ACTIVE", "OVERDUE")]
            if unpaid and open_loans:
                open_loans[0].outstanding += unpaid
                self._loan_row(open_loans[0], t)
            self.touch_cash(acc, t)

    def _margin_check(self, d: date) -> None:
        t = self.now
        for acc_id, loans in self.loans.items():
            acc = self.accounts[acc_id]
            debt = sum(l.outstanding for l in loans if l.status in ("ACTIVE", "OVERDUE")) + acc.margin_pending
            call = self.calls.get(acc.open_call_id) if acc.open_call_id else None
            if debt <= 0 and not call:
                continue
            securities = sum(self.positions[(acc_id, i)].total * self.instruments[i].last_close
                             for i in self.acc_holdings[acc_id])
            assets = acc.available + acc.receivable + securities
            equity = assets - debt
            ratio = 100.0 * equity / assets if assets > 0 else 0.0
            product = self.loan_products[acc.loan_product_id]
            if call:
                if ratio >= product["maintenance"] or debt <= 0:
                    call.status = ("MET_BY_DEPOSIT" if call.deposited else "MET_BY_SALE" if call.sold
                                   else "MET_BY_PRICE_RECOVERY")
                    call.resolved_at = t
                    acc.open_call_id = None
                    self._call_row(call, t)
                elif ratio < product["force"] or d >= call.deadline_date:
                    self.at(vn_time(next_trading_day(d), 9, 5), self._force_sell, call)
                continue
            if debt > 0 and ratio < product["maintenance"]:
                m = product["maintenance"] / 100
                required = max(1_000_000, int(round((m * assets - equity) / (1 - m), -5)))
                deadline_date = add_trading_days(d, 2)
                call = MarginCall(self.nid("margin.margin_calls"), acc, d, round(ratio, 2), required, deadline_date,
                                  vn_time(deadline_date, 14, 30), created_at=t)
                self.calls[call.margin_call_id] = call
                acc.open_call_id = call.margin_call_id
                self._call_row(call, t)
                c = self.customer_by_id[acc.customer_id]
                respond = {"HNW": 0.6, "INSTITUTION": 0.7}.get(c.segment, 0.35)
                if self.r.random() < respond:
                    when = vn_time(next_trading_day(d), self.r.randint(8, 11), self.r.randint(0, 59))
                    self.at(when, self.deposit, acc, int(required * self.r.uniform(1.0, 1.3)), "BANK_TRANSFER",
                            "Nộp tiền bổ sung ký quỹ")
                if self.r.random() < 0.3:
                    self.ticket_plan[next_trading_day(d)].append((c, "MARGIN"))
                self.gt.margin_calls.append({"margin_call_id": call.margin_call_id, "customer_id": c.customer_id,
                                             "segment": c.segment, "risk_appetite": c.risk_appetite,
                                             "customer_plans_to_deposit": respond})

    def _call_row(self, call: MarginCall, t: datetime) -> None:
        self.out("margin.margin_calls", {
            "margin_call_id": call.margin_call_id, "account_id": call.account.account_id, "call_date": call.call_date,
            "margin_ratio_pct": call.ratio_pct, "required_amount": call.required, "deadline_at": call.deadline_at,
            "status": call.status, "resolved_at": call.resolved_at, "notified_channels": "SMS,EMAIL,APP",
            "created_at": call.created_at, "updated_at": t})

    def _force_sell(self, call: MarginCall) -> None:
        if call.status != "OPEN":
            return
        acc, t = call.account, self.now
        c = self.customer_by_id[acc.customer_id]
        debt = sum(l.outstanding for l in self.loans[acc.account_id] if l.status in ("ACTIVE", "OVERDUE"))
        target = debt * 1.1
        employee = c.rm_employee_id or self.r.choice(self.employees.get("OPERATIONS", [None]))
        for inst_id in sorted(self.acc_holdings[acc.account_id],
                              key=lambda i: -self.positions[(acc.account_id, i)].available * self.instruments[i].last_close):
            if target <= 0:
                break
            inst = self.instruments[inst_id]
            avail = self.positions[(acc.account_id, inst_id)].available
            if avail < 100 or not inst.tradable:
                continue
            qty = min(avail, (int(target / inst.floor / 100) + 1) * 100)
            self.submit_order(c, acc, inst, "SELL", "LO", inst.floor, qty, "BROKER", employee, source="SYSTEM")
            target -= qty * inst.floor
        call.status, call.resolved_at = "FORCE_SOLD", t
        acc.open_call_id = None
        self._call_row(call, t)

    # ------------------------------------------------------------ end of session
    def end_of_session(self, d: date) -> None:
        t = self.now
        for o in list(self.open_orders.values()):
            self.expire(o, None, "END_OF_DAY")
        gainers, losers, total_value = [], [], 0
        for inst in self.tradable:
            path = inst.path
            vwap = float(np.mean(path))
            base = inst.liquidity * math.exp(self.rng.normal(0, 0.35)) * (1 + 15 * abs(inst.close / inst.ref - 1))
            volume = int(max(base, inst.client_volume * 25) / 10) * 10
            value = int(volume * vwap)
            total_value += value
            foreign = self.r.uniform(0.02, 0.15)
            self.out("product.eod_prices", {
                "instrument_id": inst.instrument_id, "trade_date": d, "reference_price": inst.ref,
                "ceiling_price": inst.ceiling, "floor_price": inst.floor, "open_price": inst.open,
                "high_price": int(max(path.max(), inst.open)), "low_price": int(min(path.min(), inst.open)),
                "close_price": inst.close, "volume": volume, "trading_value": value,
                "foreign_buy_volume": int(volume * foreign * self.r.uniform(0.6, 1.4)),
                "foreign_sell_volume": int(volume * foreign * self.r.uniform(0.6, 1.4)), "created_at": t})
            change = inst.close / inst.ref - 1
            if change > 0.04:
                gainers.append(inst.symbol)
            elif change < -0.04:
                losers.append(inst.symbol)
            inst.last_close = inst.close
        for inst_id, w in self.warrants.items():
            inst = self.instruments[inst_id]
            if inst.status != "ACTIVE" or d > w["maturity"]:
                continue
            # CW limits move by the underlying's daily limit divided by the conversion ratio.
            under, ref = w["underlying"], inst.last_close
            amplitude = (under.ceiling - under.ref) / w["ratio"]
            ceiling = round_to_tick(ref + amplitude, "HOSE", "COVERED_WARRANT", "down")
            floor = round_to_tick(max(10, ref - amplitude), "HOSE", "COVERED_WARRANT", "up")
            close = min(ceiling, max(floor, self.warrant_price(inst_id, under.close, d)))
            volume = int(self.r.uniform(1e4, 5e5) / 10) * 10
            self.out("product.eod_prices", {
                "instrument_id": inst_id, "trade_date": d, "reference_price": ref, "ceiling_price": ceiling,
                "floor_price": floor, "open_price": ref, "high_price": max(ref, close), "low_price": min(ref, close),
                "close_price": close, "volume": volume, "trading_value": volume * close, "foreign_buy_volume": 0,
                "foreign_sell_volume": 0, "created_at": t})
            inst.last_close = close
        for inst_id, f in self.funds.items():
            if f["weekly"] and d.weekday() != 4:
                continue
            inst = self.instruments[inst_id]
            f["nav"] *= math.exp(inst.mu + inst.beta * self.market_return * (1 if inst.sigma > 0.005 else 0)
                                 + self.rng.normal(0, inst.sigma))
            f["units"] *= math.exp(self.rng.normal(0, 0.003))
            self.out("product.fund_navs", {"instrument_id": inst_id, "nav_date": d, "nav_per_unit": round(f["nav"], 4),
                                           "total_nav": round(f["nav"] * f["units"], 2)})
        self._accrue_interest(d)
        self._margin_check(d)
        title, body = textgen.market_wrap(d, self.market_return, gainers[:5], losers[:5], total_value)
        self.at(vn_time(d, 15, 30), self._article, title, body, [])
        self._research_reports(d)

    # ------------------------------------------------------------ content
    def _article(self, title: str, body: str, instruments: list[Instrument], truth: dict | None = None) -> None:
        aid = self.nid("content.news_articles")
        self.out("content.news_articles", {"article_id": aid, "title": title, "body": body,
                                           "source_name": self.r.choice(refdata.NEWS_SOURCES), "language_code": "vi",
                                           "published_at": self.now, "created_at": self.now})
        for inst in instruments:
            self.out("content.article_instruments", {"article_id": aid, "instrument_id": inst.instrument_id})
        if truth:
            self.gt.news.append({"article_id": aid, **truth})

    def _news(self, inst: Instrument, sentiment: str, shock: float) -> None:
        title, body = textgen.news_article(self.r, inst.name, inst.symbol, sentiment)
        self._article(title, body, [inst], {"instrument_id": inst.instrument_id, "symbol": inst.symbol,
                                            "trade_date": self.day, "sentiment": sentiment, "return_shock": round(shock, 4)})

    def _research_reports(self, d: date) -> None:
        analysts = self.employees.get("ANALYST", [])
        if not analysts:
            return
        for inst in self.tradable:
            if inst.itype != "STOCK" or self.r.random() > 1 / 60:
                continue
            expected = inst.mu * 250 + self.r.gauss(0, 0.08)
            rec = ("BUY" if expected > 0.15 else "OUTPERFORM" if expected > 0.05 else "HOLD" if expected > -0.05
                   else "UNDERPERFORM" if expected > -0.15 else "SELL")
            target = round_to_tick(inst.close * (1 + expected), inst.exchange, "STOCK")
            title, body = textgen.research_report(inst.name, inst.symbol, rec, target, inst.close)
            self.out("content.research_reports", {
                "report_id": self.nid("content.research_reports"), "instrument_id": inst.instrument_id,
                "analyst_employee_id": self.r.choice(analysts), "recommendation": rec, "target_price": target,
                "title": title, "body": body, "published_at": vn_time(d, 16, self.r.randint(0, 59))})

    def _fs_disclosure(self, inst: Instrument, row: dict, when: datetime | None = None) -> None:
        title, body = textgen.financial_statement_disclosure(inst.name, inst.symbol, row["fiscal_year"],
                                                             row["fiscal_quarter"], row["revenue"], row["net_income"],
                                                             row["is_audited"])
        did = self.nid("content.disclosures")
        self.out("content.disclosures", {"disclosure_id": did, "issuer_id": inst.issuer_id,
                                         "disclosure_type": "FINANCIAL_STATEMENT", "ca_event_id": None, "title": title,
                                         "body": body, "published_at": when or self.now})
        self.gt.disclosures.append({"disclosure_id": did, "disclosure_type": "FINANCIAL_STATEMENT",
                                    "issuer_id": inst.issuer_id, "fiscal_year": row["fiscal_year"],
                                    "fiscal_quarter": row["fiscal_quarter"], "revenue": row["revenue"],
                                    "net_income": row["net_income"]})

    # ------------------------------------------------------------ corporate actions
    def _ca_row(self, ev: dict, t: datetime) -> None:
        self.out("corp_action.events", {
            "ca_event_id": ev["ca_event_id"], "instrument_id": ev["inst"].instrument_id, "ca_type": ev["ca_type"],
            "announced_on": ev["announced_on"], "ex_date": ev["ex_date"], "record_date": ev["record_date"],
            "payment_date": ev["payment_date"], "cash_per_share": ev["cash_per_share"],
            "ratio_numerator": ev["num"], "ratio_denominator": ev["den"], "subscription_price": None,
            "status": ev["status"], "created_at": ev.setdefault("created_at", t), "updated_at": t})

    def _announce_ca(self, ev: dict) -> None:
        t = vn_time(ev["announced_on"], 17)
        inst = ev["inst"]
        self._ca_row(ev, t)
        title, body = textgen.dividend_disclosure(inst.name, inst.symbol, ev["ca_type"], ev["ex_date"],
                                                  ev["record_date"], ev["payment_date"], ev["cash_per_share"],
                                                  (ev["num"], ev["den"]) if ev["num"] else None)
        did = self.nid("content.disclosures")
        self.out("content.disclosures", {"disclosure_id": did, "issuer_id": inst.issuer_id,
                                         "disclosure_type": "DIVIDEND_ANNOUNCEMENT", "ca_event_id": ev["ca_event_id"],
                                         "title": title, "body": body, "published_at": t})
        self.gt.disclosures.append({"disclosure_id": did, "disclosure_type": "DIVIDEND_ANNOUNCEMENT",
                                    "issuer_id": inst.issuer_id, "ca_type": ev["ca_type"], "ex_date": ev["ex_date"],
                                    "record_date": ev["record_date"], "payment_date": ev["payment_date"],
                                    "cash_per_share": ev["cash_per_share"], "ratio_numerator": ev["num"],
                                    "ratio_denominator": ev["den"]})

    def _corporate_actions(self, d: date) -> None:
        t = self.now
        for ev in self.ca_events:
            inst = ev["inst"]
            if ev["record_date"] == d:
                ev["entitlements"] = []
                for (acc_id, inst_id), p in self.positions.items():
                    if inst_id != inst.instrument_id or p.total <= 0:
                        continue
                    ent = {"entitlement_id": self.nid("corp_action.entitlements"), "ca_event_id": ev["ca_event_id"],
                           "account_id": acc_id, "eligible_quantity": p.total, "entitled_quantity": 0,
                           "entitled_cash": 0, "tax_withheld": 0, "status": "PENDING", "paid_at": None}
                    if ev["ca_type"] == "CASH_DIVIDEND":
                        ent["entitled_cash"] = p.total * ev["cash_per_share"]
                        ent["tax_withheld"] = round(ent["entitled_cash"] * DIVIDEND_TAX_RATE)
                    else:
                        ent["entitled_quantity"] = p.total * ev["den"] // ev["num"]
                    ev["entitlements"].append(ent)
                    self.out("corp_action.entitlements", ent)
                ev["status"] = "ENTITLED"
                self._ca_row(ev, t)
            if ev["payment_date"] == d and ev.get("entitlements") is not None:
                for ent in ev["entitlements"]:
                    acc = self.accounts[ent["account_id"]]
                    if ev["ca_type"] == "CASH_DIVIDEND":
                        acc.available += ent["entitled_cash"] - ent["tax_withheld"]
                        self.journal(acc, "CASH_DIVIDEND", ent["entitled_cash"], t, d, "CORPORATE_ACTION",
                                     ent["entitlement_id"], description=f"Cổ tức tiền mặt {inst.symbol}")
                        self.journal(acc, "DIVIDEND_TAX", -ent["tax_withheld"], t, d, "CORPORATE_ACTION",
                                     ent["entitlement_id"], description=f"Thuế TNCN cổ tức {inst.symbol}")
                        self.touch_cash(acc, t)
                    elif ent["entitled_quantity"] > 0:
                        p = self.positions[(acc.account_id, inst.instrument_id)]
                        p.avg_cost = p.avg_cost * p.total / (p.total + ent["entitled_quantity"])
                        p.total += ent["entitled_quantity"]
                        p.available += ent["entitled_quantity"]
                        self.movement(acc.account_id, inst.instrument_id, "STOCK_DIVIDEND", ent["entitled_quantity"],
                                      t, d, "CORPORATE_ACTION", ent["entitlement_id"])
                        self.touch_pos(acc.account_id, inst.instrument_id, t)
                    ent["status"], ent["paid_at"] = "PAID", t
                    self.out("corp_action.entitlements", ent)
                if ev["ca_type"] == "STOCK_DIVIDEND":
                    inst.listed_shares += inst.listed_shares * ev["den"] // ev["num"]
                    inst.version += 1
                ev["status"] = "PAID"
                self._ca_row(ev, t)

    # ------------------------------------------------------------ CRM
    def _crm_day(self, d: date) -> None:
        r = self.r
        for c, category in self.ticket_plan.pop(d, []):
            self.at(vn_time(d, r.randint(8, 20), r.randint(0, 59)), self._ticket, c, category)
        candidates = [c for c in self.customers if c.status != "CLOSED" and c.opened <= d]
        for _ in range(self.rng.poisson(len(candidates) * 0.0004)):
            c = r.choice(candidates)
            category = r.choices(["LOGIN_OTP", "DEPOSIT_WITHDRAWAL", "ORDER_ISSUE", "FEES", "APP_BUG", "ACCOUNT_OPENING",
                                  "CORPORATE_ACTION", "OTHER", "COMPLAINT"],
                                 [0.2, 0.18, 0.15, 0.08, 0.1, 0.07, 0.07, 0.1, 0.05])[0]
            self.at(vn_time(d, r.randint(8, 21), r.randint(0, 59)), self._ticket, c, category)
        for c in candidates:
            if c.rm_employee_id and c.segment in ("HNW", "ACTIVE", "INSTITUTION") and r.random() < 0.01:
                self.at(vn_time(d, r.randint(9, 17), r.randint(0, 59)), self._rm_note, c)
            if r.random() < 0.0004:
                self.at(vn_time(d, 10), self._kyc_review, c)

    def _ticket(self, c: Customer, category: str) -> None:
        t, r = self.now, self.r
        unhappy = category == "COMPLAINT" or (c.churn_date is not None and c.churn_date >= self.day)
        priority = "HIGH" if category in ("COMPLAINT", "MARGIN") else r.choice(["LOW", "MEDIUM", "MEDIUM"])
        if category == "MARGIN" and r.random() < 0.3:
            priority = "URGENT"
        acc_no = self.accounts[c.accounts["CASH"]].account_no if c.accounts else None
        subject, messages = textgen.ticket(r, category, acc_no)
        support = self.employees.get("SUPPORT", []) or [None]
        tid = self.nid("crm.support_tickets")
        channel = r.choices(["HOTLINE", "LIVE_CHAT", "EMAIL", "APP_FEEDBACK", "BRANCH"], [0.35, 0.3, 0.15, 0.15, 0.05])[0]
        first_response = t + timedelta(minutes=r.expovariate(1 / 20))
        resolved = first_response + timedelta(hours=r.expovariate(1 / (30 if unhappy else 8)))
        row = {"ticket_id": tid, "customer_id": c.customer_id, "channel": channel, "category": category,
               "priority": priority, "subject": subject, "status": "OPEN", "assigned_employee_id": r.choice(support),
               "csat_score": None, "opened_at": t, "first_response_at": None, "resolved_at": None,
               "created_at": t, "updated_at": t}
        self.tickets[tid] = row
        self.out("crm.support_tickets", row)
        when = t
        if channel == "LIVE_CHAT":
            self.at(t + timedelta(seconds=2), self._ticket_message, tid, "BOT",
                    "Xin chào, trợ lý ảo ZSC có thể giúp gì cho anh/chị?", None)
        for k, (sender, text) in enumerate(messages):
            when = t if k == 0 else when + timedelta(minutes=r.expovariate(1 / 15))
            self.at(when, self._ticket_message, tid, sender, text,
                    row["assigned_employee_id"] if sender == "AGENT" else None)
        self.at(first_response, self._ticket_update, tid, "IN_PROGRESS", None)
        csat = r.choice([1, 2, 2, 3]) if unhappy else r.choice([3, 4, 4, 5, 5, 5])
        self.at(resolved, self._ticket_update, tid, "RESOLVED", csat if r.random() < 0.6 else None)
        self.at(resolved + timedelta(days=2), self._ticket_update, tid, "CLOSED", None)

    def _ticket_message(self, tid: int, sender: str, body: str, employee: int | None) -> None:
        self.out("crm.ticket_messages", {"message_id": self.nid("crm.ticket_messages"), "ticket_id": tid,
                                         "sender_type": sender, "employee_id": employee, "body": body,
                                         "sent_at": self.now})

    def _ticket_update(self, tid: int, status: str, csat: int | None) -> None:
        row = dict(self.tickets[tid])
        row["status"], row["updated_at"] = status, self.now
        if status == "IN_PROGRESS":
            row["first_response_at"] = self.now
        if status == "RESOLVED":
            row["resolved_at"], row["csat_score"] = self.now, csat
        if status == "CLOSED":
            del self.tickets[tid]
        else:
            self.tickets[tid] = row
        self.out("crm.support_tickets", row)

    def _rm_note(self, c: Customer) -> None:
        holdings = [self.instruments[i].symbol for a in c.accounts.values() for i in self.acc_holdings[a]]
        note_type = self.r.choice(["CALL", "CALL", "MEETING", "ADVICE", "FOLLOW_UP"])
        self.out("crm.rm_notes", {"note_id": self.nid("crm.rm_notes"), "customer_id": c.customer_id,
                                  "employee_id": c.rm_employee_id, "note_type": note_type,
                                  "body": textgen.rm_note(self.r, note_type, holdings), "created_at": self.now})

    def _kyc_review(self, c: Customer) -> None:
        old = dict(self.kyc[c.customer_id])
        old["valid_to"] = self.now
        self.out("customer.kyc_profiles", old)
        if self.r.random() < 0.4:
            c.risk_appetite = self.r.choice(["CONSERVATIVE", "BALANCED", "AGGRESSIVE"])
        new = world._kyc_row(self, c, self.now)
        if c.fraud_pattern and self.r.random() < 0.5:
            new["risk_rating"] = "HIGH"
        self.kyc[c.customer_id] = new
        self.out("customer.kyc_profiles", new)

    # ------------------------------------------------------------ AML
    def _run_pattern(self, d: date, item: tuple) -> None:
        kind, r = item[0], self.r
        if kind == "STRUCTURING":
            c, n = item[1], item[2]
            acc = self.accounts[c.accounts["CASH"]]
            for _ in range(n):
                self.at(vn_time(d, r.randint(9, 15), r.randint(0, 59)), self.deposit, acc,
                        int(round(r.uniform(250e6, 299.9e6), -5)), "BANK_TRANSFER", None)
        elif kind == "RAPID_IN":
            c = item[1]
            acc = self.accounts[c.accounts["CASH"]]
            amount = int(round(r.uniform(0.5e9, 3e9), -6))
            self.at(vn_time(d, 9, r.randint(0, 59)), self.deposit, acc, amount, "BANK_TRANSFER", None)
            self.at(vn_time(next_trading_day(d), 10, r.randint(0, 59)), self.withdraw, acc,
                    int(amount * r.uniform(0.95, 1.0)), "WEB")
        elif kind == "CHURN_WITHDRAW":
            c = item[1]
            for acc_id in c.accounts.values():
                acc = self.accounts[acc_id]
                self.at(vn_time(d, r.randint(9, 15), r.randint(0, 59)), self._withdraw_most, acc)
        elif kind == "SPOOFING":
            self.at(vn_time(d, 9, 30), self._spoof, item[1])
        elif kind == "WASH_TRADE":
            ring, inst = item[1], item[2]
            for _ in range(r.randint(3, 5)):
                buyer, seller = r.sample(ring, 2)
                minute = r.randrange(5, N_MINUTES - 10)
                self.at(minute_time(d, minute, r.uniform(0, 30)), self._wash, buyer, seller, inst)

    def _withdraw_most(self, acc: Account) -> None:
        self.withdraw(acc, int(acc.available * 0.95 / 1e6) * 1_000_000, "MOBILE")

    def _spoof(self, c: Customer) -> None:
        acc = self.accounts[c.accounts["CASH"]]
        inst = max(self.tradable[:40], key=lambda i: i.liquidity)
        t0 = self.now
        for k in range(self.r.randint(25, 40)):
            self.at(t0 + timedelta(seconds=k * self.r.uniform(30, 120)), self._spoof_order, c, acc, inst)

    def _spoof_order(self, c: Customer, acc: Account, inst: Instrument) -> None:
        market = self.market_price(inst, self.now)
        tick = tick_size(inst.exchange, inst.itype, market)
        price = max(inst.floor, market - self.r.randint(2, 5) * tick)
        qty = int(acc.available * 0.05 / price / 100) * 100
        if qty < 100:
            return
        self.login(c, c.devices[0])
        o = self.submit_order(c, acc, inst, "BUY", "LO", price, qty, "API", None)
        if o.is_open:
            self.at(self.now + timedelta(seconds=self.r.uniform(1, 4.5)), self.client_cancel, o)

    def _wash(self, buyer: Customer, seller: Customer, inst: Instrument) -> None:
        price = self.market_price(inst, self.now)
        qty = self.r.randint(5, 20) * 100
        self.login(buyer, buyer.devices[-1])
        self.submit_order(buyer, self.accounts[buyer.accounts["CASH"]], inst, "BUY", "LO", price, qty, "MOBILE", None)
        self.at(self.now + timedelta(seconds=self.r.uniform(5, 90)), self._wash_sell, seller, inst, price, qty)

    def _wash_sell(self, seller: Customer, inst: Instrument, price: int, qty: int) -> None:
        self.login(seller, seller.devices[-1])
        acc = self.accounts[seller.accounts["CASH"]]
        self.submit_order(seller, acc, inst, "SELL", "LO", min(inst.ceiling, max(inst.floor, price)), qty, "MOBILE", None)

    def _aml_rules(self, d: date) -> None:
        alerts = []
        for cid, amounts in self.deposits_today.items():
            band = [a for a in amounts if 250e6 <= a < 300e6]
            if len(band) >= 3:
                alerts.append(("STRUCTURING", cid, {"deposits": band, "count": len(band)}))
            for a in amounts:
                if a >= 1e9:
                    alerts.append(("LARGE_CASH", cid, {"amount": a}))
        window = add_trading_days(d, -2)
        self.recent_deposits = [x for x in self.recent_deposits if x[0] >= window]
        for cid, out in self.withdrawals_today.items():
            for day, dep_cid, amount in self.recent_deposits:
                if dep_cid == cid and amount >= 500e6 and out >= 0.9 * amount and self.last_trade_day.get(cid, date.min) < day:
                    alerts.append(("RAPID_IN_OUT", cid, {"deposit": amount, "withdrawal": out, "deposit_date": str(day)}))
                    break
        cutoff = d - timedelta(days=30)
        for device in self.devices_today:
            users = [cid for cid, last in self.device_logins[device].items() if last >= cutoff]
            if len(users) > 3:
                for cid in users:
                    alerts.append(("SHARED_DEVICE", cid, {"device_id": device, "customers": len(users)}))
            if len(users) >= 2:
                execs = [(cid, x) for cid in users for x in self.execs_today.get(cid, [])]
                for cid in users:
                    mine = self.execs_today.get(cid, [])
                    hits = sum(1 for inst_id, side, t in mine for other, (i2, s2, t2) in execs
                               if other != cid and i2 == inst_id and s2 != side and abs((t2 - t).total_seconds()) <= 300)
                    if hits >= 3:
                        alerts.append(("WASH_TRADE", cid, {"device_id": device, "matches": hits}))
        for acc_id, n in self.fast_cancels.items():
            if n > 20:
                alerts.append(("SPOOFING", self.accounts[acc_id].customer_id, {"fast_cancels": n}))
        for rule, cid, details in alerts:
            key = (rule, cid)
            if rule != "LARGE_CASH" and key in self.alerted and (d - self.alerted[key]).days < 30:
                continue
            self.alerted[key] = d
            self._alert(rule, cid, details, d)

    def _alert(self, rule: str, cid: int, details: dict, d: date) -> None:
        c = self.customer_by_id[cid]
        base = {"LOW": 30, "MEDIUM": 55, "HIGH": 75}[self.aml_severity[rule]]
        row = {"alert_id": self.nid("compliance.aml_alerts"), "rule_code": rule, "customer_id": cid,
               "account_id": c.accounts.get("CASH"), "alert_date": d,
               "score": round(min(99.0, max(1.0, base + self.r.gauss(0, 10))), 2), "details": details,
               "status": "OPEN", "disposition": None, "reviewed_by_employee_id": None, "review_comment": None,
               "closed_at": None, "created_at": self.now, "updated_at": self.now}
        self.out("compliance.aml_alerts", row)
        review = add_trading_days(d, self.r.randint(1, 8))
        self.at(vn_time(review, 10, self.r.randint(0, 59)), self._close_alert, row, c)

    def _close_alert(self, row: dict, c: Customer) -> None:
        u = self.r.random()
        if c.fraud_pattern:
            disposition = "TRUE_POSITIVE" if u < 0.85 else "INCONCLUSIVE" if u < 0.95 else "FALSE_POSITIVE"
        else:
            disposition = "FALSE_POSITIVE" if u < 0.88 else "INCONCLUSIVE" if u < 0.96 else "TRUE_POSITIVE"
        comment = {"TRUE_POSITIVE": "Xác nhận giao dịch đáng ngờ, đã lập báo cáo và đề xuất hạn chế tài khoản.",
                   "FALSE_POSITIVE": "Đã liên hệ khách hàng, nguồn tiền và mục đích giao dịch hợp lý.",
                   "INCONCLUSIVE": "Chưa đủ căn cứ kết luận, tiếp tục theo dõi trong 90 ngày."}[disposition]
        row = dict(row, status="CLOSED", disposition=disposition, review_comment=comment, closed_at=self.now,
                   updated_at=self.now,
                   reviewed_by_employee_id=self.r.choice(self.employees.get("COMPLIANCE", [None])))
        self.out("compliance.aml_alerts", row)

    # ------------------------------------------------------------ live market data
    def _ticks(self, i: int) -> None:
        t = self.now
        for inst in self.tradable:
            price = int(inst.path[i])
            self.emit("marketdata.ticks", inst.symbol, {
                "symbol": inst.symbol, "instrument_id": inst.instrument_id, "exchange": inst.exchange,
                "price": price, "reference_price": inst.ref, "ceiling_price": inst.ceiling, "floor_price": inst.floor,
                "volume": int(inst.liquidity / N_MINUTES * self.r.uniform(0.3, 2.0) / 10) * 10,
                "event_time": t.isoformat()})
