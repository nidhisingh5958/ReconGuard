"""The self-healing loop: induce, validate by replay, promote, re-run.

The claim this module has to earn is that promoting a rule actually changes
what the engine matches, and that a rule can only get there through measured
evidence and a named human.
"""

from __future__ import annotations

import pytest

from app.domain.enums import ReconciliationStatus
from app.services.ingestion.generator import (
    UNRECOGNISED_REFERENCE_MARKER,
    GeneratorConfig,
    SyntheticDataGenerator,
)
from app.services.reconciliation.engine import ReconciliationEngine
from app.services.rules.dynamic import (
    DynamicRuleSet,
    ReferenceExtractionRule,
    validate_reference_rule,
)
from app.services.rules.proposal import ReferenceSample, propose_reference_rules
from app.services.rules.validator import (
    VERDICT_IMPROVES,
    VERDICT_INVALID,
    VERDICT_NEUTRAL,
    validate_rule,
)
from tests.test_ground_truth import to_dataset

GOOD_PATTERN = r"PGWX\s+99(\d{5})"
GOOD_MARKER = "PGWX"


@pytest.fixture(scope="module")
def dataset():
    return to_dataset(
        SyntheticDataGenerator(
            GeneratorConfig(order_count=500, seed=42, mode="messy")
        ).generate()
    )


# --- dynamic rule safety --------------------------------------------------
def test_a_valid_rule_extracts_the_settlement_key():
    rule = ReferenceExtractionRule("R1", "acquirer", GOOD_PATTERN, GOOD_MARKER)
    assert rule.extract("ACH CR PGWX 9910291 MERCHANT ACCT") == "10291"


def test_a_rule_does_not_fire_without_its_marker():
    rule = ReferenceExtractionRule("R1", "acquirer", GOOD_PATTERN, GOOD_MARKER)
    assert rule.extract("NEFT 9910291 SALARY CREDIT") is None


def test_an_unanchored_pattern_is_rejected():
    """Without a marker the pattern would claim every number on the statement."""
    problems = validate_reference_rule({"pattern": r"(\d{5})", "marker": ""})
    assert problems and "marker is required" in problems[0]


def test_a_pattern_with_the_wrong_group_count_is_rejected():
    problems = validate_reference_rule(
        {"pattern": r"(A)(\d{5})", "marker": GOOD_MARKER}
    )
    assert any("exactly one capturing group" in p for p in problems)


def test_a_pattern_that_does_not_compile_is_rejected():
    problems = validate_reference_rule({"pattern": r"([0-9", "marker": GOOD_MARKER})
    assert any("does not compile" in p for p in problems)


def test_an_unsafe_rule_is_never_loaded_into_a_rule_set():
    class Row:
        rule_type = "REFERENCE_EXTRACTION"
        rule_id = "R-BAD"
        name = "bad"
        parameters = {"pattern": r"(\d{5})", "marker": ""}

    assert DynamicRuleSet.from_rows([Row()]).reference_rules == []


# --- induction ------------------------------------------------------------
def test_a_pattern_is_induced_from_repeated_pairings():
    samples = [
        ReferenceSample(f"REC-{i}", f"ACH CR//PGWX/9910{i:03d}/MERCHANT ACCT", f"10{i:03d}")
        for i in range(3)
    ]
    proposals = propose_reference_rules(samples, controls=["RAZORPAY SETTLEMENT SET-10291"])
    assert len(proposals) == 1
    assert proposals[0].marker == GOOD_MARKER
    assert proposals[0].support == 3
    rule = ReferenceExtractionRule(
        "R", "x", proposals[0].pattern, proposals[0].marker
    )
    assert rule.extract("ACH CR PGWX 9910007 MERCHANT ACCT") == "10007"


def test_one_coincidence_is_not_a_format():
    samples = [
        ReferenceSample("REC-1", "ACH CR//PGWX/9910032/MERCHANT ACCT", "10032"),
        ReferenceSample("REC-2", "ACH CR//PGWX/9910079/MERCHANT ACCT", "10079"),
    ]
    assert propose_reference_rules(samples, min_support=3) == []


def test_a_pattern_that_would_claim_a_control_narration_is_discarded():
    """A rule must not compete with narrations the base engine already parses."""
    samples = [
        ReferenceSample(f"REC-{i}", f"INWARD CLEARING CHQ 44712{i}", f"44712{i}")
        for i in range(4)
    ]
    assert propose_reference_rules(samples, controls=["INWARD CLEARING CHQ 447120"]) == []


