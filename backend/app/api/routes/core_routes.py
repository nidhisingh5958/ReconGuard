"""Health, dataset generation, and reconciliation run endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_run_id, run_to_dict
from app.core.config import get_settings
from app.core.versioning import ENGINE_VERSION
from app.db.session import get_session
from app.repositories import reconciliation_repo as repo
from app.schemas.api import (
    GenerateDataRequest,
    GenerateDataResponse,
    HealthResponse,
    RunComparison,
    RunListResponse,
    RunRequest,
    RunSummary,
)
from app.services.ingestion.loader import DatasetError, load_manifest
from app.services.reconciliation import runner

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(session: Session = Depends(get_session)) -> HealthResponse:
    settings = get_settings()
    latest = repo.latest_run(session)
    backend = settings.database_url.split(":")[0]
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        system_version=settings.system_version,
        engine_version=ENGINE_VERSION,
        database=backend,
        ai_provider=settings.ai_provider,
        ai_enabled=settings.ai_enabled,
        deterministic_engine_requires_ai=False,
        accounting=settings.accounting.describe(),
        dataset_available=runner.dataset_exists(runner.DEFAULT_DATASET_ID),
        latest_run_id=latest.run_id if latest else None,
    )


@router.post(
    "/data/generate", response_model=GenerateDataResponse, tags=["data"]
)
def generate_data(payload: GenerateDataRequest) -> GenerateDataResponse:
    """Generate a deterministic synthetic dataset and write it to disk."""
    dataset_id, manifest, path = runner.generate_dataset(
        order_count=payload.order_count,
        seed=payload.seed,
        mode=payload.mode,
        dataset_id=payload.dataset_id,
    )
    ground_truth_path = path / "ground_truth.json"
    breakdown = {}
    if ground_truth_path.exists():
        import json

        with ground_truth_path.open(encoding="utf-8") as handle:
            breakdown = runner.anomaly_breakdown(json.load(handle))
    return GenerateDataResponse(
        dataset_id=dataset_id,
        mode=payload.mode,
        seed=payload.seed,
        manifest=manifest,
        anomaly_breakdown=breakdown,
        written_to=str(path),
    )


@router.post(
    "/reconciliation/run", response_model=RunSummary, tags=["reconciliation"]
)
def start_run(
    payload: RunRequest, session: Session = Depends(get_session)
) -> RunSummary:
    """Execute the deterministic engine. Never calls an LLM."""
    dataset_id = payload.dataset_id or runner.DEFAULT_DATASET_ID
    try:
        if dataset_id == runner.DEFAULT_DATASET_ID:
            runner.ensure_dataset(dataset_id)
        run = runner.execute_run(session, dataset_id=dataset_id, label=payload.label)
    except DatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RunSummary(**run_to_dict(run))


@router.get(
    "/reconciliation/runs", response_model=RunListResponse, tags=["reconciliation"]
)
def list_runs(
    limit: int = 50, session: Session = Depends(get_session)
) -> RunListResponse:
    runs = repo.list_runs(session, limit=limit)
    return RunListResponse(
        runs=[RunSummary(**run_to_dict(r)) for r in runs], total=len(runs)
    )


@router.get(
    "/reconciliation/runs/compare",
    response_model=RunComparison,
    tags=["reconciliation"],
)
def compare_runs(
    baseline: str, candidate: str, session: Session = Depends(get_session)
) -> RunComparison:
    """Compare two runs. Deltas are computed, never stored or assumed."""
    left = repo.get_run(session, baseline)
    right = repo.get_run(session, candidate)
    if left is None or right is None:
        missing = baseline if left is None else candidate
        raise HTTPException(status_code=404, detail=f"run {missing} not found")

    match_delta = right.deterministic_matches - left.deterministic_matches
    match_improvement = (
        (match_delta / left.deterministic_matches * 100.0)
        if left.deterministic_matches
        else 0.0
    )
    residual_delta = right.residuals - left.residuals
    residual_reduction = (
        (-residual_delta / left.residuals * 100.0) if left.residuals else 0.0
    )

    left_codes = left.reason_code_distribution or {}
    right_codes = right.reason_code_distribution or {}
    deltas = {
        code: right_codes.get(code, 0) - left_codes.get(code, 0)
        for code in sorted(set(left_codes) | set(right_codes))
    }

    return RunComparison(
        baseline=RunSummary(**run_to_dict(left)),
        candidate=RunSummary(**run_to_dict(right)),
        deterministic_match_delta=match_delta,
        deterministic_match_improvement_pct=round(match_improvement, 4),
        match_rate_delta_pct=round((right.match_rate - left.match_rate) * 100.0, 4),
        residual_delta=residual_delta,
        residual_reduction_pct=round(residual_reduction, 4),
        exception_delta=right.exceptions - left.exceptions,
        throughput_delta_rps=round(right.throughput_rps - left.throughput_rps, 2),
        processing_time_delta_ms=round(
            right.processing_time_ms - left.processing_time_ms, 3
        ),
        unexplained_value_delta_paisa=(
            right.unexplained_value_paisa - left.unexplained_value_paisa
        ),
        reason_code_deltas={k: v for k, v in deltas.items() if v != 0},
    )


@router.get(
    "/reconciliation/runs/{run_id}",
    response_model=RunSummary,
    tags=["reconciliation"],
)
def get_run(run_id: str, session: Session = Depends(get_session)) -> RunSummary:
    run = repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return RunSummary(**run_to_dict(run))
