"""Ingestion: JSON on disk to typed source dataclasses.

The on-disk format uses the published source field names (``gross_amount``,
``net_amount``, ...) with integer paise values. This layer is where the unit
becomes explicit in the type system, mapping every amount onto a ``_paisa``
suffixed attribute so no downstream caller can mistake the unit.

Dates arrive in whatever format the source system uses; they are parsed here
and the original string is preserved in ``raw``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.domain.sources import (
    BankTransactionRecord,
    GroundTruthAnomaly,
    InvoiceRecord,
    OrderRecord,
    SettlementRecord,
    SourceDataset,
)
from app.services.normalization.dates import parse_date

ORDERS_FILE = "orders.json"
SETTLEMENTS_FILE = "settlements.json"
BANK_FILE = "bank_statement.json"
INVOICES_FILE = "invoices.json"
GROUND_TRUTH_FILE = "ground_truth.json"
MANIFEST_FILE = "manifest.json"


class DatasetError(RuntimeError):
    """Raised when a dataset is missing or structurally unusable."""


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def order_from_dict(row: Dict[str, Any]) -> OrderRecord:
    parsed = parse_date(row.get("order_date"))
    if parsed is None:
        raise DatasetError(f"order {row.get('order_id')} has an unparseable order_date")
    return OrderRecord(
        order_id=row["order_id"],
        customer_id=row.get("customer_id", ""),
        customer_name=row.get("customer_name", ""),
        invoice_id=row.get("invoice_id", ""),
        payment_id=row.get("payment_id", ""),
        gross_amount_paisa=int(row["gross_amount"]),
        refund_amount_paisa=int(row.get("refund_amount", 0)),
        currency=row.get("currency", "INR"),
        order_date=parsed,
        status=row.get("status", "paid"),
        raw=row,
    )


def settlement_from_dict(row: Dict[str, Any]) -> SettlementRecord:
    parsed = parse_date(row.get("settlement_date"))
    if parsed is None:
        raise DatasetError(
            f"settlement {row.get('settlement_id')} has an unparseable settlement_date"
        )
    payment_ids = list(row.get("payment_ids") or [])
    return SettlementRecord(
        settlement_id=row["settlement_id"],
        payment_id=row.get("payment_id") or (payment_ids[0] if payment_ids else ""),
        gross_amount_paisa=int(row["gross_amount"]),
        gateway_fee_paisa=int(row.get("gateway_fee", 0)),
        gst_on_fee_paisa=int(row.get("gst_on_fee", 0)),
        tds_paisa=int(row.get("tds", 0)),
        refund_adjustment_paisa=int(row.get("refund_adjustment", 0)),
        net_amount_paisa=int(row["net_amount"]),
        settlement_date=parsed,
        status=row.get("status", "processed"),
        payment_ids=payment_ids,
        raw=row,
    )


def bank_from_dict(row: Dict[str, Any]) -> BankTransactionRecord:
    parsed = parse_date(row.get("transaction_date"))
    if parsed is None:
        raise DatasetError(
            f"bank txn {row.get('bank_transaction_id')} has an unparseable date "
            f"{row.get('transaction_date')!r}"
        )
    return BankTransactionRecord(
        bank_transaction_id=row["bank_transaction_id"],
        transaction_date=parsed,
        description=row.get("description", ""),
        reference=str(row.get("reference", "")),
        credit_amount_paisa=int(row.get("credit_amount", 0)),
        debit_amount_paisa=int(row.get("debit_amount", 0)),
        balance_paisa=int(row.get("balance", 0)),
        transaction_type=row.get("transaction_type", "CREDIT"),
        raw=row,
    )


def invoice_from_dict(row: Dict[str, Any]) -> InvoiceRecord:
    parsed = parse_date(row.get("invoice_date"))
    if parsed is None:
        raise DatasetError(
            f"invoice {row.get('invoice_id')} has an unparseable invoice_date"
        )
    return InvoiceRecord(
        invoice_id=row["invoice_id"],
        customer_name=row.get("customer_name", ""),
        gstin=row.get("gstin", ""),
        invoice_date=parsed,
        taxable_amount_paisa=int(row.get("taxable_amount", 0)),
        gst_amount_paisa=int(row.get("gst_amount", 0)),
        total_amount_paisa=int(row.get("total_amount", 0)),
        tds_amount_paisa=int(row.get("tds_amount", 0)),
        status=row.get("status", "issued"),
        raw=row,
    )


def ground_truth_from_dict(row: Dict[str, Any]) -> GroundTruthAnomaly:
    return GroundTruthAnomaly(
        anomaly_id=row["anomaly_id"],
        anomaly_type=row["anomaly_type"],
        description=row.get("description", ""),
        order_id=row.get("order_id"),
        payment_id=row.get("payment_id"),
        settlement_id=row.get("settlement_id"),
        bank_transaction_id=row.get("bank_transaction_id"),
        invoice_id=row.get("invoice_id"),
        expected_status=row.get("expected_status"),
        detected_on=row.get("detected_on", "order"),
        expected_reason_codes=list(row.get("expected_reason_codes") or []),
        amount_paisa=int(row.get("amount_paisa", 0)),
    )


def load_dataset(directory: Path, include_ground_truth: bool = True) -> SourceDataset:
    """Load a dataset directory into typed records."""
    directory = Path(directory)
    if not (directory / ORDERS_FILE).exists():
        raise DatasetError(
            f"no dataset at {directory}. Generate one with: "
            f"python -m scripts.generate_dataset --messy"
        )

    manifest: Dict[str, Any] = {}
    manifest_path = directory / MANIFEST_FILE
    if manifest_path.exists():
        manifest = _read_json(manifest_path)

    ground_truth: List[GroundTruthAnomaly] = []
    gt_path = directory / GROUND_TRUTH_FILE
    if include_ground_truth and gt_path.exists():
        ground_truth = [ground_truth_from_dict(r) for r in _read_json(gt_path)]

    return SourceDataset(
        orders=[order_from_dict(r) for r in _read_json(directory / ORDERS_FILE)],
        settlements=[
            settlement_from_dict(r) for r in _read_json(directory / SETTLEMENTS_FILE)
        ],
        bank_transactions=[
            bank_from_dict(r) for r in _read_json(directory / BANK_FILE)
        ],
        invoices=[invoice_from_dict(r) for r in _read_json(directory / INVOICES_FILE)],
        ground_truth=ground_truth,
        dataset_id=manifest.get("dataset_id", directory.name),
        mode=manifest.get("mode", "messy"),
        seed=int(manifest.get("seed", 0)),
    )


def write_dataset(directory: Path, generated) -> Dict[str, Any]:
    """Persist a GeneratedDataset to a directory as JSON."""
    directory = Path(directory)
    _write_json(directory / ORDERS_FILE, generated.orders)
    _write_json(directory / SETTLEMENTS_FILE, generated.settlements)
    _write_json(directory / BANK_FILE, generated.bank_transactions)
    _write_json(directory / INVOICES_FILE, generated.invoices)
    _write_json(directory / GROUND_TRUTH_FILE, generated.ground_truth)
    _write_json(directory / MANIFEST_FILE, generated.manifest)
    return generated.manifest


def load_manifest(directory: Path) -> Optional[Dict[str, Any]]:
    path = Path(directory) / MANIFEST_FILE
    if not path.exists():
        return None
    return _read_json(path)
