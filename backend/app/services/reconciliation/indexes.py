"""Lookup indexes for the reconciliation engine.

All matching is index-driven. Nothing in the engine scans one collection inside
a loop over another, so reconciliation is O(n) in the number of source records
rather than O(n^2). Every index here is built exactly once per run.

The prefix index deserves a note: bank narrations get truncated by field-width
limits, so a settlement reference can arrive one character short. Rather than
scoring string similarity, we index every prefix of every settlement key and
require the truncated key to resolve to exactly one settlement once the payout
amount is also taken into account. That keeps a truncated match provable.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.domain.sources import (
    BankTransactionRecord,
    InvoiceRecord,
    OrderRecord,
    SettlementRecord,
    SourceDataset,
)
from app.services.normalization.references import (
    extract_reference,
    settlement_numeric_key,
)
from app.services.normalization.text import counterparty_key, numeric_invoice_key

MIN_PREFIX_LENGTH = 4


@dataclass(slots=True)
class BankView:
    """A bank row plus the keys extracted from its narration, computed once."""

    record: BankTransactionRecord
    numeric_keys: List[str] = field(default_factory=list)
    looks_like_gateway_payout: bool = False
    is_credit: bool = True
    #: Keys contributed by promoted dynamic rules, and which rule found each.
    #: Kept separate from the built-in keys so a match sourced from a promoted
    #: rule can be attributed to that rule in the evidence.
    dynamic_keys: List[tuple] = field(default_factory=list)

    @property
    def amount_paisa(self) -> int:
        r = self.record
        return r.credit_amount_paisa if self.is_credit else r.debit_amount_paisa

    @property
    def date_was_reformatted(self) -> bool:
        """True when the source rendered the value date in a non-ISO format."""
        original = str(self.record.raw.get("transaction_date", ""))
        return bool(original) and original != self.record.transaction_date.isoformat()


@dataclass
class ReconciliationIndex:
    """Every lookup the engine needs, built in a single pass over the sources."""

    orders_by_payment_id: Dict[str, OrderRecord] = field(default_factory=dict)
    orders_by_order_id: Dict[str, OrderRecord] = field(default_factory=dict)
    settlements_by_id: Dict[str, SettlementRecord] = field(default_factory=dict)
    settlements_by_payment_id: Dict[str, List[SettlementRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    settlement_key_to_ids: Dict[str, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    settlement_prefix_to_ids: Dict[str, List[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    bank_views: List[BankView] = field(default_factory=list)
    bank_by_id: Dict[str, BankView] = field(default_factory=dict)
    credits_by_key: Dict[str, List[BankView]] = field(
        default_factory=lambda: defaultdict(list)
    )
    debits_by_key: Dict[str, List[BankView]] = field(
        default_factory=lambda: defaultdict(list)
    )
    credits_by_amount: Dict[int, List[BankView]] = field(
        default_factory=lambda: defaultdict(list)
    )
    invoices_by_id: Dict[str, InvoiceRecord] = field(default_factory=dict)
    invoices_by_numeric_key: Dict[str, List[InvoiceRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def settlements_for_payment(self, payment_id: str) -> List[SettlementRecord]:
        return self.settlements_by_payment_id.get(payment_id, [])

    def resolve_prefix(
        self, key: str, expected_amount_paisa: Optional[int] = None
    ) -> Optional[SettlementRecord]:
        """Resolve a truncated settlement key to exactly one settlement.

        Ambiguity is never broken by guessing. If the prefix maps to several
        settlements we require the payout amount to single one out; if it still
        does not, we return None and the caller reports the reference as
        unresolved rather than inventing a link.
        """
        if len(key) < MIN_PREFIX_LENGTH:
            return None
        candidate_ids = self.settlement_prefix_to_ids.get(key, [])
        if not candidate_ids:
            return None
        candidates = [self.settlements_by_id[cid] for cid in candidate_ids]
        if len(candidates) == 1:
            return candidates[0]
        if expected_amount_paisa is None:
            return None
        narrowed = [
            c for c in candidates if c.net_amount_paisa == expected_amount_paisa
        ]
        return narrowed[0] if len(narrowed) == 1 else None


def build_index(dataset: SourceDataset, rules=None) -> ReconciliationIndex:
    """Build every lookup in one pass.

    ``rules`` is an optional :class:`DynamicRuleSet` of promoted reference
    extraction rules. They run only where the built-in extractor produced
    nothing usable, so a promoted rule can add matches but can never override
    or displace one the built-in path already proved.
    """
    index = ReconciliationIndex()
    index.rules = rules

    for order in dataset.orders:
        index.orders_by_order_id[order.order_id] = order
        if order.payment_id:
            index.orders_by_payment_id[order.payment_id] = order

    for settlement in dataset.settlements:
        index.settlements_by_id[settlement.settlement_id] = settlement
        for pid in settlement.covered_payment_ids():
            if pid:
                index.settlements_by_payment_id[pid].append(settlement)
        key = settlement_numeric_key(settlement.settlement_id)
        if key:
            index.settlement_key_to_ids[key].append(settlement.settlement_id)
            for length in range(MIN_PREFIX_LENGTH, len(key) + 1):
                index.settlement_prefix_to_ids[key[:length]].append(
                    settlement.settlement_id
                )

    for bank in dataset.bank_transactions:
        extracted = extract_reference(bank.description, bank.reference)
        is_credit = bank.credit_amount_paisa > 0
        keys = list(extracted.numeric_keys)
        dynamic_keys: List[tuple] = []

        # A dynamic rule is a fallback, not an override. It runs only when no
        # built-in key resolves to a real settlement, so a promoted rule can
        # never take a bank row away from a link the base engine already proved.
        if rules and not any(k in index.settlement_key_to_ids for k in keys):
            for key, rule_id in rules.extract_keys(extracted.normalized):
                if key not in keys:
                    keys.append(key)
                dynamic_keys.append((key, rule_id))

        view = BankView(
            record=bank,
            numeric_keys=keys,
            looks_like_gateway_payout=(
                extracted.looks_like_gateway_payout or bool(dynamic_keys)
            ),
            is_credit=is_credit,
            dynamic_keys=dynamic_keys,
        )
        index.bank_views.append(view)
        index.bank_by_id[bank.bank_transaction_id] = view
        bucket = index.credits_by_key if is_credit else index.debits_by_key
        for key in keys:
            bucket[key].append(view)
        if is_credit:
            index.credits_by_amount[bank.credit_amount_paisa].append(view)

    for invoice in dataset.invoices:
        index.invoices_by_id[invoice.invoice_id] = invoice
        nkey = numeric_invoice_key(invoice.invoice_id)
        if nkey:
            index.invoices_by_numeric_key[nkey].append(invoice)

    return index
