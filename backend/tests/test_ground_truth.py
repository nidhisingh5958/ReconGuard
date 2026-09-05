"""Ground-truth evaluation of the whole pipeline.

The synthetic generator labels every anomaly it injects. These tests replay the
generated data through ingestion, normalization and the engine, then check the
engine's conclusions against those labels. This is the measurement that makes
the match rate meaningful: without it, a high number could just mean the engine
is quietly calling everything matched.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from app.domain.sources import SourceDataset
from app.services.ingestion.generator import (
    ANOMALY_MIX,
    GeneratorConfig,
    SyntheticDataGenerator,
)
from app.services.ingestion.loader import (
    bank_from_dict,
    ground_truth_from_dict,
    invoice_from_dict,
    order_from_dict,
    settlement_from_dict,
)
from app.services.reconciliation.engine import ReconciliationEngine

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


def to_dataset(generated, mode="messy") -> SourceDataset:
    """Round-trip through the loader so serialisation is exercised too."""
    return SourceDataset(
        orders=[order_from_dict(r) for r in generated.orders],
        settlements=[settlement_from_dict(r) for r in generated.settlements],
        bank_transactions=[bank_from_dict(r) for r in generated.bank_transactions],
        invoices=[invoice_from_dict(r) for r in generated.invoices],
        ground_truth=[ground_truth_from_dict(r) for r in generated.ground_truth],
        dataset_id="test",
        mode=mode,
        seed=42,
    )


@pytest.fixture(scope="module")
def messy():
    generated = SyntheticDataGenerator(
        GeneratorConfig(order_count=500, seed=42, mode="messy")
    ).generate()
    dataset = to_dataset(generated)
    output = ReconciliationEngine().run(dataset, run_id="RUN-GT")
    return generated, dataset, output


@pytest.fixture(scope="module")
def clean():
    generated = SyntheticDataGenerator(
        GeneratorConfig(order_count=250, seed=7, mode="clean")
    ).generate()
    dataset = to_dataset(generated, mode="clean")
    return generated, dataset, ReconciliationEngine().run(dataset, run_id="RUN-CLEAN")


# --- generator guarantees -------------------------------------------------
def test_generator_is_byte_deterministic():
    a = SyntheticDataGenerator(GeneratorConfig(order_count=200, seed=99)).generate()
    b = SyntheticDataGenerator(GeneratorConfig(order_count=200, seed=99)).generate()
    for field in ("orders", "settlements", "bank_transactions", "invoices", "ground_truth"):
        assert json.dumps(getattr(a, field)) == json.dumps(getattr(b, field)), field


def test_a_different_seed_produces_different_data():
    a = SyntheticDataGenerator(GeneratorConfig(order_count=200, seed=1)).generate()
    b = SyntheticDataGenerator(GeneratorConfig(order_count=200, seed=2)).generate()
    assert json.dumps(a.orders) != json.dumps(b.orders)


def test_clean_mode_injects_no_anomalies(clean):
    generated, _, _ = clean
    assert generated.ground_truth == []


def test_every_anomaly_class_in_the_mix_is_generated(messy):
    generated, _, _ = messy
    produced = {row["anomaly_type"] for row in generated.ground_truth}
    expected = {anomaly.value for anomaly, _ in ANOMALY_MIX}
    assert produced == expected
    assert len(expected) == 19
    # Every generated class must have a declared expectation, or the
    # ground-truth evaluation would silently skip it.
    assert produced <= set(ANOMALY_TO_REASON_CODES)


def test_money_is_integer_paise_everywhere_on_disk(messy):
    generated, _, _ = messy
    for row in generated.orders:
        assert isinstance(row["gross_amount"], int)
        assert isinstance(row["refund_amount"], int)
    for row in generated.settlements:
        for key in ("gross_amount", "gateway_fee", "gst_on_fee", "tds", "net_amount"):
            assert isinstance(row[key], int), f"{key} must be integer paise"
    for row in generated.bank_transactions:
        assert isinstance(row["credit_amount"], int)
        assert isinstance(row["balance"], int)


# --- clean mode is the regression net -------------------------------------
def test_clean_mode_reconciles_perfectly(clean):
    _, _, output = clean
    metrics = output.metrics
    assert metrics.match_rate == 1.0, (
        "clean mode must reconcile 100%; anything less is an engine bug, "
        "not a data problem"
    )
    assert metrics.residuals == 0
    assert metrics.exceptions == 0
    assert metrics.unexplained_value_paisa == 0


# --- messy mode against the labels ----------------------------------------
def test_every_anomaly_class_is_detected_with_full_precision_and_recall(messy):
    generated, _, output = messy
    truth = Counter(row["anomaly_type"] for row in generated.ground_truth)
    detected = Counter(
        code.value for result in output.results for code in result.reason_codes
    )
    failures = []
    for code, want in sorted(expected_code_counts(truth).items()):
        actual = detected.get(code, 0)
        if actual != want:
            failures.append(f"{code}: expected {want}, got {actual}")
    assert not failures, "ground-truth mismatch:\n" + "\n".join(failures)


def _locate(output, row):
    """Find the reconciliation record a ground-truth label should land on.

    The label says which record carries the detection via ``detected_on``,
    because it is not always the order: a refund netted into an unrelated
    payout is labelled against the refunded order but detected on the host
    settlement, and an unidentified credit has no order at all.
    """
    target = row.get("detected_on", "order")
    if target == "bank":
        return next(
            (
                r
                for r in output.results
                if row["bank_transaction_id"] in (r.bank_transaction_ids or [])
            ),
            None,
        )
    if target == "settlement":
        return next(
            (
                r
                for r in output.results
                if row["settlement_id"] in (r.settlement_ids or [])
            ),
            None,
        )
    return next((r for r in output.results if r.order_id == row["order_id"]), None)


def test_each_labelled_anomaly_lands_on_its_own_record(messy):
    """Recall at the record level, not just in aggregate counts."""
    generated, _, output = messy
    misses = []
    for row in generated.ground_truth:
        codes = ANOMALY_TO_REASON_CODES[row["anomaly_type"]]
        result = _locate(output, row)
        if result is None:
            misses.append(f"{row['anomaly_id']} {row['anomaly_type']}: no record")
            continue
        raised = [c.value for c in result.reason_codes]
        # A class mapping to several codes raises them on different records;
        # the located record must carry at least one of them.
        if not any(code in raised for code in codes):
            misses.append(
                f"{row['anomaly_id']} {row['anomaly_type']} on "
                f"{result.reconciliation_id}: none of {list(codes)} raised, got "
                f"{raised}"
            )
    assert not misses, "per-record recall failures:\n" + "\n".join(misses)


def test_expected_status_matches_for_every_labelled_anomaly(messy):
    generated, _, output = messy
    mismatches = []
    for row in generated.ground_truth:
        result = _locate(output, row)
        if result is None:
            continue
        if result.status.value != row["expected_status"]:
            mismatches.append(
                f"{row['anomaly_type']} on {result.reconciliation_id}: expected "
                f"{row['expected_status']}, got {result.status.value}"
            )
    assert not mismatches, "status mismatches:\n" + "\n".join(mismatches)


def test_match_rate_emerges_from_the_data_and_is_plausible(messy):
    _, _, output = messy
    metrics = output.metrics
    # The rate is whatever the data produces. We assert only that it sits in a
    # sane band, never a hardcoded figure.
    assert 0.85 <= metrics.match_rate <= 0.98
    assert 25 <= metrics.residuals <= 75
    assert metrics.deterministic_matches + metrics.partial_matches + metrics.residuals == (
        metrics.records_processed
    )


def test_no_matched_record_carries_unexplained_value(messy):
    _, _, output = messy
    for result in output.results:
        if result.is_matched:
            assert result.unexplained_value_paisa == 0


def test_every_residual_is_explained(messy):
    """The engine must never emit a residual it cannot account for."""
    _, _, output = messy
    for result in output.results:
        if not result.is_matched:
            assert result.reason_codes, result.reconciliation_id
            assert result.evidence, result.reconciliation_id


def test_run_is_reproducible(messy):
    """Two runs over identical input must agree exactly, ids included."""
    _, dataset, output = messy
    again = ReconciliationEngine().run(dataset, run_id="RUN-GT")
    assert [r.reconciliation_id for r in again.results] == [
        r.reconciliation_id for r in output.results
    ]
    assert [r.status for r in again.results] == [r.status for r in output.results]
    assert again.metrics.match_rate == output.metrics.match_rate
    assert again.metrics.deterministic_matches == output.metrics.deterministic_matches


def test_engine_scales_without_quadratic_blowup():
    """20x the records must not cost anything like 400x the time."""
    small = to_dataset(
        SyntheticDataGenerator(GeneratorConfig(order_count=500, seed=5)).generate()
    )
    large = to_dataset(
        SyntheticDataGenerator(GeneratorConfig(order_count=10_000, seed=5)).generate()
    )
    small_ms = ReconciliationEngine().run(small).metrics.processing_time_ms
    large_ms = ReconciliationEngine().run(large).metrics.processing_time_ms
    # Quadratic would be ~400x. Allow generous headroom for a loaded CI box.
    assert large_ms < small_ms * 60, f"{small_ms:.1f}ms -> {large_ms:.1f}ms"
