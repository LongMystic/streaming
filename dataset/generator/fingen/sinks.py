"""Writers. The engine emits complete rows with sink.upsert(table, row).

BulkSink buffers rows and writes them once per simulated day (COPY / multi-row INSERT); a row
changed many times in a day is written once with its final state. LiveSink writes every change
in order, so CDC sees each intermediate state (NEW -> PARTIALLY_FILLED -> FILLED ...).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg
import pymysql

from .config import Settings

PG_TABLES = [
    "ref.exchanges", "ref.trading_calendar", "ref.sectors", "ref.branches", "ref.employees",
    "product.issuers", "product.fee_schedules", "product.instruments", "product.bond_details",
    "product.fund_details", "product.warrant_details", "product.financial_statements",
    "customer.customers", "customer.identity_documents", "customer.addresses", "customer.bank_accounts",
    "customer.kyc_profiles", "account.accounts", "margin.loan_products", "margin.marginable_instruments",
    "ledger.cash_balances", "ledger.cash_transactions", "custody.positions", "custody.position_movements",
    "custody.settlement_instructions", "margin.loans", "margin.interest_accruals", "margin.margin_calls",
    "corp_action.events", "corp_action.entitlements", "crm.support_tickets", "crm.ticket_messages",
    "crm.rm_notes", "compliance.aml_rules", "compliance.aml_alerts", "content.news_articles",
    "content.article_instruments", "content.disclosures", "content.research_reports",
    "content.product_documents", "product.eod_prices", "product.fund_navs",
]
MY_TABLES = ["oms.orders", "oms.order_events", "oms.executions", "oms.client_sessions",
             "oms.watchlists", "oms.watchlist_items"]

# Insert-only tables: written with plain COPY / INSERT (no upsert cost).
APPEND_ONLY = {
    "ref.trading_calendar", "product.financial_statements", "customer.identity_documents",
    "customer.addresses", "customer.bank_accounts", "ledger.cash_transactions", "custody.position_movements",
    "margin.interest_accruals", "crm.ticket_messages", "crm.rm_notes", "content.news_articles",
    "content.article_instruments", "content.disclosures", "content.research_reports",
    "content.product_documents", "product.eod_prices", "product.fund_navs",
    "oms.order_events", "oms.executions", "oms.client_sessions",
}


def _naive_utc(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class _Databases:
    def __init__(self, settings: Settings):
        self.pg = psycopg.connect(settings.pg_conninfo())
        self.my = pymysql.connect(host=settings.my_host, port=settings.my_port, user=settings.my_user,
                                  password=settings.my_password, database=settings.my_db,
                                  charset="utf8mb4", autocommit=False)
        self.pk: dict[str, list[str]] = {}
        self.jsonb: dict[str, set[str]] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:
        with self.pg.cursor() as cur:
            cur.execute("""
                SELECT n.nspname || '.' || c.relname, a.attname
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
                WHERE i.indisprimary
                ORDER BY 1, array_position(i.indkey::int2[], a.attnum)""")
            for table, column in cur.fetchall():
                self.pk.setdefault(table, []).append(column)
            cur.execute("""SELECT table_schema || '.' || table_name, column_name FROM information_schema.columns
                           WHERE data_type = 'jsonb'""")
            for table, column in cur.fetchall():
                self.jsonb.setdefault(table, set()).add(column)
        with self.my.cursor() as cur:
            cur.execute("""SELECT CONCAT(table_schema, '.', table_name), column_name FROM information_schema.key_column_usage
                           WHERE constraint_name = 'PRIMARY' AND table_schema = DATABASE() ORDER BY 1, ordinal_position""")
            for table, column in cur.fetchall():
                self.pk.setdefault(table, []).append(column)
        missing = [t for t in PG_TABLES + MY_TABLES if t not in self.pk]
        if missing:
            raise RuntimeError(f"Tables not found (run dataset/scripts/init_db.sh first): {missing}")

    # --- statement builders
    def pg_upsert_sql(self, table: str, cols: list[str], source: str) -> str:
        pk = self.pk[table]
        updates = [c for c in cols if c not in pk]
        action = "NOTHING" if not updates else "UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in updates)
        return (f"INSERT INTO {table} ({', '.join(cols)}) {source} "
                f"ON CONFLICT ({', '.join(pk)}) DO {action}")

    def my_sql(self, table: str, cols: list[str]) -> str:
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
        if table not in APPEND_ONLY:
            updates = [c for c in cols if c not in self.pk[table]]
            sql += " ON DUPLICATE KEY UPDATE " + ", ".join(f"{c} = VALUES({c})" for c in updates)
        return sql

    def close(self) -> None:
        self.pg.close()
        self.my.close()


class BulkSink:
    def __init__(self, settings: Settings):
        self.db = _Databases(settings)
        self.buffers: dict[str, object] = {}
        self.rows_written: dict[str, int] = {}

    def upsert(self, table: str, row: dict) -> None:
        if table in APPEND_ONLY:
            self.buffers.setdefault(table, []).append(row)
        else:
            key = tuple(row[c] for c in self.db.pk[table])
            self.buffers.setdefault(table, {})[key] = row

    def flush(self) -> None:
        for table in PG_TABLES:
            rows = self._take(table)
            if rows:
                self._write_pg(table, rows)
        self.db.pg.commit()
        for table in MY_TABLES:
            rows = self._take(table)
            if rows:
                self._write_my(table, rows)
        self.db.my.commit()

    def _take(self, table: str) -> list[dict]:
        buf = self.buffers.pop(table, None)
        if not buf:
            return []
        rows = buf if isinstance(buf, list) else list(buf.values())
        self.rows_written[table] = self.rows_written.get(table, 0) + len(rows)
        return rows

    def _write_pg(self, table: str, rows: list[dict]) -> None:
        cols = list(rows[0].keys())
        jsonb = self.db.jsonb.get(table, set())
        with self.db.pg.cursor() as cur:
            target = table
            if table not in APPEND_ONLY:
                target = "tmp_" + table.replace(".", "_")
                cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {target} (LIKE {table} INCLUDING DEFAULTS)")
                cur.execute(f"TRUNCATE {target}")
            with cur.copy(f"COPY {target} ({', '.join(cols)}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row([json.dumps(row[c], ensure_ascii=False) if c in jsonb else row[c] for c in cols])
            if table not in APPEND_ONLY:
                cur.execute(self.db.pg_upsert_sql(table, cols, f"SELECT {', '.join(cols)} FROM {target}"))

    def _write_my(self, table: str, rows: list[dict]) -> None:
        cols = list(rows[0].keys())
        with self.db.my.cursor() as cur:
            cur.executemany(self.db.my_sql(table, cols), [tuple(_naive_utc(r[c]) for c in cols) for r in rows])

    def finish(self) -> None:
        self.flush()
        self._sync_sequences()

    def _sync_sequences(self) -> None:
        """Rows were inserted with explicit ids; move identity sequences past them."""
        with self.db.pg.cursor() as cur:
            cur.execute("""SELECT table_schema, table_name, column_name FROM information_schema.columns
                           WHERE is_identity = 'YES' AND table_schema <> 'public'""")
            for schema, table, column in cur.fetchall():
                cur.execute(f"""SELECT setval(pg_get_serial_sequence('{schema}.{table}', '{column}'),
                                COALESCE((SELECT max({column}) FROM {schema}.{table}), 1),
                                (SELECT max({column}) FROM {schema}.{table}) IS NOT NULL)""")
        self.db.pg.commit()

    def close(self) -> None:
        self.db.close()


class LiveSink:
    """Writes each change immediately (one transaction per commit() call of the live loop)."""

    def __init__(self, settings: Settings):
        self.db = _Databases(settings)
        self.pending: list[tuple[str, dict]] = []
        self.rows_written: dict[str, int] = {}

    def upsert(self, table: str, row: dict) -> None:
        self.pending.append((table, row))

    def flush(self) -> None:
        if not self.pending:
            return
        ops, self.pending = self.pending, []
        with self.db.pg.cursor() as pg, self.db.my.cursor() as my:
            for table, row in ops:
                cols = list(row.keys())
                if table.startswith("oms."):
                    my.execute(self.db.my_sql(table, cols), tuple(_naive_utc(row[c]) for c in cols))
                else:
                    jsonb = self.db.jsonb.get(table, set())
                    values = ", ".join("%s::jsonb" if c in jsonb else "%s" for c in cols)
                    params = [json.dumps(row[c], ensure_ascii=False) if c in jsonb else row[c] for c in cols]
                    if table in APPEND_ONLY:
                        pg.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({values})", params)
                    else:
                        pg.execute(self.db.pg_upsert_sql(table, cols, f"VALUES ({values})"), params)
                self.rows_written[table] = self.rows_written.get(table, 0) + 1
        self.db.pg.commit()
        self.db.my.commit()

    def finish(self) -> None:
        self.flush()

    def close(self) -> None:
        self.db.close()


def max_ids(settings: Settings) -> dict[str, int]:
    """Current max id per id-keyed table, used to continue numbering in live mode."""
    db = _Databases(settings)
    result = {}
    try:
        with db.pg.cursor() as cur:
            for table in PG_TABLES:
                pk = db.pk[table]
                if len(pk) == 1 and pk[0].endswith("_id"):
                    cur.execute(f"SELECT COALESCE(max({pk[0]}), 0) FROM {table}")
                    result[table] = cur.fetchone()[0]
        with db.my.cursor() as cur:
            for table in MY_TABLES:
                pk = db.pk[table]
                if len(pk) == 1:
                    cur.execute(f"SELECT COALESCE(max({pk[0]}), 0) FROM {table}")
                    result[table] = cur.fetchone()[0]
    finally:
        db.close()
    return result
