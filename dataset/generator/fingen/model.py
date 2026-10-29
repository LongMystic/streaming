"""In-memory simulation state. Money is int VND; prices are int VND except fund NAV."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np


@dataclass
class Instrument:
    instrument_id: int
    symbol: str
    itype: str
    exchange: str | None
    issuer_id: int | None
    name: str
    sector_code: str | None
    lot: int
    band: float
    mu: float              # daily drift (hidden "quality" of the company)
    sigma: float           # daily volatility
    beta: float
    liquidity: float       # typical market volume, shares per day
    last_close: int
    listed_shares: int
    status: str = "ACTIVE"
    margin_ratio: float = 0.0   # loan ratio in the standard margin list, 0 = not marginable
    version: int = 1
    # per-day state
    ref: int = 0
    floor: int = 0
    ceiling: int = 0
    open: int = 0
    close: int = 0
    path: np.ndarray | None = None
    news_shock: float = 0.0
    client_volume: int = 0
    client_value: int = 0

    @property
    def tradable(self) -> bool:
        return self.status == "ACTIVE" and self.itype in ("STOCK", "ETF")


@dataclass
class Account:
    account_id: int
    account_no: str
    customer_id: int
    atype: str
    fee_pct: float
    fee_schedule_id: int
    loan_product_id: int | None
    opened_at: datetime
    status: str = "ACTIVE"
    available: int = 0
    blocked: int = 0
    receivable: int = 0
    payable: int = 0
    margin_reserved: int = 0    # buying power reserved on open margin buy orders
    margin_pending: int = 0     # matched margin buys not yet disbursed (T+2)
    ledger_balance: int = 0     # running balance of cash_transactions = available + blocked + payable
    version: int = 1
    open_call_id: int | None = None


@dataclass
class Position:
    total: int = 0
    available: int = 0
    receiving: int = 0
    blocked: int = 0
    pledged: int = 0
    avg_cost: float = 0.0
    version: int = 1


@dataclass
class Customer:
    customer_id: int
    customer_code: str
    custody_code: str
    segment: str
    ctype: str
    is_foreign: bool
    branch_id: int
    rm_employee_id: int | None
    opened: date
    status: str
    order_rate: float
    login_rate: float
    cash_flow_rate: float
    wealth: int
    risk_appetite: str
    sectors: list[str]
    devices: list[str]
    ips: list[str]
    bank_account_id: int
    accounts: dict[str, int] = field(default_factory=dict)
    watchlist_ids: list[int] = field(default_factory=list)
    watch_symbols: list[int] = field(default_factory=list)
    churn_date: date | None = None
    fraud_pattern: str | None = None
    fraud_group: int | None = None
    row: dict = field(default_factory=dict)


@dataclass
class Order:
    order_id: int
    order_no: str
    account: Account
    customer: Customer
    inst: Instrument
    side: str
    otype: str
    price: int | None
    qty: int
    channel: str
    employee_id: int | None
    trade_date: date
    created_at: datetime
    source: str = "CLIENT"
    status: str = "PENDING_NEW"
    filled: int = 0
    fill_value: int = 0
    is_margin: bool = False
    reject_reason: str | None = None
    cash_blocked: int = 0
    margin_reserved: int = 0
    epoch: int = 0
    version: int = 0
    updated_at: datetime | None = None

    @property
    def remaining(self) -> int:
        return self.qty - self.filled

    @property
    def is_open(self) -> bool:
        return self.status in ("NEW", "PARTIALLY_FILLED")


@dataclass
class Settlement:
    settlement_id: int
    execution_id: int
    account: Account
    inst: Instrument
    side: str
    qty: int
    price: int
    gross: int
    fee: int
    tax: int
    trade_date: date
    settle_date: date
    cash_part: int
    loan_part: int
    created_at: datetime


@dataclass
class Loan:
    loan_id: int
    account: Account
    loan_product_id: int
    principal: int
    outstanding: int
    rate_pct: float
    disbursed_at: datetime
    due_date: date
    status: str = "ACTIVE"
    closed_at: datetime | None = None
    accrued: int = 0
    version: int = 1


@dataclass
class MarginCall:
    margin_call_id: int
    account: Account
    call_date: date
    ratio_pct: float
    required: int
    deadline_date: date
    deadline_at: datetime
    status: str = "OPEN"
    resolved_at: datetime | None = None
    deposited: bool = False
    sold: bool = False
    created_at: datetime | None = None
