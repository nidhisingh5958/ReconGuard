"""The deterministic reconciliation engine.

This module is the product. It depends on nothing outside the domain and the
service layer: no database, no API, no UI, no LLM. That is deliberate, and it
is what makes the engine testable in isolation and safe to benchmark.

Pipeline per run:

    build indexes        O(n)  one pass over every source
    resolve netting      O(n)  refunds and chargebacks become AdjustmentRecords
    reconcile payments   O(n)  index lookups only, no nested scans
    sweep bank residue   O(n)  credits nobody claimed become honest exceptions
    compute metrics      O(n)  measured from this run, never hardcoded

Ordering guarantees: payments are processed in sorted order, so bank credits
are claimed reproducibly and two runs over identical input produce identical
output including ids.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.core.config import AccountingConfig, ReconciliationConfig, get_settings
from app.core.ids import SequenceIdFactory
from app.core.versioning import ENGINE_VERSION
from app.domain.enums import (
    AuditAction,
    ConfidenceMethod,
    MatchType,
    ReasonCode,
    ReconciliationStatus,
)
from app.domain.reconciliation import (
    AdjustmentRecord,
    CalculationLine,
    Evidence,
    ReconciliationResult,
    RunMetrics,
)
from app.domain.sources import OrderRecord, SourceDataset
from app.services.accounting.fees import compute_fee_breakdown
from app.services.accounting.invariants import verify_component_invariant
from app.services.audit.ledger import AuditLedger
from app.services.metrics.calculator import compute_run_metrics
from app.services.reconciliation.classification import classify, dedupe_reason_codes
from app.services.reconciliation.confidence import weakest_link
from app.services.reconciliation.indexes import BankView, ReconciliationIndex, build_index
from app.services.reconciliation.layers.aggregation import (
    Relationship,
    SettlementGroup,
    group_settlements,
)
from app.services.reconciliation.layers.bank_matching import BankMatcher
from app.services.reconciliation.layers.identifiers import link_invoice
from app.services.reconciliation.layers.netting import NettingResult, resolve_netting

RULE_MISSING_SETTLEMENT = "RULE-CLS-001"
RULE_UNKNOWN_CREDIT = "RULE-CLS-002"
RULE_DELAYED_SETTLEMENT = "RULE-CLS-003"
RULE_GROSS_MISMATCH = "RULE-CLS-004"


@dataclass
class ReconciliationOutput:
    """Everything one run produced. Persistence is somebody else's problem."""

    results: List[ReconciliationResult] = field(default_factory=list)
    adjustments: List[AdjustmentRecord] = field(default_factory=list)
    audit_events: List = field(default_factory=list)
    metrics: Optional[RunMetrics] = None

    def by_status(self, status: ReconciliationStatus) -> List[ReconciliationResult]:
        return [r for r in self.results if r.status is status]


