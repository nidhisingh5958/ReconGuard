"""Arbitration, journal proposals, and the verification gate.

The gate is the most important thing in this module. Most of these tests are
adversarial: they hand the verifier a proposal that a confident-but-wrong model
would plausibly produce, and assert it gets rejected.
"""

from __future__ import annotations

import json

import pytest

from app.domain.ai import ArbitrationResult, JournalEntry
from app.domain.enums import ArbitrationDecision, JournalEntryStatus
from app.services.accounting import chart_of_accounts as coa
from app.services.accounting.journal import (
    PERMITTED_ACTIONS,
    JournalBatch,
    JournalBuilder,
    verify_journal_batch,
)
from app.services.ai.candidates import (
    ResidualCandidate,
    ResidualView,
    build_candidates,
    unique_exact_candidate,
)
from app.services.ai.deterministic_arbitrator import DeterministicArbitrator
from app.services.ai.interfaces import (
    NullArbitrator,
    build_residual_case,
    get_arbitrator,
)
from app.services.ai.llm_arbitrator import LLMResidualArbitrator, _clamp_confidence
from app.services.ai.providers import ProviderError, ScriptedProvider, extract_json
from app.services.ai.verification import verify_arbitration


def make_view(
    rid="REC-00001",
    status="EXCEPTION",
    codes=("UNKNOWN_BANK_CREDIT",),
    exposure=500_000,
    value_date="2026-06-10",
    counterparty="UNKNOWN",
    records=("BANK-77001",),
):
    return ResidualView(
        reconciliation_id=rid,
        status=status,
        reason_codes=list(codes),
        expected_amount_paisa=0 if status == "EXCEPTION" else exposure,
        actual_amount_paisa=exposure if status == "EXCEPTION" else 0,
        variance_paisa=exposure,
        exposure_paisa=exposure,
        counterparty=counterparty,
        value_date=value_date,
        source_records=list(records),
    )


def case_for(view, candidates=(), evidence=()):
    return build_residual_case(view, evidence=evidence, candidates=list(candidates))


# --- candidate retrieval --------------------------------------------------
def test_credit_and_receivable_of_the_same_amount_become_candidates():
    credit = make_view("REC-00500", "EXCEPTION", ("UNKNOWN_BANK_CREDIT",), 500_000)
    receivable = make_view(
        "REC-00042", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_000,
        records=("ORD-1", "SET-10291"),
    )
    candidates = build_candidates(credit, [credit, receivable])
    assert len(candidates) == 1
    assert candidates[0].candidate_id == "REC-00042"
    assert candidates[0].amount_matches_exactly


def test_a_different_amount_is_not_a_candidate():
    credit = make_view("REC-00500", exposure=500_000)
    other = make_view(
        "REC-00042", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_001
    )
    assert build_candidates(credit, [credit, other]) == []


def test_a_candidate_outside_the_date_window_is_excluded():
    credit = make_view("REC-00500", exposure=500_000, value_date="2026-06-10")
    far = make_view(
        "REC-00042", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_000,
        value_date="2026-09-30",
    )
    assert build_candidates(credit, [credit, far], date_window_days=7) == []


def test_two_equal_candidates_are_ambiguous_and_resolve_to_none():
    """Ambiguity must never be broken by picking the nearest date."""
    credit = make_view("REC-00500", exposure=500_000)
    a = make_view("REC-00042", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_000)
    b = make_view("REC-00043", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_000)
    candidates = build_candidates(credit, [credit, a, b])
    assert len(candidates) == 2
    assert unique_exact_candidate(candidates) is None


# --- deterministic arbitrator ---------------------------------------------
def test_null_arbitrator_declines_everything():
    result = NullArbitrator().resolve(case_for(make_view()))
    assert result.decision is ArbitrationDecision.UNRESOLVED
    assert result.confidence == 0.0
    assert result.requires_human_review
    assert result.journal_entry is None


def test_default_provider_is_the_null_arbitrator():
    assert get_arbitrator("none").name == "null"
    assert get_arbitrator("").name == "null"


