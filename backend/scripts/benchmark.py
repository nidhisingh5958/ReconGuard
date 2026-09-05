"""Benchmark the deterministic engine and evaluate it against ground truth.

    python -m scripts.benchmark
    python -m scripts.benchmark --sizes 500 1000 10000 --repeat 3

Reports measured throughput and, for messy datasets, precision and recall per
anomaly class. Nothing here is hardcoded: every figure comes from a real run.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.money import format_inr  # noqa: E402
from app.domain.sources import SourceDataset  # noqa: E402
from app.services.ingestion.generator import (  # noqa: E402
    GeneratorConfig,
    SyntheticDataGenerator,
)
from app.services.ingestion.loader import (  # noqa: E402
    bank_from_dict,
    ground_truth_from_dict,
    invoice_from_dict,
    order_from_dict,
    settlement_from_dict,
)
from app.services.reconciliation.engine import ReconciliationEngine  # noqa: E402

#: Which reason code(s) each injected anomaly class must cause the engine to
#: raise. Most map one-to-one. UNRECOGNISED_REFERENCE_FORMAT maps to TWO codes
#: because one unparseable narration produces two residuals: the payout is left
#: without its cash, and the credit is left without its payout. Counting it
#: against a single code would understate precision on both.
ANOMALY_TO_REASON_CODES = {
    "MISSING_SETTLEMENT": ("MISSING_SETTLEMENT",),
    "DUPLICATE_SETTLEMENT": ("DUPLICATE_SETTLEMENT",),
    "MISSING_BANK_TRANSACTION": ("MISSING_BANK_TRANSACTION",),
    "DUPLICATE_BANK_TRANSACTION": ("DUPLICATE_BANK_TRANSACTION",),
    "INVOICE_TYPO": ("INVOICE_TYPO_RESOLVED",),
    "CUSTOMER_NAME_ALIAS": ("COUNTERPARTY_ALIAS_RESOLVED",),
    "DATE_FORMAT_DIFFERENCE": ("DATE_FORMAT_NORMALIZED",),
    "ROUNDING_ERROR": ("ROUNDING_TOLERANCE_APPLIED",),
    "PARTIAL_REFUND": ("PARTIAL_REFUND",),
    "NETTED_REFUND": ("REFUND_NETTED",),
    "AGGREGATED_SETTLEMENT": ("AGGREGATED_SETTLEMENT",),
    "SPLIT_SETTLEMENT": ("SPLIT_SETTLEMENT",),
    "DELAYED_SETTLEMENT": ("DELAYED_SETTLEMENT",),
    "CHARGEBACK": ("CHARGEBACK",),
    "TDS_DISCREPANCY": ("TDS_MISMATCH",),
    "GST_DISCREPANCY": ("GST_MISMATCH",),
    "TRUNCATED_BANK_REFERENCE": ("TRUNCATED_BANK_REFERENCE",),
    "UNKNOWN_BANK_CREDIT": ("UNKNOWN_BANK_CREDIT",),
    "UNRECOGNISED_REFERENCE_FORMAT": (
        "MISSING_BANK_TRANSACTION",
        "UNKNOWN_BANK_CREDIT",
    ),
}


def expected_code_counts(truth):
    """Expected occurrences per reason code, summed across anomaly classes."""
    expected = {}
    for anomaly, count in truth.items():
        for code in ANOMALY_TO_REASON_CODES[anomaly]:
            expected[code] = expected.get(code, 0) + count
    return expected


def build(count: int, seed: int, mode: str) -> SourceDataset:
    generated = SyntheticDataGenerator(
        GeneratorConfig(order_count=count, seed=seed, mode=mode)
    ).generate()
    return SourceDataset(
        orders=[order_from_dict(r) for r in generated.orders],
        settlements=[settlement_from_dict(r) for r in generated.settlements],
        bank_transactions=[bank_from_dict(r) for r in generated.bank_transactions],
        invoices=[invoice_from_dict(r) for r in generated.invoices],
        ground_truth=[ground_truth_from_dict(r) for r in generated.ground_truth],
        dataset_id=f"{mode}-{count}",
        mode=mode,
        seed=seed,
    )


def benchmark(sizes: List[int], seed: int, repeat: int) -> None:
    print("=" * 78)
    print("THROUGHPUT (deterministic engine, no LLM)")
    print("=" * 78)
    header = (
        f"{'records':>8}  {'source rows':>12}  {'best ms':>9}  {'rec/sec':>10}  "
        f"{'match rate':>11}  {'residuals':>10}"
    )
    print(header)
    print("-" * 78)
    for size in sizes:
        dataset = build(size, seed, "messy")
        best = None
        metrics = None
        for _ in range(repeat):
            output = ReconciliationEngine().run(dataset, run_id="BENCH")
            if best is None or output.metrics.processing_time_ms < best:
                best = output.metrics.processing_time_ms
                metrics = output.metrics
        rps = metrics.records_processed / (best / 1000.0)
        print(
            f"{metrics.records_processed:>8}  {metrics.total_source_records:>12}  "
            f"{best:>9.1f}  {rps:>10.0f}  {metrics.match_rate:>10.2%}  "
            f"{metrics.residuals:>10}"
        )


def evaluate(count: int, seed: int) -> None:
    dataset = build(count, seed, "messy")
    output = ReconciliationEngine().run(dataset, run_id="EVAL")
    truth = Counter(a.anomaly_type for a in dataset.ground_truth)
    detected = Counter(
        code.value for result in output.results for code in result.reason_codes
    )

    print()
    print("=" * 78)
    print(f"GROUND TRUTH EVALUATION ({count} orders, seed {seed})")
    print("=" * 78)
    print(f"{'reason code':<32}{'expected':>9}{'detected':>10}{'precision':>11}{'recall':>9}")
    print("-" * 78)
    expected = expected_code_counts(truth)
    total_tp = total_expected = total_detected = 0
    for code in sorted(expected):
        want = expected[code]
        found = detected.get(code, 0)
        tp = min(want, found)
        precision = (tp / found) if found else 0.0
        recall = (tp / want) if want else 0.0
        total_tp += tp
        total_expected += want
        total_detected += found
        print(f"{code:<32}{want:>9}{found:>10}{precision:>10.1%}{recall:>9.1%}")
    print("-" * 78)
    overall_p = (total_tp / total_detected) if total_detected else 0.0
    overall_r = (total_tp / total_expected) if total_expected else 0.0
    print(
        f"{'OVERALL':<32}{total_expected:>9}{total_detected:>10}"
        f"{overall_p:>10.1%}{overall_r:>9.1%}"
    )

    m = output.metrics
    print()
    print("RUN METRICS (measured)")
    print(f"  records processed     {m.records_processed}")
    print(f"  deterministic matches {m.deterministic_matches}")
    print(f"  partial matches       {m.partial_matches}")
    print(f"  review required       {m.review_required}")
    print(f"  duplicates            {m.duplicates}")
    print(f"  exceptions            {m.exceptions}")
    print(f"  unresolved            {m.unresolved}")
    print(f"  match rate            {m.match_rate:.2%}")
    print(f"  exception rate        {m.exception_rate:.2%}")
    print(f"  total reconciled      {format_inr(m.total_reconciled_paisa)}")
    print(f"  unexplained value     {format_inr(m.unexplained_value_paisa)}")
    print(f"  audit events written  {len(output.audit_events)}")

    clean = ReconciliationEngine().run(build(count, seed, "clean"), run_id="CLEAN")
    print()
    print("CLEAN-MODE CONTROL (a correct engine must score 100%)")
    print(f"  match rate            {clean.metrics.match_rate:.2%}")
    print(f"  residuals             {clean.metrics.residuals}")


def main() -> int:
    parser = argparse.ArgumentParser(description="ReconGuard engine benchmark")
    parser.add_argument("--sizes", type=int, nargs="+", default=[500, 1000, 10000])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--eval-size", type=int, default=500)
    args = parser.parse_args()

    benchmark(args.sizes, args.seed, args.repeat)
    evaluate(args.eval_size, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
