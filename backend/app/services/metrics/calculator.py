"""Run metrics.

Every number here is derived from the results of an actual run. Nothing is
hardcoded, sampled or rounded up for presentation. If a metric cannot be
computed from real records it is not reported.

Definitions, stated once so the UI and the docs cannot drift apart:

    match_rate      = deterministic_matches / records_processed
    exception_rate  = (exceptions + unresolved) / records_processed
    throughput      = records_processed / processing_time_seconds
    residuals       = everything that is not MATCHED and not PARTIAL_MATCH,
                      i.e. the rows that need a human or, later, an arbitrator

``records_processed`` counts reconciliation results, which is one per order
plus one per unidentified bank credit. That denominator is deliberate: an
unidentified credit is a record the system had to make a decision about, and
excluding it would flatter the match rate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Sequence

from app.domain.enums import ReconciliationStatus
from app.domain.reconciliation import ReconciliationResult, RunMetrics
from app.domain.sources import SourceDataset


def status_distribution(
    results: Sequence[ReconciliationResult],
) -> Dict[str, int]:
    """Count results by status, always reporting every status including zeros."""
    counts = {status.value: 0 for status in ReconciliationStatus}
    for result in results:
        counts[result.status.value] += 1
    return counts


def reason_code_distribution(
    results: Sequence[ReconciliationResult],
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results:
        for code in result.reason_codes:
            counts[code.value] = counts.get(code.value, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def compute_run_metrics(
    run_id: str,
    results: Sequence[ReconciliationResult],
    dataset: SourceDataset,
    started_at: datetime,
    completed_at: datetime,
    processing_time_ms: float,
    engine_version: str,
) -> RunMetrics:
    counts = status_distribution(results)
    processed = len(results)

    matched = counts[ReconciliationStatus.MATCHED.value]
    partial = counts[ReconciliationStatus.PARTIAL_MATCH.value]
    review = counts[ReconciliationStatus.REVIEW_REQUIRED.value]
    exceptions = counts[ReconciliationStatus.EXCEPTION.value]
    duplicates = counts[ReconciliationStatus.DUPLICATE.value]
    unresolved = counts[ReconciliationStatus.UNRESOLVED.value]
    residuals = review + exceptions + duplicates + unresolved

    total_reconciled = sum(
        r.actual_amount_paisa for r in results if r.status is ReconciliationStatus.MATCHED
    )
    total_variance = sum(abs(r.variance_paisa) for r in results)
    unexplained = sum(r.unexplained_value_paisa for r in results)

    seconds = processing_time_ms / 1000.0
    throughput = (processed / seconds) if seconds > 0 else 0.0

    return RunMetrics(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
        records_processed=processed,
        total_source_records=dataset.record_count(),
        deterministic_matches=matched,
        partial_matches=partial,
        review_required=review,
        exceptions=exceptions,
        duplicates=duplicates,
        unresolved=unresolved,
        residuals=residuals,
        processing_time_ms=processing_time_ms,
        throughput_rps=throughput,
        match_rate=(matched / processed) if processed else 0.0,
        exception_rate=((exceptions + unresolved) / processed) if processed else 0.0,
        total_reconciled_paisa=total_reconciled,
        total_variance_paisa=total_variance,
        unexplained_value_paisa=unexplained,
        engine_version=engine_version,
        dataset_id=dataset.dataset_id,
        dataset_mode=dataset.mode,
    )


def metrics_to_dict(metrics: RunMetrics) -> Dict[str, object]:
    return {
        "run_id": metrics.run_id,
        "started_at": metrics.started_at.isoformat(),
        "completed_at": metrics.completed_at.isoformat(),
        "records_processed": metrics.records_processed,
        "total_source_records": metrics.total_source_records,
        "deterministic_matches": metrics.deterministic_matches,
        "partial_matches": metrics.partial_matches,
        "review_required": metrics.review_required,
        "exceptions": metrics.exceptions,
        "duplicates": metrics.duplicates,
        "unresolved": metrics.unresolved,
        "residuals": metrics.residuals,
        "processing_time_ms": round(metrics.processing_time_ms, 3),
        "throughput_rps": round(metrics.throughput_rps, 2),
        "match_rate": round(metrics.match_rate, 6),
        "exception_rate": round(metrics.exception_rate, 6),
        "total_reconciled_paisa": metrics.total_reconciled_paisa,
        "total_variance_paisa": metrics.total_variance_paisa,
        "unexplained_value_paisa": metrics.unexplained_value_paisa,
        "engine_version": metrics.engine_version,
        "dataset_id": metrics.dataset_id,
        "dataset_mode": metrics.dataset_mode,
    }
