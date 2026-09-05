"""Layer 1 - exact identifier matching on the commercial side.

Links an order to its invoice, and confirms the counterparty. Both links are
established by exact lookup, either on the raw identifier or on a normalized
key produced by a named, deterministic rule. Neither uses similarity scoring.

The invoice typo case is worth spelling out. A register that records INV-1O001
for INV-10001 has not created a new invoice, it has recorded a character-level
transcription error. Folding the standard O/0, I/1, S/5, B/8 confusions is a
fixed rule, so the fold is reproducible and can be shown as evidence. We still
require the folded key to identify exactly one invoice before using it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.domain.enums import ConfidenceMethod, ReasonCode
from app.domain.reconciliation import Evidence
from app.domain.sources import InvoiceRecord, OrderRecord
from app.services.normalization.text import counterparty_key, numeric_invoice_key
from app.services.reconciliation.indexes import ReconciliationIndex

RULE_INVOICE_EXACT = "RULE-MATCH-020"
RULE_INVOICE_TYPO = "RULE-MATCH-021"
RULE_COUNTERPARTY = "RULE-MATCH-022"


@dataclass
class InvoiceLink:
    invoice: Optional[InvoiceRecord] = None
    method: ConfidenceMethod = ConfidenceMethod.NOT_ESTABLISHED
    reason_codes: List[ReasonCode] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    rule_ids: List[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.invoice is not None


def link_invoice(order: OrderRecord, index: ReconciliationIndex) -> InvoiceLink:
    """Resolve the invoice for an order, exact id first, folded key second."""
    exact = index.invoices_by_id.get(order.invoice_id)
    if exact is not None:
        link = InvoiceLink(
            invoice=exact,
            method=ConfidenceMethod.EXACT_IDENTIFIER,
            rule_ids=[RULE_INVOICE_EXACT],
            evidence=[
                Evidence(
                    source="INVOICES",
                    record_id=exact.invoice_id,
                    fact=(
                        f"Invoice {exact.invoice_id} matches the order invoice "
                        f"reference exactly; total {exact.total_amount_paisa} paise"
                    ),
                    amount_paisa=exact.total_amount_paisa,
                    detail={"rule_id": RULE_INVOICE_EXACT},
                )
            ],
        )
        _check_counterparty(order, exact, link)
        return link

    folded = numeric_invoice_key(order.invoice_id)
    candidates = index.invoices_by_numeric_key.get(folded, []) if folded else []
    if len(candidates) == 1:
        invoice = candidates[0]
        link = InvoiceLink(
            invoice=invoice,
            method=ConfidenceMethod.EXACT_IDENTIFIER,
            reason_codes=[ReasonCode.INVOICE_TYPO_RESOLVED],
            rule_ids=[RULE_INVOICE_TYPO],
            evidence=[
                Evidence(
                    source="INVOICES",
                    record_id=invoice.invoice_id,
                    fact=(
                        f"Order references {order.invoice_id}; the register holds "
                        f"{invoice.invoice_id}. Both fold to key {folded} under the "
                        f"character-confusion rule, and the key is unique"
                    ),
                    amount_paisa=invoice.total_amount_paisa,
                    detail={
                        "rule_id": RULE_INVOICE_TYPO,
                        "order_invoice_id": order.invoice_id,
                        "register_invoice_id": invoice.invoice_id,
                        "folded_key": folded,
                    },
                )
            ],
        )
        _check_counterparty(order, invoice, link)
        return link

    return InvoiceLink(
        method=ConfidenceMethod.NOT_ESTABLISHED,
        reason_codes=[ReasonCode.INVOICE_LINK_BROKEN],
        rule_ids=[RULE_INVOICE_EXACT],
        evidence=[
            Evidence(
                source="ORDERS",
                record_id=order.order_id,
                fact=(
                    f"No invoice found for reference {order.invoice_id!r} "
                    f"(folded key {folded!r} matched {len(candidates)} invoices)"
                ),
                detail={"rule_id": RULE_INVOICE_EXACT},
            )
        ],
    )


def _check_counterparty(
    order: OrderRecord, invoice: InvoiceRecord, link: InvoiceLink
) -> None:
    """Flag a resolved alias so the operator sees the names differ but agree."""
    order_key = counterparty_key(order.customer_name)
    invoice_key = counterparty_key(invoice.customer_name)
    if order_key == invoice_key and order.customer_name != invoice.customer_name:
        link.reason_codes.append(ReasonCode.COUNTERPARTY_ALIAS_RESOLVED)
        link.rule_ids.append(RULE_COUNTERPARTY)
        link.evidence.append(
            Evidence(
                source="INVOICES",
                record_id=invoice.invoice_id,
                fact=(
                    f"Counterparty alias resolved: order says "
                    f"{order.customer_name!r}, invoice says "
                    f"{invoice.customer_name!r}; both normalize to {order_key!r}"
                ),
                detail={"rule_id": RULE_COUNTERPARTY},
            )
        )
