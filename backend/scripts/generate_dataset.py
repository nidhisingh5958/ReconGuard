"""Generate a synthetic dataset.

    python -m scripts.generate_dataset --messy
    python -m scripts.generate_dataset --clean --count 500
    python -m scripts.generate_dataset --messy --count 10000 --seed 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.money import format_inr  # noqa: E402
from app.services.reconciliation import runner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="ReconGuard synthetic data generator")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--clean", action="store_true", help="perfectly reconciling data")
    mode.add_argument(
        "--messy", action="store_true", help="inject 18 labelled anomaly classes"
    )
    parser.add_argument("--count", type=int, default=500, help="number of orders")
    parser.add_argument("--seed", type=int, default=42, help="deterministic seed")
    parser.add_argument("--dataset-id", default=None, help="output directory name")
    args = parser.parse_args()

    selected = "clean" if args.clean else "messy"
    dataset_id = args.dataset_id or (
        runner.DEFAULT_DATASET_ID
        if (selected == "messy" and args.count == 500 and args.seed == 42)
        else f"{selected}-{args.count}"
    )

    dataset_id, manifest, path = runner.generate_dataset(
        order_count=args.count, seed=args.seed, mode=selected, dataset_id=dataset_id
    )

    print(f"dataset      {dataset_id}  ({selected}, seed {args.seed})")
    print(f"written to   {path}")
    print(f"orders       {manifest['order_count']}")
    print(f"settlements  {manifest['settlement_count']}")
    print(f"bank rows    {manifest['bank_transaction_count']}")
    print(f"invoices     {manifest['invoice_count']}")
    print(f"total source {manifest['total_source_records']} records")
    print(f"anomalies    {manifest['anomaly_count']} labelled in ground_truth.json")

    import json

    gt_path = path / "ground_truth.json"
    if gt_path.exists():
        with gt_path.open(encoding="utf-8") as handle:
            breakdown = runner.anomaly_breakdown(json.load(handle))
        if breakdown:
            print("\nanomaly mix")
            for name, count in breakdown.items():
                print(f"  {name:<28} {count:>4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
