"""API integration tests.

These run against an isolated SQLite database and a temporary data directory,
so they neither read nor pollute the developer's working dataset.

The single most important assertion in this module is that every endpoint
works with no AI provider configured. That is a product requirement, not an
implementation detail.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point at a throwaway database BEFORE the app (and its engine) is imported.
_TMP = Path(tempfile.mkdtemp(prefix="reconguard-api-"))
os.environ["RECONGUARD_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["RECONGUARD_AI_PROVIDER"] = "none"

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402

from app.db.init_db import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.reconciliation import runner  # noqa: E402

DATASET_ID = "api-test"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data_dir = tmp_path_factory.mktemp("reconguard-data")
    runner.DATA_DIR = data_dir  # keep generated fixtures out of the repo
    init_db()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def seeded(client):
    """One dataset and two runs, so comparison endpoints have something real."""
    generated = client.post(
        "/api/data/generate",
        json={"order_count": 120, "seed": 11, "mode": "messy", "dataset_id": DATASET_ID},
    )
    assert generated.status_code == 200, generated.text
    first = client.post(
        "/api/reconciliation/run", json={"dataset_id": DATASET_ID, "label": "baseline"}
    )
    second = client.post(
        "/api/reconciliation/run", json={"dataset_id": DATASET_ID, "label": "candidate"}
    )
    assert first.status_code == 200 and second.status_code == 200
    return first.json(), second.json()


# --- system ---------------------------------------------------------------
def test_health_reports_a_working_system_with_no_ai(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["ai_enabled"] is False
    assert payload["ai_provider"] == "none"
    assert payload["deterministic_engine_requires_ai"] is False
    assert payload["accounting"]["gateway_fee_pct"] == 2.0
    assert payload["accounting"]["gst_on_fee_pct"] == 18.0


def test_root_advertises_the_product(client):
    payload = client.get("/").json()
    assert payload["name"] == "ReconGuard"
    assert "Deterministic" in payload["tagline"]


# --- data generation ------------------------------------------------------
def test_generate_writes_a_labelled_dataset(client):
    payload = client.post(
        "/api/data/generate",
        json={"order_count": 60, "seed": 3, "mode": "messy", "dataset_id": "gen-test"},
    ).json()
    assert payload["manifest"]["units"] == "paise"
    assert payload["manifest"]["order_count"] == 60
    assert payload["anomaly_breakdown"], "messy mode must label its anomalies"
    assert sum(payload["anomaly_breakdown"].values()) > 0


def test_clean_mode_generates_no_anomalies(client):
    payload = client.post(
        "/api/data/generate",
        json={"order_count": 40, "seed": 3, "mode": "clean", "dataset_id": "clean-test"},
    ).json()
    assert payload["anomaly_breakdown"] == {}


# --- runs -----------------------------------------------------------------
def test_run_produces_measured_metrics(seeded):
    first, _ = seeded
    assert first["records_processed"] > 0
    assert 0.0 < first["match_rate"] <= 1.0
    assert first["processing_time_ms"] > 0
    assert first["throughput_rps"] > 0
    assert first["engine_version"].startswith("recon-engine/")
    # The parts must add up to the whole; nothing may go uncounted.
    total = (
        first["deterministic_matches"]
        + first["partial_matches"]
        + first["residuals"]
    )
    assert total == first["records_processed"]


def test_runs_are_listed_newest_first(client, seeded):
    payload = client.get("/api/reconciliation/runs").json()
    assert payload["total"] >= 2
    assert payload["runs"][0]["run_id"] >= payload["runs"][-1]["run_id"]


def test_run_detail_is_retrievable(client, seeded):
    first, _ = seeded
    payload = client.get(f"/api/reconciliation/runs/{first['run_id']}").json()
    assert payload["run_id"] == first["run_id"]
    assert payload["status_distribution"]


def test_unknown_run_is_a_404(client):
    assert client.get("/api/reconciliation/runs/RUN-99999").status_code == 404


def test_run_comparison_computes_deltas(client, seeded):
    first, second = seeded
    payload = client.get(
        "/api/reconciliation/runs/compare",
        params={"baseline": first["run_id"], "candidate": second["run_id"]},
    ).json()
    # Identical input twice: the engine is deterministic, so nothing moved.
    assert payload["deterministic_match_delta"] == 0
    assert payload["residual_delta"] == 0
    assert payload["reason_code_deltas"] == {}
    assert payload["baseline"]["run_id"] == first["run_id"]


# --- records --------------------------------------------------------------
def test_records_are_paginated_and_filterable(client, seeded):
    payload = client.get("/api/reconciliation/records", params={"limit": 5}).json()
    assert len(payload["records"]) <= 5
    assert payload["total"] >= len(payload["records"])

    matched = client.get(
        "/api/reconciliation/records", params={"status": "MATCHED", "limit": 3}
    ).json()
    assert all(r["status"] == "MATCHED" for r in matched["records"])


def test_record_detail_carries_calculation_and_evidence(client, seeded):
    listing = client.get(
        "/api/reconciliation/records", params={"status": "MATCHED", "limit": 1}
    ).json()
    rec_id = listing["records"][0]["reconciliation_id"]
    detail = client.get(f"/api/reconciliation/records/{rec_id}").json()
    assert detail["calculation"], "a matched record must show its arithmetic"
    assert detail["evidence"], "a matched record must cite its source records"
    assert detail["source_records"]
    assert detail["confidence"] == 1.0
    assert any("x 200/10000" in line["expression"] for line in detail["calculation"])


def test_explain_answers_why_it_matched(client, seeded):
    listing = client.get(
        "/api/reconciliation/records", params={"status": "MATCHED", "limit": 1}
    ).json()
    rec_id = listing["records"][0]["reconciliation_id"]
    payload = client.get(
        f"/api/reconciliation/records/{rec_id}/explain"
    ).json()
    assert payload["grounded"] is True
    assert payload["generated_by"] == "deterministic-retrieval"
    assert payload["verdict"]
    assert payload["matching_logic"]
    assert payload["audit_events"], "the explanation must be backed by audit events"


# --- exceptions -----------------------------------------------------------
def test_exceptions_are_honest_and_never_auto_resolved(client, seeded):
    payload = client.get("/api/exceptions", params={"limit": 200}).json()
    assert payload["total"] > 0
    for item in payload["exceptions"]:
        assert item["resolution_status"] == "HUMAN REVIEW REQUIRED"
        assert item["status"] != "MATCHED"
        assert item["findings"], "an exception must state what could not be established"
        assert item["headline"]
    assert payload["summary"]["total"] > 0


def test_unknown_bank_credit_appears_on_the_exception_desk(client, seeded):
    payload = client.get(
        "/api/exceptions", params={"reason_code": "UNKNOWN_BANK_CREDIT", "limit": 50}
    ).json()
    assert payload["total"] > 0
    item = payload["exceptions"][0]
    assert item["headline"] == "Unknown bank credit"
    assert "No matching order" in item["findings"]
    assert "No matching settlement" in item["findings"]
    assert "No matching invoice" in item["findings"]


# --- audit ----------------------------------------------------------------
def test_audit_trail_is_populated_and_filterable(client, seeded):
    payload = client.get("/api/audit", params={"limit": 10}).json()
    assert payload["total"] > 0
    assert payload["facets"]["actions"]
    event = payload["events"][0]
    assert event["audit_id"]
    assert event["system_version"]

    filtered = client.get(
        "/api/audit", params={"action": "RECONCILIATION_MATCH", "limit": 5}
    ).json()
    assert all(e["action"] == "RECONCILIATION_MATCH" for e in filtered["events"])
    assert all(e["calculation"] for e in filtered["events"])


def test_audit_events_are_chronological(client, seeded):
    payload = client.get("/api/audit", params={"limit": 100}).json()
    stamps = [e["timestamp"] for e in payload["events"]]
    assert stamps == sorted(stamps)


# --- metrics / rules / cash ----------------------------------------------
def test_metrics_expose_their_formulas(client, seeded):
    payload = client.get("/api/metrics").json()
    assert payload["run"]["match_rate"] > 0
    assert payload["formulas"]["match_rate"] == (
        "deterministic_matches / records_processed"
    )
    assert payload["status_distribution"]
    assert payload["confidence_distribution"]
    assert payload["daily_volume"]


def test_rules_catalogue_is_seeded_with_the_built_in_rules(client, seeded):
    payload = client.get("/api/rules").json()
    assert payload["total"] >= 20
    ids = {r["rule_id"] for r in payload["rules"]}
    assert {"RULE-FEE-001", "RULE-TAX-001", "RULE-TAX-002", "RULE-NET-001"} <= ids


def test_built_in_rules_are_active_and_not_dynamic(client, seeded):
    """Built-ins are compiled into the engine, so they carry no parameters and
    cannot be replayed or promoted. Promotion applies only to induced rules."""
    payload = client.get("/api/rules").json()
    built_in = [r for r in payload["rules"] if r["rule_id"].startswith("RULE-") and not r["rule_id"].startswith("RULE-DYN-")]
    assert built_in
    for rule in built_in:
        assert rule["status"] == "ACTIVE"
        assert rule["is_dynamic"] is False
    assert payload["lifecycle"], "the promotion lifecycle must be published"


def test_cash_position_is_committed_only_with_no_prediction(client, seeded):
    payload = client.get("/api/cash-position").json()
    assert payload["includes_prediction"] is False
    assert payload["basis"] == "deterministic"
    assert payload["forecast"] == []
    assert payload["confirmed_received_paisa"] > 0


def test_arbitration_queue_contains_only_residuals(client, seeded):
    payload = client.get("/api/arbitration/queue").json()
    assert payload["arbitrator"] == "null"
    assert payload["ai_enabled"] is False
    assert payload["queue_size"] > 0
    for residual in payload["residuals"]:
        assert residual["status"] in (
            "EXCEPTION",
            "UNRESOLVED",
            "REVIEW_REQUIRED",
            "DUPLICATE",
        )
        assert residual["reason_codes"]
