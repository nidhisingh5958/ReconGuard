"""Schema creation and seeding of the built-in rule catalogue.

The rules seeded here are the deterministic rules the engine already applies.
They are registered as ACTIVE and are the reference set a future AI arbitrator
would propose additions to. Nothing is auto-promoted in this phase.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_engine
from app.models.base import Base
from app.models.entities import RuleRow

#: (rule_id, name, type, expression, description)
BUILTIN_RULES = [
    (
        "RULE-FEE-001",
        "Gateway fee",
        "ACCOUNTING",
        "gateway_fee = gross x gateway_fee_bps / 10000",
        "Percentage fee charged by the gateway on the gross transaction value.",
    ),
    (
        "RULE-TAX-001",
        "GST on gateway fee",
        "ACCOUNTING",
        "gst = gateway_fee x gst_on_fee_bps / 10000",
        "GST is levied on the gateway fee, not on the gross transaction value.",
    ),
    (
        "RULE-TAX-002",
        "TDS withholding",
        "ACCOUNTING",
        "tds = gross x tds_bps / 10000",
        "Tax deducted at source on gross value. Rate is configuration, not a constant.",
    ),
    (
        "RULE-NET-001",
        "Net settlement invariant",
        "ACCOUNTING",
        "net = gross - gateway_fee - gst - tds - netted_refunds + adjustments",
        "The accounting identity that proves a settlement corresponds to a payment.",
    ),
    (
        "RULE-NET-002",
        "Settlement self-consistency",
        "ACCOUNTING",
        "reported_net == gross - reported_fee - reported_gst - reported_tds - refunds",
        "Checks the source record adds up to its own reported net.",
    ),
    (
        "RULE-TOL-001",
        "Rounding tolerance",
        "ACCOUNTING",
        "abs(variance) <= rounding_tolerance_paisa",
        "Absorbs sub-paisa rounding differences, and labels every result it touches.",
    ),
    (
        "RULE-ADJ-001",
        "Refund netting",
        "ACCOUNTING",
        "netted_refunds = sum(refund_adjustment attributed to this payout)",
        "Refunds deducted inside a payout rather than paid separately.",
    ),
    (
        "RULE-MATCH-001",
        "Exact bank reference",
        "MATCHING",
        "settlement_key in extracted_numeric_keys(bank_narration)",
        "Settlement id appears verbatim in the bank narration. Confidence 1.0.",
    ),
    (
        "RULE-MATCH-002",
        "Truncated bank reference",
        "MATCHING",
        "unique_prefix_resolution(narration_key, payout_amount)",
        "Truncated reference resolved to exactly one settlement. Confidence 0.95.",
    ),
    (
        "RULE-MATCH-003",
        "Amount and date window",
        "MATCHING",
        "credit == net AND abs(days) <= tolerance AND gateway_marker",
        "Fallback when no reference survives. Confidence 0.90.",
    ),
    (
        "RULE-MATCH-011",
        "Aggregated settlement",
        "MATCHING",
        "sum(fee_breakdown(p.gross) for p in covered_payments) == reported_net",
        "N payments consolidated into one payout.",
    ),
    (
        "RULE-MATCH-012",
        "Split settlement",
        "MATCHING",
        "sum(leg.gross) == order.gross",
        "One payment paid out across N settlement legs.",
    ),
    (
        "RULE-MATCH-013",
        "Duplicate settlement",
        "MATCHING",
        "every settlement claims the full order gross",
        "Distinguishes a double payout from an even split.",
    ),
    (
        "RULE-MATCH-020",
        "Exact invoice link",
        "MATCHING",
        "order.invoice_id in invoice_register",
        "Direct identifier link between order and invoice.",
    ),
    (
        "RULE-MATCH-021",
        "Invoice typo fold",
        "MATCHING",
        "fold(O->0, I->1, L->1, S->5, B->8) AND unique",
        "Resolves transcription errors in the invoice register.",
    ),
    (
        "RULE-MATCH-022",
        "Counterparty alias",
        "MATCHING",
        "counterparty_key(a) == counterparty_key(b)",
        "Legal-form suffixes and punctuation removed before comparison.",
    ),
    (
        "RULE-NET-010",
        "Refund attribution",
        "CLASSIFICATION",
        "netted_refund_payment_ids or covered_payment_ids",
        "Attributes a netted refund to the payment it belongs to.",
    ),
    (
        "RULE-NET-011",
        "Chargeback detection",
        "CLASSIFICATION",
        "bank_debit references a known settlement",
        "Identifies a reversal of an already-settled payout.",
    ),
    (
        "RULE-NORM-010",
        "Date normalization",
        "NORMALIZATION",
        "ordered strptime over the configured format list",
        "Indian DD/MM convention wins ambiguity, by rule rather than by accident.",
    ),
    (
        "RULE-NORM-020",
        "Reference extraction",
        "NORMALIZATION",
        "digit runs of length >= 4 plus alphanumeric tokens",
        "Structured key extraction from messy bank narrations.",
    ),
    (
        "RULE-CLS-001",
        "Missing settlement",
        "CLASSIFICATION",
        "no settlement covers payment_id",
        "Honest dead end. Never resolved by inference.",
    ),
    (
        "RULE-CLS-002",
        "Unknown bank credit",
        "CLASSIFICATION",
        "credit unclaimed after all matching layers",
        "Reported as an exception, never attached to a plausible nearby order.",
    ),
    (
        "RULE-CLS-003",
        "Delayed settlement",
        "CLASSIFICATION",
        "settlement_date - order_date > delayed_settlement_flag_days",
        "Informational: payout landed outside the expected cycle.",
    ),
]


def create_schema() -> None:
    eng = get_engine()
    Base.metadata.create_all(bind=eng)
    # Lightweight schema migration for SQLite table column addition
    from sqlalchemy import inspect, text
    inspector = inspect(eng)
    if "arbitration_results" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("arbitration_results")]
        if "model_metadata" not in columns:
            with eng.connect() as conn:
                conn.execute(text("ALTER TABLE arbitration_results ADD COLUMN model_metadata JSON DEFAULT '{}'"))
                conn.commit()
    if "rules" in inspector.get_table_names():
        columns = [c["name"] for c in inspector.get_columns("rules")]
        missing = {
            "occurrence_count": "INTEGER DEFAULT 0",
            "backtest_result": "JSON DEFAULT '{}'",
            "expected_match_gain": "INTEGER DEFAULT 0",
            "expected_false_positive_rate": "FLOAT DEFAULT 0.0",
            "approved_by": "VARCHAR(64)",
            "approved_at": "DATETIME",
        }
        with eng.connect() as conn:
            for col, col_type in missing.items():
                if col not in columns:
                    conn.execute(text(f"ALTER TABLE rules ADD COLUMN {col} {col_type}"))
            conn.commit()


def seed_rules(session: Session) -> int:
    """Register the built-in deterministic rules if they are not present."""
    existing = {row.rule_id for row in session.query(RuleRow.rule_id).all()}
    now = datetime.now(timezone.utc)
    added = 0
    for rule_id, name, rule_type, expression, description in BUILTIN_RULES:
        if rule_id in existing:
            continue
        session.add(
            RuleRow(
                rule_id=rule_id,
                name=name,
                description=description,
                rule_type=rule_type,
                expression=expression,
                version=1,
                status="ACTIVE",
                created_by="system",
                created_at=now,
                validation_count=0,
                promoted_at=now,
            )
        )
        added += 1
    session.commit()
    return added


def init_db() -> None:
    create_schema()
    session = SessionLocal()
    try:
        seed_rules(session)
    finally:
        session.close()


if __name__ == "__main__":
    init_db()
    print("schema created and rule catalogue seeded")