def test_unknown_provider_degrades_to_deterministic_never_to_an_error():
    """A misconfigured provider must not take the system down."""
    assert get_arbitrator("some-provider-that-does-not-exist").name == "deterministic"


def test_unique_exact_pair_resolves():
    credit = make_view("REC-00500", exposure=500_000)
    receivable = make_view(
        "REC-00042", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_000,
        records=("ORD-10042", "SET-10291"),
    )
    case = case_for(credit, build_candidates(credit, [credit, receivable]))
    result, batch = DeterministicArbitrator().resolve_with_journal(case)

    assert result.decision is ArbitrationDecision.RESOLVE
    assert result.confidence == 0.95
    assert "REC-00042" in result.evidence
    assert "SET-10291" in result.evidence
    assert batch is not None
    assert batch.total_paisa == 500_000


def test_ambiguous_candidates_do_not_resolve():
    credit = make_view("REC-00500", exposure=500_000)
    a = make_view("REC-00042", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_000)
    b = make_view("REC-00043", "PARTIAL_MATCH", ("MISSING_BANK_TRANSACTION",), 500_000)
    case = case_for(credit, build_candidates(credit, [credit, a, b]))
    result, _ = DeterministicArbitrator().resolve_with_journal(case)

    assert result.decision is ArbitrationDecision.PROBABLE
    assert "no pairing is asserted" in result.reason


def test_policy_booking_uses_the_engine_amount_not_an_invented_one():
    view = make_view("REC-00099", "EXCEPTION", ("MISSING_SETTLEMENT",), 1_234_567)
    result, batch = DeterministicArbitrator().resolve_with_journal(case_for(view))
    assert result.decision is ArbitrationDecision.PROBABLE
    assert result.proposed_action == "ACCRUE_SETTLEMENT_RECEIVABLE"
    assert batch.total_paisa == 1_234_567
    assert batch.entries[0].debit_account == coa.SETTLEMENT_RECEIVABLE


def test_every_policy_maps_to_a_permitted_action():
    from app.services.ai.deterministic_arbitrator import POLICY_BY_REASON

    for action, *_ in POLICY_BY_REASON.values():
        assert action in PERMITTED_ACTIONS


def test_arbitrator_is_deterministic_across_calls():
    view = make_view("REC-00099", "EXCEPTION", ("MISSING_SETTLEMENT",), 900_000)
    a = DeterministicArbitrator().resolve(case_for(view))
    b = DeterministicArbitrator().resolve(case_for(view))
    assert (a.decision, a.confidence, a.proposed_action, a.reason) == (
        b.decision,
        b.confidence,
        b.proposed_action,
        b.reason,
    )


# --- journal construction and balance -------------------------------------
def test_a_built_batch_balances_and_matches_the_unexplained_amount():
    batch = JournalBuilder().build(
        "REC-1", "PARK_UNIDENTIFIED_CREDIT", 750_000, ["BANK-77001"], 0.8
    )
    verdict = verify_journal_batch(batch)
    assert verdict.accepted
    assert verdict.total_debits_paisa == verdict.total_credits_paisa == 750_000


def test_a_batch_whose_total_differs_from_the_residual_is_rejected():
    """The number is the engine's. A batch that disagrees with it is refused."""
    batch = JournalBuilder().build(
        "REC-1", "PARK_UNIDENTIFIED_CREDIT", 750_000, ["BANK-77001"], 0.8
    )
    batch.expected_total_paisa = 800_000
    verdict = verify_journal_batch(batch)
    assert not verdict.accepted
    assert any("does not equal the unexplained amount" in r for r in verdict.reasons)


def test_an_unknown_account_is_rejected():
    entry = JournalEntry(
        journal_id="JRN-1",
        date=__import__("datetime").date(2026, 6, 1),
        debit_account="9999",
        credit_account=coa.BANK,
        amount_paisa=100,
        description="invented account",
    )
    batch = JournalBatch("JB-1", "REC-1", [entry], expected_total_paisa=100)
    verdict = verify_journal_batch(batch)
    assert not verdict.accepted
    assert any("unknown debit account" in r for r in verdict.reasons)


