"""API tests for arbitration, self-healing rules, journals, forecasting, copilot.

Runs against an isolated database and a temporary data directory, with no AI
provider configured. That is the point: the whole intelligence layer has to work
with no credentials present.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="reconguard-intel-"))
os.environ["RECONGUARD_DATABASE_URL"] = f"sqlite:///{(_TMP / 'intel.db').as_posix()}"
os.environ["RECONGUARD_AI_PROVIDER"] = "none"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402

from app.db.init_db import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.reconciliation import runner  # noqa: E402

DATASET_ID = "intel-test"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("reconguard-intel-data")
    runner.DATA_DIR = data_dir
    init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def run_id(client):
    generated = client.post(
        "/api/data/generate",
        json={
            "order_count": 400,
            "seed": 42,
            "mode": "messy",
            "dataset_id": DATASET_ID,
        },
    )
    assert generated.status_code == 200, generated.text
    started = client.post(
        "/api/reconciliation/run",
        json={"dataset_id": DATASET_ID, "label": "before self-healing"},
    )
    assert started.status_code == 200, started.text
    return started.json()["run_id"]


@pytest.fixture(scope="module")
def arbitrated(client, run_id):
    response = client.post(
        "/api/arbitration/run",
        json={"run_id": run_id, "arbitrator": "deterministic"},
    )
    assert response.status_code == 200, response.text
    return run_id, response.json()


# --- arbitration ----------------------------------------------------------
def test_arbitration_runs_with_no_ai_credentials(arbitrated):
    _, payload = arbitrated
    assert payload["arbitrator"] == "deterministic"
    assert payload["uses_model"] is False
    assert payload["residuals_examined"] > 0
    assert payload["rejected_by_verification"] == 0
    assert payload["journal_entries_proposed"] > 0


def test_every_result_is_verified_and_needs_a_human(client, arbitrated):
    run, _ = arbitrated
    payload = client.get("/api/arbitration/results", params={"run_id": run}).json()
    assert payload["total"] > 0
    for item in payload["items"]:
        assert item["decision"] in ("RESOLVE", "PROBABLE", "UNRESOLVED")
        assert item["reason"]
        assert item["requires_human_review"] is True
        if item["decision"] != "UNRESOLVED":
            assert item["verification_accepted"] is True
            assert item["proposed_action"]
    assert payload["summary"]["total"] == payload["total"]


def test_arbitration_only_sees_residuals(client, arbitrated):
    run, _ = arbitrated
    results = client.get("/api/arbitration/results", params={"run_id": run}).json()
    matched = client.get(
        "/api/reconciliation/records",
        params={"run_id": run, "status": "MATCHED", "limit": 1000},
    ).json()
    matched_ids = {r["reconciliation_id"] for r in matched["records"]}
    for item in results["items"]:
        assert item["residual_id"] not in matched_ids


# --- journals -------------------------------------------------------------
def test_proposed_journals_balance_and_use_real_accounts(client, arbitrated):
    run, _ = arbitrated
    payload = client.get(
        "/api/journal", params={"run_id": run, "limit": 500}
    ).json()
    assert payload["total"] > 0
    codes = {a["code"] for a in payload["chart_of_accounts"]}
    for entry in payload["entries"]:
        assert entry["amount_paisa"] > 0
        assert entry["debit_account"] in codes
        assert entry["credit_account"] in codes
        assert entry["debit_account"] != entry["credit_account"]


def test_posting_without_approval_is_refused(client, arbitrated):
    run, _ = arbitrated
    listing = client.get(
        "/api/journal", params={"run_id": run, "status": "PROPOSED", "limit": 1}
    ).json()
    journal_id = listing["entries"][0]["journal_id"]
    response = client.post(
        f"/api/journal/{journal_id}/decide",
        json={"decision": "POST", "actor": "auditor@example.com"},
    )
    assert response.status_code == 409
    assert "only an APPROVED entry can be posted" in response.json()["detail"]


def test_a_journal_decision_requires_a_named_actor(client, arbitrated):
    run, _ = arbitrated
    listing = client.get(
        "/api/journal", params={"run_id": run, "status": "PROPOSED", "limit": 1}
    ).json()
    journal_id = listing["entries"][0]["journal_id"]
    response = client.post(
        f"/api/journal/{journal_id}/decide",
        json={"decision": "APPROVE", "actor": ""},
    )
    assert response.status_code == 422


def test_approve_then_post_yields_a_balanced_trial_balance(client, arbitrated):
    run, _ = arbitrated
    listing = client.get(
        "/api/journal", params={"run_id": run, "status": "PROPOSED", "limit": 1}
    ).json()
    journal_id = listing["entries"][0]["journal_id"]

    assert (
        client.post(
            f"/api/journal/{journal_id}/decide",
            json={"decision": "APPROVE", "actor": "auditor@example.com"},
        ).status_code
        == 200
    )
    posted = client.post(
        f"/api/journal/{journal_id}/decide",
        json={"decision": "POST", "actor": "auditor@example.com"},
    )
    assert posted.status_code == 200
    assert posted.json()["by_status"].get("POSTED", 0) >= 1

    balance = client.get(
        "/api/journal/trial-balance", params={"run_id": run}
    ).json()
    assert balance["posted_entries"] >= 1
    assert balance["balanced"] is True
    assert balance["total_debits_paisa"] == balance["total_credits_paisa"]


def test_trial_balance_excludes_proposals(client, arbitrated):
    run, _ = arbitrated
    journal = client.get("/api/journal", params={"run_id": run, "limit": 500}).json()
    balance = client.get("/api/journal/trial-balance", params={"run_id": run}).json()
    assert journal["by_status"].get("PROPOSED", 0) > 0
    assert balance["posted_entries"] == journal["by_status"].get("POSTED", 0)


# --- the self-healing loop over HTTP --------------------------------------
def test_the_full_self_healing_loop(client, run_id, arbitrated):
    """Induce, validate by replay, promote, re-run, and measure the difference."""
    _, arbitration = arbitrated
    proposals = arbitration["rule_proposals"]
    assert proposals, "arbitration should induce a rule from the reference gap"
    rule = proposals[0]
    assert rule["status"] == "PROPOSED"
    assert rule["support"] >= 3

    before = client.get(f"/api/reconciliation/runs/{run_id}").json()

    # promotion is refused without evidence
    premature = client.post(
        f"/api/rules/{rule['rule_id']}/promote", json={"actor": "auditor@example.com"}
    )
    assert premature.status_code == 409

    # validate by replay
    validated = client.post(
        f"/api/rules/{rule['rule_id']}/validate",
        json={"dataset_id": DATASET_ID},
    )
    assert validated.status_code == 200
    catalogue = validated.json()
    report = next(
        v for v in catalogue["validations"] if v["rule_id"] == rule["rule_id"]
    )
    assert report["verdict"] == "IMPROVES"
    assert report["match_delta"] > 0
    assert report["regressions"] == []

    row = next(r for r in catalogue["rules"] if r["rule_id"] == rule["rule_id"])
    assert row["status"] == "APPROVED"

    # a named human promotes it
    promoted = client.post(
        f"/api/rules/{rule['rule_id']}/promote",
        json={"actor": "auditor@example.com", "note": "Acquirer format change"},
    )
    assert promoted.status_code == 200
    row = next(
        r for r in promoted.json()["rules"] if r["rule_id"] == rule["rule_id"]
    )
    assert row["status"] == "ACTIVE"
    assert rule["rule_id"] in promoted.json()["active_dynamic_rules"]

    # the next run picks it up
    after = client.post(
        "/api/reconciliation/run",
        json={"dataset_id": DATASET_ID, "label": "after self-healing"},
    ).json()

    assert after["deterministic_matches"] > before["deterministic_matches"]
    assert after["residuals"] < before["residuals"]
    assert after["match_rate"] > before["match_rate"]

    comparison = client.get(
        "/api/reconciliation/runs/compare",
        params={"baseline": run_id, "candidate": after["run_id"]},
    ).json()
    assert comparison["deterministic_match_delta"] > 0
    assert comparison["residual_reduction_pct"] > 0
    assert comparison["unexplained_value_delta_paisa"] < 0


def test_a_built_in_rule_cannot_be_replayed(client, run_id):
    response = client.post("/api/rules/RULE-FEE-001/validate", json={})
    assert response.status_code == 400
    assert "compiled into the engine" in response.json()["detail"]


def test_promotion_requires_a_named_actor(client, arbitrated):
    catalogue = client.get("/api/rules").json()
    dynamic = [r for r in catalogue["rules"] if r["is_dynamic"]]
    assert dynamic
    response = client.post(
        f"/api/rules/{dynamic[0]['rule_id']}/promote", json={"actor": ""}
    )
    assert response.status_code == 422


def test_rules_catalogue_exposes_the_lifecycle(client, run_id):
    payload = client.get("/api/rules").json()
    assert payload["total"] >= 20
    assert [s["status"] for s in payload["lifecycle"]][:4] == [
        "PROPOSED",
        "VALIDATING",
        "APPROVED",
        "ACTIVE",
    ]


# --- forecasting ----------------------------------------------------------
def test_forecast_separates_committed_from_projected(client, run_id):
    payload = client.get(
        "/api/cash-position/forecast",
        params={"run_id": run_id, "horizon_days": 14},
    ).json()
    assert payload["horizon_days"] == 14
    assert len(payload["points"]) == 14
    assert payload["expected_total_paisa"] == (
        payload["committed_total_paisa"] + payload["projected_total_paisa"]
    )
    for point in payload["points"]:
        assert point["low_paisa"] <= point["expected_inflow_paisa"] <= point["high_paisa"]


def test_forecast_confidence_is_backtested(client, run_id):
    payload = client.get(
        "/api/cash-position/forecast", params={"run_id": run_id}
    ).json()
    report = payload["backtest"]
    assert report is not None
    if report["usable"]:
        assert report["test_days"] > 0
        assert 0.0 <= report["coverage"] <= 1.0
        assert report["hits"] <= report["test_days"]
        assert "held-out" in report["note"]


def test_committed_cash_position_still_reports_no_prediction(client, run_id):
    payload = client.get("/api/cash-position", params={"run_id": run_id}).json()
    assert payload["includes_prediction"] is False
    assert payload["basis"] == "deterministic"


# --- copilot --------------------------------------------------------------
def test_copilot_answers_from_stored_facts(client, run_id):
    payload = client.post(
        "/api/copilot/ask",
        json={"question": "What is the match rate for this run?", "run_id": run_id},
    ).json()
    assert payload["intent"] == "RUN_METRICS"
    assert payload["grounded"] is True
    assert payload["generated_by"] == "deterministic-retrieval"
    assert "match rate of" in payload["answer"]
    assert payload["facts"]


def test_copilot_agrees_with_the_metrics_endpoint(client, run_id):
    """An answer and the dashboard must never disagree about a number."""
    metrics = client.get("/api/metrics", params={"run_id": run_id}).json()["run"]
    answer = client.post(
        "/api/copilot/ask",
        json={"question": "How many records were processed?", "run_id": run_id},
    ).json()
    processed = next(
        f["value"] for f in answer["facts"] if f["label"] == "Records processed"
    )
    assert processed == f"{metrics['records_processed']:,}"


def test_copilot_declines_rather_than_guessing(client, run_id):
    payload = client.post(
        "/api/copilot/ask",
        json={"question": "What will our revenue be next year?", "run_id": run_id},
    ).json()
    assert payload["intent"] == "UNKNOWN"
    assert "could not map that question" in payload["answer"]
    assert payload["facts"], "an honest decline still offers what it can answer"


def test_copilot_explains_a_specific_record(client, run_id):
    listing = client.get(
        "/api/reconciliation/records",
        params={"run_id": run_id, "status": "MATCHED", "limit": 1},
    ).json()
    rec_id = listing["records"][0]["reconciliation_id"]
    payload = client.post(
        "/api/copilot/ask",
        json={"question": f"Why was {rec_id} matched?", "run_id": run_id},
    ).json()
    assert payload["intent"] == "EXPLAIN_RECORD"
    assert "Matched by" in payload["answer"]
    assert payload["records"]


def test_chart_of_accounts_is_exposed(client):
    payload = client.get("/api/accounting/chart").json()
    codes = {a["code"] for a in payload["accounts"]}
    assert {"1000", "1100", "1200", "2000", "9000"} <= codes


def test_health_still_reports_no_ai_requirement(client):
    payload = client.get("/api/health").json()
    assert payload["ai_enabled"] is False
    assert payload["deterministic_engine_requires_ai"] is False
