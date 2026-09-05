"""Journal entry construction and verification.

A journal entry here is a balanced pair by construction (one debit account, one
credit account, one integer-paise amount), so "debits equal credits" is true
structurally. That check alone would therefore be theatre. The verification that
actually matters, and the one an arbitrator cannot talk its way past, is:

    the batch total must equal the exact amount the residual left unexplained

A model can propose an explanation. It cannot propose a number: the number is
already known, to the paisa, from the deterministic engine. Anything that does
not reconcile to it is rejected before it can be persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from app.core.ids import SequenceIdFactory
from app.domain.ai import JournalEntry
from app.domain.enums import JournalEntryStatus
from app.services.accounting import chart_of_accounts as coa

RULE_JOURNAL_BALANCE = "RULE-JRN-001"
RULE_JOURNAL_AMOUNT = "RULE-JRN-002"
RULE_JOURNAL_ACCOUNTS = "RULE-JRN-003"
RULE_JOURNAL_EVIDENCE = "RULE-JRN-004"


@dataclass(slots=True)
class JournalBatch:
    """A set of entries that together correct one residual."""

    batch_id: str
    residual_id: str
    entries: List[JournalEntry] = field(default_factory=list)
    narrative: str = ""
    expected_total_paisa: int = 0

    @property
    def total_paisa(self) -> int:
        return sum(e.amount_paisa for e in self.entries)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "residual_id": self.residual_id,
            "narrative": self.narrative,
            "expected_total_paisa": self.expected_total_paisa,
            "total_paisa": self.total_paisa,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass(slots=True)
class JournalVerdict:
    accepted: bool
    reasons: List[str] = field(default_factory=list)
    total_debits_paisa: int = 0
    total_credits_paisa: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reasons": self.reasons,
            "total_debits_paisa": self.total_debits_paisa,
            "total_credits_paisa": self.total_credits_paisa,
        }


def verify_journal_batch(
    batch: JournalBatch,
    permitted_source_records: Optional[Sequence[str]] = None,
) -> JournalVerdict:
    """The gate every proposal passes before it can be persisted.

    Confidence asserted by whatever produced the batch carries no weight here.
    Only the arithmetic and the chart of accounts do.
    """
    reasons: List[str] = []
    debits = 0
    credits = 0

    if not batch.entries:
        reasons.append("batch contains no entries")

    for entry in batch.entries:
        debits += entry.amount_paisa
        credits += entry.amount_paisa

        if entry.amount_paisa <= 0:
            reasons.append(
                f"{entry.journal_id}: amount must be a positive number of paise, "
                f"got {entry.amount_paisa}"
            )
        if entry.debit_account == entry.credit_account:
            reasons.append(
                f"{entry.journal_id}: debits and credits the same account "
                f"{entry.debit_account}"
            )
        if not coa.is_known(entry.debit_account):
            reasons.append(
                f"{entry.journal_id}: unknown debit account {entry.debit_account!r} "
                f"(rule {RULE_JOURNAL_ACCOUNTS})"
            )
        if not coa.is_known(entry.credit_account):
            reasons.append(
                f"{entry.journal_id}: unknown credit account "
                f"{entry.credit_account!r} (rule {RULE_JOURNAL_ACCOUNTS})"
            )
        if permitted_source_records is not None:
            permitted = set(permitted_source_records)
            unknown = [r for r in entry.source_records if r not in permitted]
            if unknown:
                reasons.append(
                    f"{entry.journal_id}: cites records not present in the residual "
                    f"evidence: {unknown} (rule {RULE_JOURNAL_EVIDENCE})"
                )

    if debits != credits:
        reasons.append(
            f"debits {debits} != credits {credits} (rule {RULE_JOURNAL_BALANCE})"
        )

    if batch.expected_total_paisa and batch.total_paisa != batch.expected_total_paisa:
        reasons.append(
            f"batch total {batch.total_paisa} does not equal the unexplained "
            f"amount {batch.expected_total_paisa} (rule {RULE_JOURNAL_AMOUNT})"
        )

    return JournalVerdict(
        accepted=not reasons,
        reasons=reasons,
        total_debits_paisa=debits,
        total_credits_paisa=credits,
    )


class JournalBuilder:
    """Builds correctly-shaped batches for each residual class.

    The mapping from a reason code to a pair of accounts is bookkeeping policy,
    written down here once. It is deliberately NOT something a model chooses:
    the model may select which policy applies, and the amount always comes from
    the engine.
    """

    def __init__(self, value_date: Optional[date] = None) -> None:
        self._ids = SequenceIdFactory("JRN", width=6)
        self.value_date = value_date or date.today()

    def _entry(
        self,
        debit: str,
        credit: str,
        amount_paisa: int,
        description: str,
        source_records: Sequence[str],
        confidence: float,
    ) -> JournalEntry:
        return JournalEntry(
            journal_id=self._ids.next(),
            date=self.value_date,
            debit_account=debit,
            credit_account=credit,
            amount_paisa=int(amount_paisa),
            description=description,
            source_records=list(source_records),
            confidence=confidence,
            status=JournalEntryStatus.PROPOSED,
        )

    def build(
        self,
        residual_id: str,
        action: str,
        amount_paisa: int,
        source_records: Sequence[str],
        confidence: float,
        value_date: Optional[date] = None,
    ) -> Optional[JournalBatch]:
        """Build the batch for a named corrective action, or None if unmapped."""
        if value_date is not None:
            self.value_date = value_date
        amount = abs(int(amount_paisa))
        if amount == 0:
            return None

        policy = JOURNAL_POLICIES.get(action)
        if policy is None:
            return None
        debit, credit, narrative = policy

        batch = JournalBatch(
            batch_id=f"JB-{residual_id}",
            residual_id=residual_id,
            narrative=narrative,
            expected_total_paisa=amount,
        )
        batch.entries.append(
            self._entry(
                debit=debit,
                credit=credit,
                amount_paisa=amount,
                description=f"{narrative} ({residual_id})",
                source_records=source_records,
                confidence=confidence,
            )
        )
        return batch


#: action -> (debit account, credit account, narrative)
JOURNAL_POLICIES: Dict[str, tuple] = {
    "ACCRUE_SETTLEMENT_RECEIVABLE": (
        coa.SETTLEMENT_RECEIVABLE,
        coa.ACCOUNTS_RECEIVABLE,
        "Accrue payout owed by the gateway but not yet remitted",
    ),
    "PARK_UNIDENTIFIED_CREDIT": (
        coa.BANK,
        coa.SUSPENSE,
        "Park an unidentified bank credit in suspense pending attribution",
    ),
    "RECOGNISE_DUPLICATE_LIABILITY": (
        coa.BANK,
        coa.MERCHANT_PAYABLE,
        "Recognise a duplicate receipt as potentially repayable",
    ),
    "BOOK_CHARGEBACK_LOSS": (
        coa.CHARGEBACK_LOSS,
        coa.BANK,
        "Book a reversed payout as a chargeback loss",
    ),
    "BOOK_TDS_DIFFERENCE": (
        coa.TDS_RECEIVABLE,
        coa.RECONCILIATION_VARIANCE,
        "Book excess tax withheld at source as recoverable",
    ),
    "BOOK_GST_DIFFERENCE": (
        coa.GST_INPUT_CREDIT,
        coa.RECONCILIATION_VARIANCE,
        "Book a GST difference on gateway fees",
    ),
    "BOOK_FEE_DIFFERENCE": (
        coa.GATEWAY_FEE_EXPENSE,
        coa.RECONCILIATION_VARIANCE,
        "Book a gateway fee difference against the contracted rate",
    ),
    "BOOK_VARIANCE": (
        coa.RECONCILIATION_VARIANCE,
        coa.SETTLEMENT_RECEIVABLE,
        "Book an attributed but unresolved settlement variance",
    ),
}

#: Actions an arbitrator is allowed to propose. Enumerated so a model cannot
#: invent one, and so the permitted vocabulary is visible in one place.
PERMITTED_ACTIONS = tuple(sorted(JOURNAL_POLICIES))
