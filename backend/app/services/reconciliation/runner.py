"""Application service tying dataset, engine and persistence together.

The engine itself stays ignorant of all three. This module is the only place
that knows a run involves reading files and writing rows.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import DATA_DIR, get_settings
from app.domain.sources import SourceDataset
from app.models.entities import ReconciliationRun
from app.repositories import reconciliation_repo as repo
from app.services.ingestion.generator import (
    GeneratedDataset,
    GeneratorConfig,
    SyntheticDataGenerator,
)
from app.services.ingestion.loader import (
    DatasetError,
    load_dataset,
    load_manifest,
    write_dataset,
)
from app.services.reconciliation.engine import ReconciliationEngine

DEFAULT_DATASET_ID = "seed-500"


def dataset_path(dataset_id: str = DEFAULT_DATASET_ID) -> Path:
    return DATA_DIR / dataset_id


def dataset_exists(dataset_id: str = DEFAULT_DATASET_ID) -> bool:
    return (dataset_path(dataset_id) / "orders.json").exists()


def generate_dataset(
    order_count: int = 500,
    seed: int = 42,
    mode: str = "messy",
    dataset_id: Optional[str] = None,
) -> tuple:
    """Generate and persist a synthetic dataset. Returns (dataset_id, manifest, path)."""
    settings = get_settings()
    resolved_id = dataset_id or f"{mode}-{order_count}"
    config = GeneratorConfig(
        order_count=order_count,
        seed=seed,
        mode=mode,
        accounting=settings.accounting,
        dataset_id=resolved_id,
    )
    generated: GeneratedDataset = SyntheticDataGenerator(config).generate()
    target = dataset_path(resolved_id)
    manifest = write_dataset(target, generated)
    return resolved_id, manifest, target


def anomaly_breakdown(generated_ground_truth) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in generated_ground_truth:
        key = row["anomaly_type"] if isinstance(row, dict) else row.anomaly_type
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def load(dataset_id: str = DEFAULT_DATASET_ID) -> SourceDataset:
    return load_dataset(dataset_path(dataset_id))


def ensure_dataset(dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """Generate the default seed dataset on first use so the API is never empty."""
    if dataset_exists(dataset_id):
        return dataset_id
    resolved, _, _ = generate_dataset(
        order_count=500, seed=42, mode="messy", dataset_id=dataset_id
    )
    return resolved


def execute_run(
    session: Session,
    dataset_id: str = DEFAULT_DATASET_ID,
    label: str = "",
) -> ReconciliationRun:
    """Run the deterministic engine over a dataset and persist everything."""
    settings = get_settings()
    if not dataset_exists(dataset_id):
        raise DatasetError(
            f"dataset {dataset_id!r} not found. Generate it first via "
            f"POST /api/data/generate"
        )

    dataset = load(dataset_id)
    manifest = load_manifest(dataset_path(dataset_id)) or {}
    repo.register_dataset(
        session, dataset_id, dataset.mode, dataset.seed, manifest
    )

    run_id = repo.next_run_id(session)
    # Promoted rules are executable configuration: a run picks up whatever has
    # been promoted, which is what makes rule promotion actually change results.
    from app.services.rules import registry

    engine = ReconciliationEngine(
        accounting=settings.accounting,
        reconciliation=settings.reconciliation,
        rules=registry.load_rule_set(session),
    )
    output = engine.run(dataset, run_id=run_id)

    return repo.save_run(
        session,
        metrics=output.metrics,
        results=output.results,
        audit_events=output.audit_events,
        accounting_config=settings.accounting.describe(),
        label=label,
    )