# --- the gap exists before the rule ---------------------------------------
def test_the_unrecognised_format_is_a_real_gap_for_the_base_engine(dataset):
    """The built-in extractor genuinely cannot parse this narration."""
    output = ReconciliationEngine().run(dataset, run_id="BASE")
    codes = [c.value for r in output.results for c in r.reason_codes]
    unparsed = sum(
        1
        for b in dataset.bank_transactions
        if UNRECOGNISED_REFERENCE_MARKER in b.description
    )
    assert unparsed >= 5, "the dataset must actually contain the gap"
    # Each unparsed credit costs one missing-bank-transaction and one orphan.
    assert codes.count("MISSING_BANK_TRANSACTION") >= unparsed
    assert codes.count("UNKNOWN_BANK_CREDIT") >= unparsed


# --- validation by replay -------------------------------------------------
def test_replay_measures_a_real_improvement_with_no_regressions(dataset):
    report = validate_rule(
        dataset, "RULE-DYN-TEST", {"pattern": GOOD_PATTERN, "marker": GOOD_MARKER}
    )
    assert report.verdict == VERDICT_IMPROVES
    assert report.approved
    assert report.match_delta > 0
    assert report.residual_delta < 0
    assert report.regressions == []
    assert report.detail["unexplained_delta_paisa"] < 0
    assert len(report.improvements) == report.match_delta


def test_a_rule_that_changes_nothing_is_neutral_not_approved(dataset):
    report = validate_rule(
        dataset,
        "RULE-DYN-NOOP",
        {"pattern": r"ZZZQ\s+(\d{5})", "marker": "ZZZQ"},
    )
    assert report.verdict == VERDICT_NEUTRAL
    assert not report.approved
    assert report.match_delta == 0


def test_a_structurally_unsafe_rule_is_invalid_and_never_replayed(dataset):
    report = validate_rule(dataset, "RULE-DYN-BAD", {"pattern": r"(\d+)", "marker": ""})
    assert report.verdict == VERDICT_INVALID
    assert not report.approved
    assert report.detail["structural_errors"]


# --- promotion actually changes the engine --------------------------------
def test_promoting_the_rule_changes_what_the_engine_matches(dataset):
    baseline = ReconciliationEngine().run(dataset, run_id="BASE")
    rule_set = DynamicRuleSet(
        reference_rules=[
            ReferenceExtractionRule("RULE-DYN-001", "acquirer", GOOD_PATTERN, GOOD_MARKER)
        ]
    )
    healed = ReconciliationEngine(rules=rule_set).run(dataset, run_id="HEALED")

    assert healed.metrics.deterministic_matches > baseline.metrics.deterministic_matches
    assert healed.metrics.residuals < baseline.metrics.residuals
    assert healed.metrics.match_rate > baseline.metrics.match_rate

    # Nothing that was matched may stop being matched.
    before = {r.reconciliation_id: r.status for r in baseline.results}
    for result in healed.results:
        previous = before.get(result.reconciliation_id)
        if previous is ReconciliationStatus.MATCHED:
            assert result.status is ReconciliationStatus.MATCHED


def test_a_rule_sourced_match_is_attributed_to_the_rule(dataset):
    rule_set = DynamicRuleSet(
        reference_rules=[
            ReferenceExtractionRule("RULE-DYN-001", "acquirer", GOOD_PATTERN, GOOD_MARKER)
        ]
    )
    output = ReconciliationEngine(rules=rule_set).run(dataset, run_id="HEALED")
    promoted = [
        r
        for r in output.results
        if "PROMOTED_RULE_APPLIED" in [c.value for c in r.reason_codes]
    ]
    assert promoted, "matches recovered by a promoted rule must say so"
    for result in promoted:
        assert "RULE-DYN-001" in result.rule_ids
        assert any(
            "promoted rule RULE-DYN-001" in e.fact for e in result.evidence
        ), "the evidence must name the rule that recovered the key"


def test_a_dynamic_rule_never_overrides_a_proved_built_in_match(dataset):
    """A greedy rule must not be able to steal a bank row from the base engine."""
    greedy = DynamicRuleSet(
        reference_rules=[
            ReferenceExtractionRule(
                "RULE-GREEDY", "greedy", r"SETTLEMENT\s+SET\s+(\d{5})", "SETTLEMENT"
            )
        ]
    )
    baseline = ReconciliationEngine().run(dataset, run_id="BASE")
    with_greedy = ReconciliationEngine(rules=greedy).run(dataset, run_id="GREEDY")

    before = {r.reconciliation_id: r.status for r in baseline.results}
    for result in with_greedy.results:
        if before.get(result.reconciliation_id) is ReconciliationStatus.MATCHED:
            assert result.status is ReconciliationStatus.MATCHED
