"""CLI: python -m fingen {backfill,live,reset} ..."""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from datetime import timedelta

from .calendar_vn import first_trading_day_on_or_after, next_trading_day, vn_time
from .config import OUTPUT_DIR, PRESETS, load_settings
from .sinks import MY_TABLES, PG_TABLES, BulkSink, LiveSink, max_ids

STATE_FILE = OUTPUT_DIR / "state.pkl"


def _summary(rows: dict[str, int]) -> str:
    keys = ["customer.customers", "oms.orders", "oms.order_events", "oms.executions", "ledger.cash_transactions",
            "custody.settlement_instructions", "margin.loans", "margin.margin_calls", "compliance.aml_alerts",
            "crm.support_tickets", "content.news_articles"]
    return ", ".join(f"{k.split('.')[1]}={rows.get(k, 0):,}" for k in keys)


def cmd_backfill(args) -> None:
    from .engine import Engine
    preset = PRESETS[args.preset]
    settings = load_settings()
    sink = BulkSink(settings)
    existing = {t: n for t, n in max_ids(settings).items() if n}
    if existing:
        sys.exit(f"Target tables are not empty ({len(existing)} tables). Run `python -m fingen reset` first.")
    started = time.time()
    engine = Engine(preset, args.seed, sink)
    print(f"[backfill] preset {preset.name}: {preset.customers:,} customers, {preset.start} -> {preset.end}")
    engine.build_world()
    engine.schedule_day(first_trading_day_on_or_after(preset.start))
    end = vn_time(preset.end, 23, 59, 59)
    day = None
    while engine.heap and engine.heap[0][0] <= end:
        nxt = engine.heap[0][0]
        engine.run_until(nxt)
        if engine.day != day:
            day = engine.day
            print(f"  {day}  open orders={len(engine.open_orders):,}  "
                  f"elapsed={time.time() - started:,.0f}s", end="\r", flush=True)
    sink.finish()
    print()
    gt = engine.gt.write(OUTPUT_DIR / "ground_truth", engine)
    sink.close()
    with open(STATE_FILE, "wb") as f:
        pickle.dump(engine, f)
    print(f"[backfill] done in {time.time() - started:,.0f}s: {_summary(sink.rows_written)}")
    print(f"[backfill] ground truth: {json.dumps(gt)} -> {OUTPUT_DIR / 'ground_truth'}")
    print(f"[backfill] state saved to {STATE_FILE} (needed by `live`)")


def cmd_live(args) -> None:
    if not STATE_FILE.exists():
        sys.exit("No saved state. Run `python -m fingen backfill` first.")
    with open(STATE_FILE, "rb") as f:
        engine = pickle.load(f)
    settings = load_settings()
    db_ids = max_ids(settings)
    stale = [t for t, n in engine.ids.items() if t in db_ids and db_ids[t] != n]
    if stale:
        sys.exit(f"Database does not match the saved state ({stale[:3]}...). Reset and backfill again.")
    engine.sink = LiveSink(settings)
    engine.live = True
    if not args.no_kafka:
        from confluent_kafka import Producer
        engine.kafka = Producer({"bootstrap.servers": settings.kafka_bootstrap, "linger.ms": 50})
    if engine.last_day_scheduled is None or engine.last_day_scheduled <= engine.day:
        engine.schedule_day(next_trading_day(engine.day))
    sim = engine.heap[0][0] - timedelta(seconds=1)
    print(f"[live] simulated clock starts at {sim:%Y-%m-%d %H:%M:%S}Z, speed x{args.speed}, "
          f"kafka={'off' if args.no_kafka else settings.kafka_bootstrap}. Ctrl+C to stop.")
    wall = time.monotonic()
    last_report = wall
    stop_at = wall + args.duration if args.duration else None
    try:
        while stop_at is None or time.monotonic() < stop_at:
            now = time.monotonic()
            sim += timedelta(seconds=(now - wall) * args.speed)
            wall = now
            if engine.heap and engine.heap[0][0] - sim > timedelta(minutes=10):
                sim = engine.heap[0][0] - timedelta(seconds=1)   # skip idle periods (nights, lunch break)
            engine.run_until(sim)
            engine.sink.flush()
            if engine.kafka is not None:
                engine.kafka.poll(0)
            if now - last_report > 10:
                last_report = now
                print(f"  sim {sim:%Y-%m-%d %H:%M:%S}Z  {_summary(engine.sink.rows_written)}", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        engine.sink.finish()
        if engine.kafka is not None:
            engine.kafka.flush(10)
        rows = engine.sink.rows_written
        engine.sink.close()
        with open(STATE_FILE, "wb") as f:
            pickle.dump(engine, f)
        print(f"\n[live] stopped; state saved. Rows written: {_summary(rows)}")


def cmd_reset(args) -> None:
    import psycopg
    import pymysql
    settings = load_settings()
    with psycopg.connect(settings.pg_conninfo()) as pg:
        pg.execute(f"TRUNCATE {', '.join(PG_TABLES)} RESTART IDENTITY CASCADE")
    my = pymysql.connect(host=settings.my_host, port=settings.my_port, user=settings.my_user,
                         password=settings.my_password, database=settings.my_db)
    with my.cursor() as cur:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in MY_TABLES:
            cur.execute(f"TRUNCATE {table}")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    my.close()
    STATE_FILE.unlink(missing_ok=True)
    print("[reset] all dataset tables truncated, saved state removed")


def main() -> None:
    parser = argparse.ArgumentParser(prog="fingen", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backfill", help="build the world and simulate the preset's history")
    b.add_argument("--preset", choices=list(PRESETS), default="S")
    b.add_argument("--seed", type=int, default=42)
    b.set_defaults(func=cmd_backfill)
    lv = sub.add_parser("live", help="continue the simulation in (accelerated) real time")
    lv.add_argument("--speed", type=float, default=60.0, help="simulated seconds per wall-clock second")
    lv.add_argument("--no-kafka", action="store_true", help="do not produce marketdata.ticks / app.clickstream")
    lv.add_argument("--duration", type=float, default=0, help="stop after this many wall-clock seconds (0 = run until Ctrl+C)")
    lv.set_defaults(func=cmd_live)
    rs = sub.add_parser("reset", help="truncate every dataset table")
    rs.set_defaults(func=cmd_reset)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
