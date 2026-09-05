"""Journal approval and posting.

Nothing an arbitrator produces reaches the ledger on its own. A proposed entry
becomes APPROVED only when a named person approves it, and POSTED only after the
batch is re-verified at posting time.

Re-verifying at posting rather than trusting the check made at proposal time is
deliberate: the two events are separated by a human decision and possibly by a
configuration change, and the balance check is cheap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ai import JournalEntry
from app.domain.enums import JournalEntryStatus
from app.models.entities import JournalEntryRow
from app.services.accounting import chart_of_accounts as coa
from app.services.accounting.journal import JournalBatch, verify_journal_batch


class PostingError(RuntimeError):
    """Raised when an entry cannot legally move to the requested state."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_domain(row: JournalEntryRow) -> JournalEntry:
    return JournalEntry(
        journal_id=row.journal_id,
        date=row.entry_date,
        debit_account=row.debit_account,
        credit_account=row.credit_account,
        amount_paisa=row.amount_paisa,
        description=row.description,
        source_records=list(row.source_records or []),
        confidence=row.confidence,
        status=JournalEntryStatus(row.status),
    )


def list_entries(
    session: Session,
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    residual_id: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple:
    stmt = select(JournalEntryRow)
    if run_id:
        stmt = stmt.where(JournalEntryRow.run_id == run_id)
    if status:
        stmt = stmt.where(JournalEntryRow.status == status)
    if residual_id:
        stmt = stmt.where(JournalEntryRow.residual_id == residual_id)
    rows = list(session.scalars(stmt).all())
    rows.sort(key=lambda r: (-abs(r.amount_paisa), r.journal_id))
    return rows[offset : offset + limit], len(rows)


def _batch_for(session: Session, batch_id: str) -> JournalBatch:
    rows = list(
        session.scalars(
            select(JournalEntryRow).where(JournalEntryRow.batch_id == batch_id)
        ).all()
    )
    if not rows:
        raise PostingError(f"no journal batch {batch_id}")
    batch = JournalBatch(
        batch_id=batch_id,
        residual_id=rows[0].residual_id,
        entries=[_as_domain(r) for r in rows],
        narrative=rows[0].description,
        expected_total_paisa=sum(r.amount_paisa for r in rows),
    )
    return batch


def decide(
    session: Session,
    journal_id: str,
    decision: str,
    actor: str,
    note: str = "",
) -> JournalEntryRow:
    """Approve, reject or post one entry. ``actor`` is mandatory."""
    if not actor or not actor.strip():
        raise PostingError(
            "a journal decision requires a named actor; an unattributed change to "
            "the ledger is not auditable"
        )

    row = session.get(JournalEntryRow, journal_id)
    if row is None:
        raise PostingError(f"journal entry {journal_id} not found")

    target = decision.strip().upper()
    if target == "APPROVE":
        if row.status != JournalEntryStatus.PROPOSED.value:
            raise PostingError(
                f"{journal_id} is {row.status}; only a PROPOSED entry can be approved"
            )
        row.status = JournalEntryStatus.APPROVED.value

    elif target == "REJECT":
        if row.status == JournalEntryStatus.POSTED.value:
            raise PostingError(
                f"{journal_id} is already POSTED and cannot be rejected; post a "
                f"reversing entry instead"
            )
        row.status = JournalEntryStatus.REJECTED.value

    elif target == "POST":
        if row.status != JournalEntryStatus.APPROVED.value:
            raise PostingError(
                f"{journal_id} is {row.status}; only an APPROVED entry can be posted"
            )
        # Re-verify at posting time rather than trusting the proposal-time check.
        verdict = verify_journal_batch(_batch_for(session, row.batch_id))
        if not verdict.accepted:
            raise PostingError(
                f"batch {row.batch_id} fails verification at posting time: "
                + "; ".join(verdict.reasons)
            )
        row.status = JournalEntryStatus.POSTED.value

    else:
        raise PostingError(
            f"unknown decision {decision!r}; expected APPROVE, REJECT or POST"
        )

    row.decided_by = actor
    row.decided_at = _now()
    if note:
        row.description = f"{row.description} [{actor}: {note}]"
    session.commit()
    return row


def trial_balance(session: Session, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Account balances from POSTED entries only.

    Proposals are excluded on purpose: a trial balance that included unapproved
    proposals would not be a trial balance, it would be a wish.
    """
    stmt = select(JournalEntryRow).where(
        JournalEntryRow.status == JournalEntryStatus.POSTED.value
    )
    if run_id:
        stmt = stmt.where(JournalEntryRow.run_id == run_id)
    rows = list(session.scalars(stmt).all())

    balances: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        for code, side in ((row.debit_account, "debit"), (row.credit_account, "credit")):
            account = coa.resolve(code)
            bucket = balances.setdefault(
                code,
                {
                    "code": code,
                    "name": account.name if account else "Unknown account",
                    "account_type": account.account_type.value if account else "UNKNOWN",
                    "debit_paisa": 0,
                    "credit_paisa": 0,
                },
            )
            bucket[f"{side}_paisa"] += row.amount_paisa

    total_debits = sum(b["debit_paisa"] for b in balances.values())
    total_credits = sum(b["credit_paisa"] for b in balances.values())
    for bucket in balances.values():
        bucket["balance_paisa"] = bucket["debit_paisa"] - bucket["credit_paisa"]

    return {
        "run_id": run_id,
        "posted_entries": len(rows),
        "total_debits_paisa": total_debits,
        "total_credits_paisa": total_credits,
        "balanced": total_debits == total_credits,
        "accounts": sorted(balances.values(), key=lambda a: a["code"]),
    }


def entry_to_dict(row: JournalEntryRow) -> Dict[str, Any]:
    debit = coa.resolve(row.debit_account)
    credit = coa.resolve(row.credit_account)
    return {
        "journal_id": row.journal_id,
        "batch_id": row.batch_id,
        "run_id": row.run_id,
        "residual_id": row.residual_id,
        "entry_date": row.entry_date,
        "debit_account": row.debit_account,
        "debit_account_name": debit.name if debit else "Unknown account",
        "credit_account": row.credit_account,
        "credit_account_name": credit.name if credit else "Unknown account",
        "amount_paisa": row.amount_paisa,
        "description": row.description,
        "source_records": list(row.source_records or []),
        "confidence": row.confidence,
        "status": row.status,
        "proposed_by": row.proposed_by,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at,
        "created_at": row.created_at,
    }