class ReconciliationEngine:
    """Deterministic, LLM-free reconciliation over a SourceDataset."""

    version = ENGINE_VERSION

    def __init__(
        self,
        accounting: Optional[AccountingConfig] = None,
        reconciliation: Optional[ReconciliationConfig] = None,
        rules=None,
    ) -> None:
        settings = get_settings()
        self.accounting = accounting or settings.accounting
        self.config = reconciliation or settings.reconciliation
        #: Promoted dynamic rules, or None. The engine is fully functional
        #: without them; they only add matches the built-in layers missed.
        self.rules = rules

    # ------------------------------------------------------------------
    def run(self, dataset: SourceDataset, run_id: str = "RUN-00000") -> ReconciliationOutput:
        started_at = datetime.now(timezone.utc)
        clock = time.perf_counter()

        ledger = AuditLedger(run_id=run_id)
        ledger.record(
            AuditAction.RUN_STARTED,
            calculation=(
                f"dataset={dataset.dataset_id} mode={dataset.mode} "
                f"orders={len(dataset.orders)} settlements={len(dataset.settlements)} "
                f"bank={len(dataset.bank_transactions)} "
                f"invoices={len(dataset.invoices)}"
            ),
            detail={
                "engine_version": self.version,
                "active_dynamic_rules": (
                    self.rules.rule_ids if self.rules else []
                ),
                "accounting": self.accounting.describe(),
                "rounding_tolerance_paisa": self.config.rounding_tolerance_paisa,
                "settlement_date_tolerance_days": (
                    self.config.settlement_date_tolerance_days
                ),
            },
        )

        index = build_index(dataset, rules=self.rules)
        ledger.record(
            AuditAction.DATA_INGESTED,
            calculation=(
                f"indexed {len(index.orders_by_order_id)} orders, "
                f"{len(index.settlements_by_id)} settlements, "
                f"{len(index.bank_views)} bank rows, "
                f"{len(index.invoices_by_id)} invoices"
            ),
        )

        netting = resolve_netting(index)
        for adjustments in netting.adjustments_by_settlement.values():
            for adjustment in adjustments:
                ledger.record(
                    AuditAction.ADJUSTMENT_RECORDED,
                    source_records=[adjustment.source_record],
                    rule_id="RULE-NET-010",
                    calculation=adjustment.description,
                    evidence=[e.record_id for e in adjustment.evidence],
                    detail={"adjustment": adjustment.to_dict()},
                )

        matcher = BankMatcher(index, self.config)
        ids = SequenceIdFactory("REC", width=5)
        results: List[ReconciliationResult] = []
        all_adjustments: List[AdjustmentRecord] = []

        for order in sorted(dataset.orders, key=lambda o: o.order_id):
            result = self._reconcile_order(order, index, matcher, netting, ids, ledger)
            results.append(result)
            all_adjustments.extend(result.adjustments)

        results.extend(self._sweep_unclaimed_credits(matcher, ids, ledger))

        elapsed_ms = (time.perf_counter() - clock) * 1000.0
        completed_at = datetime.now(timezone.utc)

        metrics = compute_run_metrics(
            run_id=run_id,
            results=results,
            dataset=dataset,
            started_at=started_at,
            completed_at=completed_at,
            processing_time_ms=elapsed_ms,
            engine_version=self.version,
        )

        ledger.record(
            AuditAction.RUN_COMPLETED,
            calculation=(
                f"{metrics.deterministic_matches}/{metrics.records_processed} matched "
                f"= {metrics.match_rate:.4f}; residuals {metrics.residuals}; "
                f"{metrics.processing_time_ms:.1f} ms; "
                f"{metrics.throughput_rps:.1f} records/sec"
            ),
            detail={
                "records_processed": metrics.records_processed,
                "deterministic_matches": metrics.deterministic_matches,
                "residuals": metrics.residuals,
                "exceptions": metrics.exceptions,
                "unexplained_value_paisa": metrics.unexplained_value_paisa,
            },
        )

        return ReconciliationOutput(
            results=results,
            adjustments=all_adjustments,
            audit_events=ledger.events,
            metrics=metrics,
        )

    # ------------------------------------------------------------------
    def _reconcile_order(
        self,
        order: OrderRecord,
        index: ReconciliationIndex,
        matcher: BankMatcher,
        netting: NettingResult,
        ids: SequenceIdFactory,
        ledger: AuditLedger,
    ) -> ReconciliationResult:
        reconciliation_id = ids.next()
        settlements = index.settlements_for_payment(order.payment_id)
        invoice_link = link_invoice(order, index)

        expected = compute_fee_breakdown(order.gross_amount_paisa, self.accounting)

        # --- no settlement at all: an honest dead end --------------------
        if not settlements:
            evidence = [
                Evidence(
                    source="ORDERS",
                    record_id=order.order_id,
                    fact=(
                        f"Order {order.order_id} captured payment "
                        f"{order.payment_id} for {order.gross_amount_paisa} paise on "
                        f"{order.order_date.isoformat()}, status {order.status!r}"
                    ),
                    amount_paisa=order.gross_amount_paisa,
                ),
                Evidence(
                    source="SETTLEMENTS",
                    record_id="(none)",
                    fact=(
                        f"No settlement record covers payment {order.payment_id}"
                    ),
                    detail={"rule_id": RULE_MISSING_SETTLEMENT},
                ),
            ] + invoice_link.evidence
            result = ReconciliationResult(
                reconciliation_id=reconciliation_id,
                status=ReconciliationStatus.EXCEPTION,
                match_type=MatchType.NONE,
                confidence=0.0,
                confidence_method=ConfidenceMethod.NOT_ESTABLISHED,
                source_records=[order.order_id, order.payment_id],
                expected_amount_paisa=expected.net_amount_paisa,
                actual_amount_paisa=0,
                variance_paisa=-expected.net_amount_paisa,
                reason_codes=dedupe_reason_codes(
                    [ReasonCode.MISSING_SETTLEMENT] + invoice_link.reason_codes
                ),
                calculation=list(expected.lines),
                evidence=evidence,
                order_id=order.order_id,
                payment_id=order.payment_id,
                invoice_id=(
                    invoice_link.invoice.invoice_id if invoice_link.found else None
                ),
                counterparty=order.customer_name,
                gross_amount_paisa=order.gross_amount_paisa,
                value_date=order.order_date,
                rule_ids=[RULE_MISSING_SETTLEMENT],
            )
            self._audit(ledger, result, AuditAction.RECONCILIATION_EXCEPTION)
            return result

        # --- shape the payment/payout relationship (Layer 4) -------------
        group = group_settlements(order, settlements, index)
        reason_codes: List[ReasonCode] = list(group.reason_codes)
        evidence: List[Evidence] = list(group.evidence)
        rule_ids: List[str] = list(group.rule_ids)
        methods: List[ConfidenceMethod] = [ConfidenceMethod.EXACT_IDENTIFIER]

        evidence.insert(
            0,
            Evidence(
                source="ORDERS",
                record_id=order.order_id,
                fact=(
                    f"Order {order.order_id} carries payment {order.payment_id}, "
                    f"gross {order.gross_amount_paisa} paise"
                ),
                amount_paisa=order.gross_amount_paisa,
                detail={"rule_id": "RULE-MATCH-000"},
            ),
        )

        # --- netting (Layer 5) -------------------------------------------
        adjustments: List[AdjustmentRecord] = []
        for settlement in group.settlements:
            adjustments.extend(netting.for_settlement(settlement.settlement_id))
        for adjustment in adjustments:
            evidence.extend(adjustment.evidence)
            if adjustment.related_payment == order.payment_id:
                reason_codes.append(ReasonCode.PARTIAL_REFUND)
            else:
                reason_codes.append(ReasonCode.REFUND_NETTED)

        # --- accounting invariant (Layer 2) ------------------------------
        check = verify_component_invariant(
            component_gross_amounts=group.component_gross_amounts,
            reported_gateway_fee_paisa=group.reported_fee_paisa,
            reported_gst_paisa=group.reported_gst_paisa,
            reported_tds_paisa=group.reported_tds_paisa,
            reported_refund_adjustment_paisa=group.reported_refund_paisa,
            reported_net_paisa=group.reported_net_paisa,
            config=self.accounting,
            rounding_tolerance_paisa=self.config.rounding_tolerance_paisa,
        )
        reason_codes.extend(check.reason_codes)
        calculation: List[CalculationLine] = list(check.lines)
        rule_ids.append("RULE-NET-001")

        methods.append(
            ConfidenceMethod.ACCOUNTING_INVARIANT
            if check.holds_exactly
            else (
                ConfidenceMethod.ACCOUNTING_INVARIANT_WITHIN_ROUNDING_TOLERANCE
                if check.within_tolerance
                else ConfidenceMethod.NOT_ESTABLISHED
            )
        )

        for settlement in group.settlements:
            evidence.append(
                Evidence(
                    source="SETTLEMENTS",
                    record_id=settlement.settlement_id,
                    fact=(
                        f"Settlement {settlement.settlement_id} reports gross "
                        f"{settlement.gross_amount_paisa}, fee "
                        f"{settlement.gateway_fee_paisa}, GST "
                        f"{settlement.gst_on_fee_paisa}, TDS {settlement.tds_paisa}, "
                        f"refund adj {settlement.refund_adjustment_paisa}, net "
                        f"{settlement.net_amount_paisa} paise, value date "
                        f"{settlement.settlement_date.isoformat()}"
                    ),
                    amount_paisa=settlement.net_amount_paisa,
                    detail={"rule_id": "RULE-NET-001"},
                )
            )

        # --- gross reconciliation across legs ----------------------------
        if group.relationship in (Relationship.SPLIT, Relationship.SIMPLE):
            covered_gross = group.reported_gross_paisa
            if covered_gross != order.gross_amount_paisa:
                reason_codes.append(ReasonCode.NET_AMOUNT_VARIANCE)
                rule_ids.append(RULE_GROSS_MISMATCH)
                calculation.append(
                    CalculationLine(
                        label="Gross coverage variance",
                        expression=(
                            f"settlement gross {covered_gross} - order gross "
                            f"{order.gross_amount_paisa} = "
                            f"{covered_gross - order.gross_amount_paisa}"
                        ),
                        result_paisa=covered_gross - order.gross_amount_paisa,
                        rule_id=RULE_GROSS_MISMATCH,
                    )
                )

        # --- delayed payout ----------------------------------------------
        latest = max(s.settlement_date for s in group.settlements)
        lag_days = (latest - order.order_date).days
        if lag_days > self.config.delayed_settlement_flag_days:
            reason_codes.append(ReasonCode.DELAYED_SETTLEMENT)
            rule_ids.append(RULE_DELAYED_SETTLEMENT)
            evidence.append(
                Evidence(
                    source="SETTLEMENTS",
                    record_id=group.primary.settlement_id,
                    fact=(
                        f"Payout landed {lag_days} days after the order, against an "
                        f"expected cycle of T+"
                        f"{self.config.expected_settlement_lag_days}"
                    ),
                    detail={"rule_id": RULE_DELAYED_SETTLEMENT, "lag_days": lag_days},
                )
            )

        # --- bank side (Layers 1 and 3) ----------------------------------
        bank_ids: List[str] = []
        bank_total = 0
        bank_found = False
        for settlement in group.settlements:
            bank_match = matcher.match(settlement)
            reason_codes.extend(bank_match.reason_codes)
            evidence.extend(bank_match.evidence)
            rule_ids.extend(bank_match.rule_ids)
            if bank_match.found:
                bank_found = True
                bank_ids.extend(bank_match.transaction_ids)
                bank_total += bank_match.total_credit_paisa
                methods.append(bank_match.method)

        # --- chargebacks --------------------------------------------------
        chargeback_total = 0
        for settlement in group.settlements:
            for chargeback in netting.chargebacks_for(settlement.settlement_id):
                adjustments.append(chargeback)
                chargeback_total += chargeback.amount_paisa
                evidence.extend(chargeback.evidence)
                reason_codes.append(ReasonCode.CHARGEBACK)
                calculation.append(
                    CalculationLine(
                        label="Chargeback reversal",
                        expression=(
                            f"payout {settlement.net_amount_paisa} reversed by debit "
                            f"{chargeback.amount_paisa} on "
                            f"{chargeback.source_record}"
                        ),
                        result_paisa=-chargeback.amount_paisa,
                        rule_id="RULE-NET-011",
                    )
                )

        # --- duplicates ----------------------------------------------------
        expected_amount = check.expected_net_paisa
        actual_amount = group.reported_net_paisa
        if group.relationship is Relationship.DUPLICATE:
            # Exposure is what a naive sum of the ledger would show, so the
            # duplicated amount surfaces as variance instead of vanishing.
            actual_amount = group.reported_net_paisa + group.duplicate_net_paisa
        elif bank_found and ReasonCode.DUPLICATE_BANK_TRANSACTION in reason_codes:
            actual_amount = bank_total

        if chargeback_total:
            # The cash arrived and then left again. Net retained value is what
            # the business actually keeps, so the reversal has to move the
            # actual figure; leaving it at the gross payout would report a
            # reversed transaction as fully settled with zero exposure.
            actual_amount -= chargeback_total

        reason_codes.extend(invoice_link.reason_codes)
        evidence.extend(invoice_link.evidence)
        rule_ids.extend(invoice_link.rule_ids)

        reason_codes = dedupe_reason_codes(reason_codes)
        status = classify(
            has_settlement=True,
            invariant_proved=check.proved,
            bank_found=bank_found,
            has_duplicates=group.relationship is Relationship.DUPLICATE,
            reason_codes=reason_codes,
        )

        confidence, method = weakest_link(methods)
        if status in (
            ReconciliationStatus.EXCEPTION,
            ReconciliationStatus.UNRESOLVED,
        ):
            confidence, method = 0.0, ConfidenceMethod.NOT_ESTABLISHED

        source_records = (
            [order.order_id, order.payment_id]
            + group.all_settlement_ids
            + bank_ids
            + ([invoice_link.invoice.invoice_id] if invoice_link.found else [])
        )

        result = ReconciliationResult(
            reconciliation_id=reconciliation_id,
            status=status,
            match_type=group.match_type,
            confidence=confidence,
            confidence_method=method,
            source_records=source_records,
            expected_amount_paisa=expected_amount,
            actual_amount_paisa=actual_amount,
            variance_paisa=actual_amount - expected_amount,
            reason_codes=reason_codes,
            calculation=calculation,
            evidence=evidence,
            adjustments=adjustments,
            order_id=order.order_id,
            payment_id=order.payment_id,
            settlement_ids=group.all_settlement_ids,
            bank_transaction_ids=bank_ids,
            invoice_id=invoice_link.invoice.invoice_id if invoice_link.found else None,
            counterparty=order.customer_name,
            gross_amount_paisa=order.gross_amount_paisa,
            value_date=latest,
            rule_ids=sorted(set(rule_ids)),
        )

        action = {
            ReconciliationStatus.MATCHED: AuditAction.RECONCILIATION_MATCH,
            ReconciliationStatus.PARTIAL_MATCH: AuditAction.RECONCILIATION_PARTIAL,
            ReconciliationStatus.DUPLICATE: AuditAction.RECONCILIATION_DUPLICATE,
        }.get(status, AuditAction.RECONCILIATION_EXCEPTION)
        self._audit(ledger, result, action)
        ledger.record(
            AuditAction.INVARIANT_VERIFIED
            if check.proved
            else AuditAction.INVARIANT_VIOLATED,
            reconciliation_id=reconciliation_id,
            source_records=group.all_settlement_ids,
            rule_id="RULE-NET-001",
            calculation=(
                f"expected {check.expected_net_paisa} vs reported "
                f"{check.actual_net_paisa}, variance {check.variance_paisa}"
            ),
            detail={"component_variances": check.component_variances},
        )
        return result

    # ------------------------------------------------------------------
    def _sweep_unclaimed_credits(
        self, matcher: BankMatcher, ids: SequenceIdFactory, ledger: AuditLedger
    ) -> List[ReconciliationResult]:
        """Bank credits nothing accounted for become explicit exceptions.

        These are never silently dropped and never speculatively attached to a
        nearby order. An unidentified credit is a real finance problem and it
        is reported as one.
        """
        results: List[ReconciliationResult] = []
        for view in matcher.unclaimed_credits():
            record = view.record
            reconciliation_id = ids.next()
            result = ReconciliationResult(
                reconciliation_id=reconciliation_id,
                status=ReconciliationStatus.EXCEPTION,
                match_type=MatchType.NONE,
                confidence=0.0,
                confidence_method=ConfidenceMethod.NOT_ESTABLISHED,
                source_records=[record.bank_transaction_id],
                expected_amount_paisa=0,
                actual_amount_paisa=record.credit_amount_paisa,
                variance_paisa=record.credit_amount_paisa,
                reason_codes=[ReasonCode.UNKNOWN_BANK_CREDIT],
                calculation=[
                    CalculationLine(
                        label="Unidentified credit",
                        expression=(
                            f"bank credit {record.credit_amount_paisa} paise with no "
                            f"matching order, settlement or invoice"
                        ),
                        result_paisa=record.credit_amount_paisa,
                        rule_id=RULE_UNKNOWN_CREDIT,
                    )
                ],
                evidence=[
                    Evidence(
                        source="BANK",
                        record_id=record.bank_transaction_id,
                        fact=(
                            f"Credit of {record.credit_amount_paisa} paise on "
                            f"{record.transaction_date.isoformat()}, narration "
                            f"{record.description!r}"
                        ),
                        amount_paisa=record.credit_amount_paisa,
                        detail={
                            "rule_id": RULE_UNKNOWN_CREDIT,
                            "extracted_keys": view.numeric_keys,
                            "looks_like_gateway_payout": (
                                view.looks_like_gateway_payout
                            ),
                            # The raw narration is carried structurally so a
                            # rule proposer can induce a pattern from it later
                            # without re-parsing a prose sentence.
                            "narration": record.description,
                            "reference": record.reference,
                        },
                    ),
                    Evidence(
                        source="SETTLEMENTS",
                        record_id="(none)",
                        fact=(
                            "No settlement key in the narration resolves to a known "
                            "payout, and no unmatched payout shares this amount "
                            "inside the date window"
                        ),
                    ),
                ],
                bank_transaction_ids=[record.bank_transaction_id],
                counterparty="UNKNOWN",
                gross_amount_paisa=record.credit_amount_paisa,
                value_date=record.transaction_date,
                rule_ids=[RULE_UNKNOWN_CREDIT],
            )
            results.append(result)
            self._audit(ledger, result, AuditAction.RECONCILIATION_EXCEPTION)
        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _audit(
        ledger: AuditLedger, result: ReconciliationResult, action: AuditAction
    ) -> None:
        headline = next(
            (
                line
                for line in result.calculation
                if line.label
                in (
                    "Invariant verified",
                    "Net settlement variance",
                    "Rounding tolerance applied",
                    "Unidentified credit",
                )
            ),
            result.calculation[-1] if result.calculation else None,
        )
        ledger.record(
            action,
            reconciliation_id=result.reconciliation_id,
            source_records=result.source_records,
            rule_id=result.rule_ids[0] if result.rule_ids else None,
            calculation=headline.expression if headline else "",
            previous_state="UNRECONCILED",
            new_state=result.status.value,
            evidence=[e.record_id for e in result.evidence],
            detail={
                "match_type": result.match_type.value,
                "confidence": result.confidence,
                "confidence_method": result.confidence_method.value,
                "reason_codes": [c.value for c in result.reason_codes],
                "expected_amount_paisa": result.expected_amount_paisa,
                "actual_amount_paisa": result.actual_amount_paisa,
                "variance_paisa": result.variance_paisa,
            },
        )
