"""Presets, connection settings and paths."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
GENERATOR_DIR = PACKAGE_DIR.parent
DATASET_DIR = GENERATOR_DIR.parent
STREAMING_DIR = DATASET_DIR.parent
OUTPUT_DIR = GENERATOR_DIR / "output"


@dataclass(frozen=True)
class Preset:
    name: str
    customers: int
    stocks: int
    etfs: int
    covered_warrants: int
    bonds: int
    funds: int
    employees: int
    start: date
    end: date
    # Multiplies every segment's order rate; tuned so S gives roughly 300k orders.
    rate_scale: float


PRESETS = {
    "XS": Preset("XS", 500, 30, 2, 4, 4, 2, 40, date(2025, 6, 2), date(2025, 6, 30), 3.0),
    "S": Preset("S", 5_000, 140, 4, 10, 10, 4, 120, date(2025, 4, 1), date(2025, 6, 30), 3.0),
    "M": Preset("M", 50_000, 380, 8, 30, 30, 8, 600, date(2024, 7, 1), date(2025, 6, 30), 2.0),
    "L": Preset("L", 300_000, 600, 12, 60, 60, 12, 2_500, date(2023, 7, 3), date(2025, 6, 30), 1.5),
}

# Anchor entities referenced by dataset/text2sql/gold_examples.jsonl.
ANCHOR_SYMBOLS = {"ZTC": "3010", "ZAB": "1010", "ZRE": "2010"}

BROKER_CODE = "ZSC"          # fictional 3-char depository member code used in custody codes
SELLING_TAX_RATE = 0.001     # 0.1% of the sale value
DIVIDEND_TAX_RATE = 0.05     # 5% on cash dividends
SETTLEMENT_DAYS = 2          # T+2


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True)
class Settings:
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    my_host: str
    my_port: int
    my_db: str
    my_user: str
    my_password: str
    kafka_bootstrap: str

    def pg_conninfo(self) -> str:
        return (f"host={self.pg_host} port={self.pg_port} dbname={self.pg_db} "
                f"user={self.pg_user} password={self.pg_password}")


def load_settings() -> Settings:
    """streaming/.env provides defaults; GEN_* environment variables override them."""
    env = {**_read_dotenv(STREAMING_DIR / ".env"), **os.environ}
    return Settings(
        pg_host=env.get("GEN_PG_HOST", "127.0.0.1"),
        pg_port=int(env.get("GEN_PG_PORT", "5432")),
        pg_db=env.get("GEN_PG_DB", "appdb"),
        pg_user=env.get("GEN_PG_USER", env.get("POSTGRES_APP_USER", "app")),
        pg_password=env.get("GEN_PG_PASSWORD", env.get("POSTGRES_APP_PASSWORD", "")),
        my_host=env.get("GEN_MYSQL_HOST", "127.0.0.1"),
        my_port=int(env.get("GEN_MYSQL_PORT", "3307")),
        my_db=env.get("GEN_MYSQL_DB", "oms"),
        my_user=env.get("GEN_MYSQL_USER", env.get("MYSQL_APP_USER", "app")),
        my_password=env.get("GEN_MYSQL_PASSWORD", env.get("MYSQL_APP_PASSWORD", "")),
        kafka_bootstrap=env.get("GEN_KAFKA_BOOTSTRAP", "localhost:9094"),
    )