def test_a_self_referential_entry_is_rejected():
    entry = JournalEntry(
        journal_id="JRN-1",
        date=__import__("datetime").date(2026, 6, 1),
        debit_account=coa.BANK,
        credit_account=coa.BANK,
        amount_paisa=100,
        description="circular",
    )
    batch = JournalBatch("JB-1", "REC-1", [entry], expected_total_paisa=100)
    assert not verify_journal_batch(batch).accepted


def test_a_zero_amount_entry_is_rejected():
    entry = JournalEntry(
        journal_id="JRN-1",
        date=__import__("datetime").date(2026, 6, 1),
        debit_account=coa.BANK,
        credit_account=coa.SUSPENSE,
        amount_paisa=0,
        description="nothing",
    )
    batch = JournalBatch("JB-1", "REC-1", [entry])
    assert not verify_journal_batch(batch).accepted


# --- the verification gate ------------------------------------------------
def _hostile(case, **kwargs):
    defaults = dict(
        residual_id=case.residual_id,
        decision=ArbitrationDecision.RESOLVE,
        confidence=0.99,
        reason="I am very confident.",
        evidence=list(case.source_records),
        proposed_action="PARK_UNIDENTIFIED_CREDIT",
        requires_human_review=False,
        arbitrator="hostile-test",
    )
    defaults.update(kwargs)
    return ArbitrationResult(**defaults)


def test_a_proposal_citing_a_record_it_was_never_shown_is_rejected():
    case = case_for(make_view())
    outcome = verify_arbitration(case, _hostile(case, evidence=["ORD-99999"]))
    assert not outcome.accepted
    assert outcome.result.decision is ArbitrationDecision.UNRESOLVED
    assert any("outside the residual evidence" in r for r in outcome.reasons)


def test_resolve_without_evidence_is_rejected():
    case = case_for(make_view())
    outcome = verify_arbitration(case, _hostile(case, evidence=[]))
    assert not outcome.accepted
    assert any("requires at least one referenced source record" in r for r in outcome.reasons)


def test_an_action_outside_the_vocabulary_is_rejected():
    case = case_for(make_view())
    outcome = verify_arbitration(
        case, _hostile(case, proposed_action="TRANSFER_TO_MY_ACCOUNT")
    )
    assert not outcome.accepted
    assert any("not in the permitted vocabulary" in r for r in outcome.reasons)


def test_resolve_against_a_non_matching_amount_is_rejected():
    """A model may not pair two sides whose money does not agree."""
    credit = make_view("REC-00500", exposure=500_000)
    near = ResidualCandidate(
        candidate_id="REC-00042",
        kind="UNMATCHED_RECEIVABLE",
        amount_paisa=499_900,
        value_date="2026-06-11",
        counterparty="Acme",
        source_records=["SET-10291"],
        amount_delta_paisa=-100,
        date_delta_days=1,
    )
    case = case_for(credit, [near])
    outcome = verify_arbitration(
        case, _hostile(case, evidence=["BANK-77001", "REC-00042"])
    )
    assert not outcome.accepted
    assert any("differs by" in r for r in outcome.reasons)


def test_a_high_confidence_claim_does_not_survive_a_failed_check():
    """Asserted confidence carries no weight in the gate."""
    case = case_for(make_view())
    outcome = verify_arbitration(
        case, _hostile(case, confidence=1.0, evidence=["FAKE-1"])
    )
    assert not outcome.accepted
    assert outcome.result.confidence == 0.0


def test_a_rejected_proposal_is_downgraded_not_discarded():
    case = case_for(make_view())
    outcome = verify_arbitration(case, _hostile(case, evidence=["ORD-99999"]))
    assert outcome.result.decision is ArbitrationDecision.UNRESOLVED
    assert outcome.result.requires_human_review
    assert "downgraded to UNRESOLVED" in outcome.result.reason
    assert outcome.reasons, "the reasons for rejection must be recorded"


