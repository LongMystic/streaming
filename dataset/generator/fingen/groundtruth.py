"""Facts only the simulator knows. Written to files, never to the databases."""
from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


class GroundTruth:
    def __init__(self):
        self.patterns: list[dict] = []
        self.news: list[dict] = []
        self.disclosures: list[dict] = []
        self.margin_calls: list[dict] = []
        self.rag_qa: list[dict] = []

    def pattern(self, pattern_id: int, pattern_type: str, customer_ids: list[int], days, notes: str) -> None:
        self.patterns.append({"pattern_id": pattern_id, "pattern_type": pattern_type, "customer_ids": customer_ids,
                              "dates": [str(d) for d in days], "notes": notes})

    def write(self, out_dir: Path, engine) -> dict[str, int]:
        out_dir.mkdir(parents=True, exist_ok=True)
        customers = [{
            "customer_id": c.customer_id, "segment": c.segment, "order_rate_per_day": round(c.order_rate, 4),
            "wealth_vnd": c.wealth, "risk_appetite": c.risk_appetite,
            "churn_date": str(c.churn_date) if c.churn_date else None,
            "fraud_pattern": c.fraud_pattern, "fraud_group": c.fraud_group,
        } for c in engine.customers]
        tables = {"customer_hidden_profile": customers, "injected_patterns": self.patterns,
                  "news_sentiment_truth": self.news, "disclosure_extraction_truth": self.disclosures,
                  "margin_call_context": self.margin_calls}
        counts = {}
        for name, rows in tables.items():
            if rows:
                normalized = [{k: (str(v) if hasattr(v, "isoformat") else v) for k, v in row.items()} for row in rows]
                pq.write_table(pa.Table.from_pylist(normalized), out_dir / f"{name}.parquet")
            counts[name] = len(rows)
        with open(out_dir / "rag_qa.jsonl", "w", encoding="utf-8") as f:
            for row in self.rag_qa:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        counts["rag_qa"] = len(self.rag_qa)
        return counts