def test_a_well_formed_proposal_passes():
    view = make_view("REC-00099", "EXCEPTION", ("MISSING_SETTLEMENT",), 900_000)
    case = case_for(view)
    result, batch = DeterministicArbitrator().resolve_with_journal(case)
    outcome = verify_arbitration(case, result, batch)
    assert outcome.accepted
    assert outcome.journal_verdict["accepted"]


# --- the LLM path ---------------------------------------------------------
def scripted(response):
    return LLMResidualArbitrator(client=ScriptedProvider([response]))


def test_llm_arbitrator_uses_the_engine_amount_not_the_model_amount():
    """Even if a model states an amount, the batch total comes from the engine."""
    view = make_view("REC-00099", "EXCEPTION", ("MISSING_SETTLEMENT",), 777_777)
    case = case_for(view)
    arb = scripted(
        {
            "decision": "PROBABLE",
            "matched_candidate_id": None,
            "proposed_action": "ACCRUE_SETTLEMENT_RECEIVABLE",
            "confidence": 0.7,
            "reason": "Captured but never settled.",
            "cited_records": ["BANK-77001"],
            "amount_paisa": 999_999_999,
        }
    )
    result, batch = arb.resolve_with_journal(case)
    assert batch.total_paisa == 777_777
    assert result.decision is ArbitrationDecision.PROBABLE


def test_model_confidence_is_capped_below_one():
    """1.00 means proved. No model produces that kind of evidence."""
    assert _clamp_confidence(1.0) == 0.90
    assert _clamp_confidence(5) == 0.90
    assert _clamp_confidence(-3) == 0.0
    assert _clamp_confidence(0.42) == 0.42
    assert _clamp_confidence("not a number") == 0.5


def test_provider_failure_falls_back_to_deterministic_arbitration():
    view = make_view("REC-00099", "EXCEPTION", ("MISSING_SETTLEMENT",), 900_000)
    arb = LLMResidualArbitrator(
        client=ScriptedProvider([ProviderError("503 upstream unavailable")])
    )
    result, batch = arb.resolve_with_journal(case_for(view))
    assert result.decision is ArbitrationDecision.PROBABLE
    assert "fallback from" in result.arbitrator
    assert "delegated arbitration unavailable" in result.reason
    assert batch.total_paisa == 900_000


def test_unparseable_model_output_falls_back():
    view = make_view("REC-00099", "EXCEPTION", ("MISSING_SETTLEMENT",), 900_000)
    arb = LLMResidualArbitrator(client=ScriptedProvider(["I am not JSON at all"]))
    result, _ = arb.resolve_with_journal(case_for(view))
    assert "fallback from" in result.arbitrator


def test_nonsense_decision_falls_back():
    view = make_view("REC-00099", "EXCEPTION", ("MISSING_SETTLEMENT",), 900_000)
    arb = scripted({"decision": "DEFINITELY_FINE", "confidence": 1.0})
    result, _ = arb.resolve_with_journal(case_for(view))
    assert "fallback from" in result.arbitrator


def test_the_prompt_carries_only_permitted_fields():
    view = make_view()
    case = case_for(view)
    client = ScriptedProvider([{"decision": "UNRESOLVED", "reason": "no"}])
    arb = LLMResidualArbitrator(client=client)
    arb.resolve(case)

    sent = client.calls[0]["user"]
    payload = json.loads(sent.split("RESIDUAL CASE\n")[1].split("\n\nPERMITTED")[0])
    assert set(payload).issubset(set(LLMResidualArbitrator.PERMITTED_INPUT_FIELDS))
    # The dataset must never be in the prompt.
    assert "orders" not in payload and "settlements" not in payload


def test_extract_json_handles_fenced_and_prose_wrapped_output():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here you go: {"a": 2} Hope that helps.') == {"a": 2}
    with pytest.raises(ProviderError):
        extract_json("no object here")


def test_malformed_json_is_an_error_never_repaired():
    with pytest.raises(ProviderError):
        extract_json('{"decision": "RESOLVE", ')
