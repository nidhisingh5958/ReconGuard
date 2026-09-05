"""Deterministic synthetic financial dataset generator.

Two modes:

* ``clean`` - a perfectly reconciling world. Every order has exactly one
  settlement, one bank credit and one invoice. A correct engine must score a
  100% match rate here; anything less is an engine bug, which makes clean mode
  the strongest regression test we have.
* ``messy`` - clean mode plus eighteen classes of deliberately injected,
  individually labelled anomalies.

Determinism is a hard requirement: the same seed always produces byte-identical
output, so a match-rate change between two runs is always attributable to an
engine change and never to data drift.

Every injected anomaly is written to a ground-truth file with a machine label.
That file is what allows precision and recall to be measured. It is NEVER
served to the operator-facing reconciliation UI.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import AccountingConfig
from app.domain.enums import AnomalyType, ReasonCode, ReconciliationStatus
from app.services.accounting.fees import compute_fee_breakdown

# --- static reference data (deterministic, no randomness at import time) -----

CUSTOMER_NAMES: Tuple[str, ...] = (
    "Acme Retail", "Nimbus Logistics", "Sundara Textiles", "Vertex Analytics",
    "Kaveri Foods", "Blue Orbit Media", "Pinnacle Interiors", "Meridian Health",
    "Trident Motors", "Lotus Fintech", "Sierra Components", "Harbour Exports",
    "Vidya Publishers", "Quantum Ceramics", "Ashoka Agro", "Northwind Travel",
    "Silverline Pharma", "Coral Reef Apparel", "Ganga Cements", "Zenith Robotics",
    "Peacock Handlooms", "Basalt Infra", "Marigold Events", "Deccan Optics",
    "Solstice Energy", "Ivory Lane Furniture", "Rapid Freight", "Konark Jewellers",
    "Tulip Cosmetics", "Everest Sporting", "Banyan Legal", "Citrus Beverages",
    "Falcon Security", "Indigo Looms", "Jasmine Dairy", "Kestrel Aviation",
    "Lantern Studios", "Monsoon Rainwear", "Nectar Confectionery", "Orchid Realty",
)

#: Bank narration templates. The bank is the messiest source in the pipeline,
#: so the same settlement legitimately appears in several shapes.
BANK_DESCRIPTION_TEMPLATES: Tuple[str, ...] = (
    "RAZORPAY SETTLEMENT SET-{num}",
    "RAZORPAY SETTLE {num}",
    "RZP SET-{num}",
    "Settlement payout / {num}",
    "NEFT-RZPSET{num}-HDFC",
    "RZP  SETTLEMENT   SET-{num}",
    "rzp set-{num}",
    "RAZORPAY SOFTWARE PVT LTD SET-{num}",
)

#: Alternative date renderings used in messy mode to force real normalization.
BANK_DATE_FORMATS: Tuple[str, ...] = ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y")

#: A narration format the built-in extractor genuinely cannot parse. The digits
#: carry a two-character acquirer prefix, so the digit-run extractor recovers
#: "9910291" rather than the settlement key "10291", and no gateway marker is
#: present so the amount-and-date fallback declines it too. This is the gap a
#: promoted rule closes; see docs/self-healing-rules.md.
UNRECOGNISED_REFERENCE_TEMPLATE = "ACH CR//PGWX/99{num}/MERCHANT ACCT"
UNRECOGNISED_REFERENCE_PREFIX = "99"
UNRECOGNISED_REFERENCE_MARKER = "PGWX"

UNKNOWN_CREDIT_DESCRIPTIONS: Tuple[str, ...] = (
    "NEFT CR-HDFC0000123-VENDOR REFUND-9928371",
    "IMPS INWARD 883712 MISC CREDIT",
    "RTGS CR UTIB0000456 UNIDENTIFIED REMITTER",
    "CASH DEPOSIT BRANCH 2291",
    "INWARD CLEARING CHQ 447120",
)

#: Anomaly mix per 500 orders. Scaled proportionally for other dataset sizes.
ANOMALY_MIX: Tuple[Tuple[AnomalyType, int], ...] = (
    (AnomalyType.MISSING_SETTLEMENT, 6),
    (AnomalyType.DUPLICATE_SETTLEMENT, 4),
    (AnomalyType.MISSING_BANK_TRANSACTION, 6),
    (AnomalyType.DUPLICATE_BANK_TRANSACTION, 4),
    (AnomalyType.INVOICE_TYPO, 4),
    (AnomalyType.CUSTOMER_NAME_ALIAS, 5),
    (AnomalyType.DATE_FORMAT_DIFFERENCE, 5),
    (AnomalyType.ROUNDING_ERROR, 5),
    (AnomalyType.PARTIAL_REFUND, 5),
    (AnomalyType.NETTED_REFUND, 5),
    (AnomalyType.AGGREGATED_SETTLEMENT, 4),   # each consumes 3 orders
    (AnomalyType.SPLIT_SETTLEMENT, 4),
    (AnomalyType.DELAYED_SETTLEMENT, 5),
    (AnomalyType.CHARGEBACK, 3),
    (AnomalyType.TDS_DISCREPANCY, 4),
    (AnomalyType.GST_DISCREPANCY, 4),
    (AnomalyType.TRUNCATED_BANK_REFERENCE, 5),
    (AnomalyType.UNKNOWN_BANK_CREDIT, 4),     # consumes no order
    (AnomalyType.UNRECOGNISED_REFERENCE_FORMAT, 6),
)

AGGREGATION_GROUP_SIZE = 3


@dataclass(slots=True)
class GeneratorConfig:
    order_count: int = 500
    seed: int = 42
    mode: str = "messy"
    start_date: date = date(2026, 6, 1)
    day_span: int = 90
    accounting: AccountingConfig = field(default_factory=AccountingConfig)
    settlement_lag_days: int = 2
    dataset_id: str = "seed-500"


@dataclass(slots=True)
class GeneratedDataset:
    """JSON-ready output. All monetary values are integer paise."""

    orders: List[Dict[str, Any]] = field(default_factory=list)
    settlements: List[Dict[str, Any]] = field(default_factory=list)
    bank_transactions: List[Dict[str, Any]] = field(default_factory=list)
    invoices: List[Dict[str, Any]] = field(default_factory=list)
    ground_truth: List[Dict[str, Any]] = field(default_factory=list)
    manifest: Dict[str, Any] = field(default_factory=dict)


def _gstin(index: int) -> str:
    """Deterministic, structurally plausible (not real) GSTIN."""
    state = 20 + (index % 17)
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    pan = (
        f"{letters[index % 24]}{letters[(index // 3) % 24]}{letters[(index // 7) % 24]}"
        f"CU{(index % 9000) + 1000}"
        f"{letters[(index // 11) % 24]}"
    )
    return f"{state:02d}{pan}1Z{index % 10}"


class SyntheticDataGenerator:
    """Builds a full four-source financial dataset with labelled anomalies."""

    def __init__(self, config: Optional[GeneratorConfig] = None) -> None:
        self.config = config or GeneratorConfig()
        self.rng = random.Random(self.config.seed)
        self._anomaly_seq = 0
        self.ground_truth: List[Dict[str, Any]] = []

    # -- ids ---------------------------------------------------------------
    @staticmethod
    def _order_id(i: int) -> str:
        return f"ORD-{10001 + i}"

    @staticmethod
    def _payment_id(i: int) -> str:
        return f"PAY-{89001 + i}"

    @staticmethod
    def _invoice_id(i: int) -> str:
        return f"INV-{10001 + i}"

    @staticmethod
    def _settlement_id(n: int) -> str:
        return f"SET-{10001 + n}"

    @staticmethod
    def _bank_id(n: int) -> str:
        return f"BANK-{77001 + n}"

    def _next_anomaly_id(self) -> str:
        self._anomaly_seq += 1
        return f"GT-{self._anomaly_seq:05d}"

    def _label(
        self,
        anomaly_type: AnomalyType,
        description: str,
        expected_status: ReconciliationStatus,
        expected_reason_codes: List[ReasonCode],
        amount_paisa: int = 0,
        detected_on: str = "order",
        **refs: Any,
    ) -> None:
        """Record one ground-truth label.

        ``detected_on`` names which reconciliation record is expected to carry
        the detection. It is usually the order, but not always: a refund netted
        into an unrelated payout is labelled against the REFUNDED order while
        the engine raises it on the record owning the HOST settlement, and an
        unidentified credit has no order at all. Stating this explicitly is
        what lets recall be measured per record rather than only in aggregate.
        """
        self.ground_truth.append(
            {
                "anomaly_id": self._next_anomaly_id(),
                "anomaly_type": anomaly_type.value,
                "description": description,
                "expected_status": expected_status.value,
                "expected_reason_codes": [c.value for c in expected_reason_codes],
                "amount_paisa": amount_paisa,
                "detected_on": detected_on,
                "order_id": refs.get("order_id"),
                "payment_id": refs.get("payment_id"),
                "settlement_id": refs.get("settlement_id"),
                "bank_transaction_id": refs.get("bank_transaction_id"),
                "invoice_id": refs.get("invoice_id"),
            }
        )

    # -- planning ----------------------------------------------------------
    def _scaled_mix(self) -> Dict[AnomalyType, int]:
        """Scale the reference anomaly mix to the requested dataset size."""
        if self.config.mode == "clean":
            return {}
        factor = self.config.order_count / 500.0
        mix: Dict[AnomalyType, int] = {}
        for anomaly, count in ANOMALY_MIX:
            scaled = max(1, round(count * factor)) if count else 0
            mix[anomaly] = scaled
        return mix

    def _assign(self, mix: Dict[AnomalyType, int]) -> Tuple[Dict[int, AnomalyType], List[List[int]]]:
        """Deterministically allocate order indexes to anomaly classes.

        Aggregation needs a contiguous group of orders, so it is allocated
        first out of a shuffled pool; everything else takes single indexes.
        """
        pool = list(range(self.config.order_count))
        self.rng.shuffle(pool)
        cursor = 0
        assignment: Dict[int, AnomalyType] = {}
        aggregation_groups: List[List[int]] = []

        group_count = mix.get(AnomalyType.AGGREGATED_SETTLEMENT, 0)
        for _ in range(group_count):
            if cursor + AGGREGATION_GROUP_SIZE > len(pool):
                break
            group = pool[cursor : cursor + AGGREGATION_GROUP_SIZE]
            cursor += AGGREGATION_GROUP_SIZE
            aggregation_groups.append(group)
            for idx in group:
                assignment[idx] = AnomalyType.AGGREGATED_SETTLEMENT

        for anomaly, count in mix.items():
            if anomaly in (
                AnomalyType.AGGREGATED_SETTLEMENT,
                AnomalyType.UNKNOWN_BANK_CREDIT,
            ):
                continue
            for _ in range(count):
                if cursor >= len(pool):
                    break
                assignment[pool[cursor]] = anomaly
                cursor += 1

        return assignment, aggregation_groups

    # -- base records ------------------------------------------------------
    def _gross_amount_paisa(self) -> int:
        """A realistic order value in paise, always a whole number of rupees."""
        bucket = self.rng.random()
        if bucket < 0.55:
            rupees = self.rng.randint(500, 15_000)
        elif bucket < 0.9:
            rupees = self.rng.randint(15_000, 90_000)
        else:
            rupees = self.rng.randint(90_000, 450_000)
        return rupees * 100

    def _order_date(self, i: int) -> date:
        offset = self.rng.randint(0, self.config.day_span - 1)
        return self.config.start_date + timedelta(days=offset)

    def generate(self) -> GeneratedDataset:
        cfg = self.config
        mix = self._scaled_mix()
        assignment, aggregation_groups = self._assign(mix)

        orders: List[Dict[str, Any]] = []
        base: List[Dict[str, Any]] = []
        for i in range(cfg.order_count):
            customer_index = i % len(CUSTOMER_NAMES)
            base.append(
                {
                    "index": i,
                    "order_id": self._order_id(i),
                    "customer_id": f"CUS-{100 + customer_index}",
                    "customer_name": CUSTOMER_NAMES[customer_index],
                    "customer_index": customer_index,
                    "invoice_id": self._invoice_id(i),
                    "payment_id": self._payment_id(i),
                    "gross_amount": self._gross_amount_paisa(),
                    "order_date": self._order_date(i),
                    "anomaly": assignment.get(i),
                }
            )

        settlements: List[Dict[str, Any]] = []
        bank_rows: List[Dict[str, Any]] = []
        invoices: List[Dict[str, Any]] = []
        #: settlement_id -> the credit rows paying it out. Tracked explicitly
        #: rather than re-derived from the narration, which is exactly the
        #: string the messy-mode anomalies are allowed to corrupt.
        credits_by_settlement: Dict[str, List[Dict[str, Any]]] = {}
        #: Settlements already carrying an injected anomaly. Kept out of the
        #: netted-refund host pool so each labelled anomaly stays independently
        #: measurable instead of compounding with another.
        anomalous_settlements: set = set()

        settlement_counter = 0
        bank_counter = 0

        def new_settlement_id() -> str:
            nonlocal settlement_counter
            sid = self._settlement_id(settlement_counter)
            settlement_counter += 1
            return sid

        def new_bank_id() -> str:
            nonlocal bank_counter
            bid = self._bank_id(bank_counter)
            bank_counter += 1
            return bid

        def emit_settlement(
            settlement_id: str,
            payment_ids: List[str],
            gross: int,
            settlement_date: date,
            refund_adjustment: int = 0,
            netted_refund_payment_ids: Optional[List[str]] = None,
            fee_override: Optional[int] = None,
            gst_override: Optional[int] = None,
            tds_override: Optional[int] = None,
            net_override: Optional[int] = None,
            status: str = "processed",
        ) -> Dict[str, Any]:
            breakdown = compute_fee_breakdown(gross, cfg.accounting)
            fee = fee_override if fee_override is not None else breakdown.gateway_fee_paisa
            gst = gst_override if gst_override is not None else breakdown.gst_on_fee_paisa
            tds = tds_override if tds_override is not None else breakdown.tds_paisa
            net = (
                net_override
                if net_override is not None
                else gross - fee - gst - tds - refund_adjustment
            )
            row = {
                "settlement_id": settlement_id,
                "payment_id": payment_ids[0],
                "payment_ids": payment_ids,
                "gross_amount": gross,
                "gateway_fee": fee,
                "gst_on_fee": gst,
                "tds": tds,
                "refund_adjustment": refund_adjustment,
                "net_amount": net,
                "settlement_date": settlement_date.isoformat(),
                "status": status,
            }
            if netted_refund_payment_ids:
                row["netted_refund_payment_ids"] = netted_refund_payment_ids
            settlements.append(row)
            return row

        def emit_bank_credit(
            settlement_row: Dict[str, Any],
            value_date: date,
            amount: Optional[int] = None,
            truncate_reference: bool = False,
            date_format: str = "%Y-%m-%d",
            template_index: Optional[int] = None,
            unrecognised_format: bool = False,
        ) -> Dict[str, Any]:
            sid = settlement_row["settlement_id"]
            digits = sid.split("-")[1]
            if truncate_reference:
                digits = digits[:-1]
            if unrecognised_format:
                description = UNRECOGNISED_REFERENCE_TEMPLATE.format(num=digits)
                reference = ""
            else:
                idx = (
                    template_index
                    if template_index is not None
                    else self.rng.randrange(len(BANK_DESCRIPTION_TEMPLATES))
                )
                description = BANK_DESCRIPTION_TEMPLATES[idx].format(num=digits)
                reference = f"SET-{digits}" if not truncate_reference else digits
            row = {
                "bank_transaction_id": new_bank_id(),
                "transaction_date": value_date.strftime(date_format),
                "description": description,
                "reference": reference,
                "credit_amount": amount if amount is not None else settlement_row["net_amount"],
                "debit_amount": 0,
                "balance": 0,
                "transaction_type": "CREDIT",
            }
            bank_rows.append(row)
            credits_by_settlement.setdefault(sid, []).append(row)
            return row

        def emit_invoice(
            record: Dict[str, Any],
            invoice_id: Optional[str] = None,
            customer_name: Optional[str] = None,
        ) -> Dict[str, Any]:
            gross = record["gross_amount"]
            # Invoice total is GST-inclusive; back out the taxable base at 18%.
            taxable = round(gross * 100 / 118)
            gst = gross - taxable
            tds = compute_fee_breakdown(gross, cfg.accounting).tds_paisa
            row = {
                "invoice_id": invoice_id or record["invoice_id"],
                "customer_name": customer_name or record["customer_name"],
                "gstin": _gstin(record["customer_index"]),
                "invoice_date": record["order_date"].isoformat(),
                "taxable_amount": taxable,
                "gst_amount": gst,
                "total_amount": gross,
                "tds_amount": tds,
                "status": "issued",
            }
            invoices.append(row)
            return row

        handled: set = set()

        # --- aggregated settlements (consume whole groups first) -----------
        for group in aggregation_groups:
            group_records = [base[i] for i in group]
            # A real consolidated payout batches one settlement cycle, so the
            # orders it covers fall on the same day. Leaving them scattered
            # across the quarter would make every member look like a late
            # payout for reasons that have nothing to do with aggregation.
            batch_date = min(r["order_date"] for r in group_records)
            for r in group_records:
                r["order_date"] = batch_date
            total_gross = sum(r["gross_amount"] for r in group_records)
            # Fees are charged per payment and then summed, exactly as a real
            # aggregated payout works. Summing components avoids rounding drift
            # against a fee computed on the combined gross.
            fee = sum(
                compute_fee_breakdown(r["gross_amount"], cfg.accounting).gateway_fee_paisa
                for r in group_records
            )
            gst = sum(
                compute_fee_breakdown(r["gross_amount"], cfg.accounting).gst_on_fee_paisa
                for r in group_records
            )
            tds = sum(
                compute_fee_breakdown(r["gross_amount"], cfg.accounting).tds_paisa
                for r in group_records
            )
            latest = max(r["order_date"] for r in group_records)
            s_date = latest + timedelta(days=cfg.settlement_lag_days)
            sid = new_settlement_id()
            row = emit_settlement(
                sid,
                [r["payment_id"] for r in group_records],
                total_gross,
                s_date,
                fee_override=fee,
                gst_override=gst,
                tds_override=tds,
            )
            bank = emit_bank_credit(row, s_date)
            for r in group_records:
                handled.add(r["index"])
                emit_invoice(r)
                self._label(
                    AnomalyType.AGGREGATED_SETTLEMENT,
                    f"{len(group_records)} payments aggregated into one payout {sid}",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.AGGREGATED_SETTLEMENT],
                    amount_paisa=r["gross_amount"],
                    order_id=r["order_id"],
                    payment_id=r["payment_id"],
                    settlement_id=sid,
                    bank_transaction_id=bank["bank_transaction_id"],
                )

        # --- per-order emission --------------------------------------------
        refund_donors: List[Dict[str, Any]] = []

        for record in base:
            i = record["index"]
            anomaly = record["anomaly"]
            order_row = {
                "order_id": record["order_id"],
                "customer_id": record["customer_id"],
                "customer_name": record["customer_name"],
                "invoice_id": record["invoice_id"],
                "payment_id": record["payment_id"],
                "gross_amount": record["gross_amount"],
                "refund_amount": 0,
                "currency": "INR",
                "order_date": record["order_date"].isoformat(),
                "status": "paid",
            }
            orders.append(order_row)
            record["order_row"] = order_row

            if i in handled:
                continue  # already emitted as part of an aggregation group

            s_date = record["order_date"] + timedelta(days=cfg.settlement_lag_days)
            gross = record["gross_amount"]
            pid = record["payment_id"]

            if anomaly is AnomalyType.MISSING_SETTLEMENT:
                emit_invoice(record)
                self._label(
                    AnomalyType.MISSING_SETTLEMENT,
                    "Payment captured but the gateway never produced a settlement",
                    ReconciliationStatus.EXCEPTION,
                    [ReasonCode.MISSING_SETTLEMENT],
                    amount_paisa=gross,
                    order_id=record["order_id"],
                    payment_id=pid,
                    invoice_id=record["invoice_id"],
                )
                continue

            if anomaly is AnomalyType.SPLIT_SETTLEMENT:
                # One payment paid out over two settlements. Each leg carries
                # its own gross and its own correctly derived fees. The legs are
                # deliberately unequal (60/40): a real partial payout rarely
                # halves exactly, and two identical legs would be genuinely
                # indistinguishable from a duplicate payout.
                half = (gross * 6 // 10 // 100) * 100
                remainder = gross - half
                sid_a, sid_b = new_settlement_id(), new_settlement_id()
                row_a = emit_settlement(sid_a, [pid], half, s_date)
                row_b = emit_settlement(
                    sid_b, [pid], remainder, s_date + timedelta(days=1)
                )
                bank_a = emit_bank_credit(row_a, s_date)
                bank_b = emit_bank_credit(row_b, s_date + timedelta(days=1))
                emit_invoice(record)
                self._label(
                    AnomalyType.SPLIT_SETTLEMENT,
                    f"Single payment split across settlements {sid_a} and {sid_b}",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.SPLIT_SETTLEMENT],
                    amount_paisa=gross,
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid_a,
                    bank_transaction_id=bank_a["bank_transaction_id"],
                )
                continue

            if anomaly is AnomalyType.NETTED_REFUND:
                # This order is refunded later; the claw-back is netted into a
                # LATER settlement belonging to a different payment. The engine
                # must attribute it rather than reporting a phantom shortfall.
                sid = new_settlement_id()
                row = emit_settlement(sid, [pid], gross, s_date)
                emit_bank_credit(row, s_date)
                emit_invoice(record)
                order_row["refund_amount"] = gross
                order_row["status"] = "refunded"
                refund_donors.append(
                    {"payment_id": pid, "amount": gross, "order_id": record["order_id"]}
                )
                continue

            if anomaly is AnomalyType.PARTIAL_REFUND:
                refund = (gross // 4 // 100) * 100
                order_row["refund_amount"] = refund
                order_row["status"] = "partially_refunded"
                sid = new_settlement_id()
                row = emit_settlement(
                    sid,
                    [pid],
                    gross,
                    s_date,
                    refund_adjustment=refund,
                    netted_refund_payment_ids=[pid],
                )
                bank = emit_bank_credit(row, s_date)
                emit_invoice(record)
                self._label(
                    AnomalyType.PARTIAL_REFUND,
                    "Partial refund netted inside the same settlement",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.PARTIAL_REFUND],
                    amount_paisa=refund,
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=bank["bank_transaction_id"],
                )
                continue

            # ---- everything below emits exactly one settlement ------------
            sid = new_settlement_id()
            fee_override = gst_override = tds_override = net_override = None
            refund_adjustment = 0
            settle_date = s_date
            breakdown = compute_fee_breakdown(gross, cfg.accounting)

            if anomaly is AnomalyType.ROUNDING_ERROR:
                net_override = breakdown.net_amount_paisa - 1
            elif anomaly is AnomalyType.TDS_DISCREPANCY:
                tds_override = breakdown.tds_paisa + 15_000
            elif anomaly is AnomalyType.GST_DISCREPANCY:
                gst_override = breakdown.gst_on_fee_paisa + 2_500
            elif anomaly is AnomalyType.DELAYED_SETTLEMENT:
                settle_date = record["order_date"] + timedelta(days=12)

            row = emit_settlement(
                sid,
                [pid],
                gross,
                settle_date,
                refund_adjustment=refund_adjustment,
                fee_override=fee_override,
                gst_override=gst_override,
                tds_override=tds_override,
                net_override=net_override,
            )
            if anomaly is not None:
                anomalous_settlements.add(sid)

            invoice_id = None
            customer_name = None
            if anomaly is AnomalyType.INVOICE_TYPO:
                # Classic transcription error: a zero keyed as the letter O,
                # inside the serial rather than in the 'INV' prefix.
                prefix, _, serial = record["invoice_id"].partition("-")
                invoice_id = f"{prefix}-{serial.replace('0', 'O', 1)}"
            if anomaly is AnomalyType.CUSTOMER_NAME_ALIAS:
                customer_name = f"{record['customer_name']} Pvt Ltd"
            emit_invoice(record, invoice_id=invoice_id, customer_name=customer_name)

            # ---- bank side -------------------------------------------------
            if anomaly is AnomalyType.MISSING_BANK_TRANSACTION:
                self._label(
                    AnomalyType.MISSING_BANK_TRANSACTION,
                    "Settlement issued but no matching credit on the bank statement",
                    ReconciliationStatus.PARTIAL_MATCH,
                    [ReasonCode.MISSING_BANK_TRANSACTION],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                )
                continue

            date_format = "%Y-%m-%d"
            truncate = False
            if anomaly is AnomalyType.DATE_FORMAT_DIFFERENCE:
                date_format = BANK_DATE_FORMATS[1 + (i % 2)]
            if anomaly is AnomalyType.TRUNCATED_BANK_REFERENCE:
                truncate = True

            bank = emit_bank_credit(
                row,
                settle_date,
                truncate_reference=truncate,
                date_format=date_format,
                unrecognised_format=(
                    anomaly is AnomalyType.UNRECOGNISED_REFERENCE_FORMAT
                ),
            )

            if anomaly is AnomalyType.DUPLICATE_SETTLEMENT:
                dup_sid = new_settlement_id()
                emit_settlement(dup_sid, [pid], gross, settle_date)
                self._label(
                    AnomalyType.DUPLICATE_SETTLEMENT,
                    f"Payment settled twice: {sid} and {dup_sid}",
                    ReconciliationStatus.DUPLICATE,
                    [ReasonCode.DUPLICATE_SETTLEMENT],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=dup_sid,
                )
            elif anomaly is AnomalyType.DUPLICATE_BANK_TRANSACTION:
                dup = emit_bank_credit(row, settle_date)
                self._label(
                    AnomalyType.DUPLICATE_BANK_TRANSACTION,
                    "The same payout credited to the bank account twice",
                    ReconciliationStatus.DUPLICATE,
                    [ReasonCode.DUPLICATE_BANK_TRANSACTION],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=dup["bank_transaction_id"],
                )
            elif anomaly is AnomalyType.CHARGEBACK:
                order_row["status"] = "chargeback"
                debit = {
                    "bank_transaction_id": new_bank_id(),
                    "transaction_date": (settle_date + timedelta(days=4)).isoformat(),
                    "description": f"CHARGEBACK DEBIT RZP SET-{sid.split('-')[1]}",
                    "reference": sid,
                    "credit_amount": 0,
                    "debit_amount": row["net_amount"],
                    "balance": 0,
                    "transaction_type": "DEBIT",
                }
                bank_rows.append(debit)
                self._label(
                    AnomalyType.CHARGEBACK,
                    "Settled payout later reversed by a chargeback debit",
                    ReconciliationStatus.REVIEW_REQUIRED,
                    [ReasonCode.CHARGEBACK],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=debit["bank_transaction_id"],
                )
            elif anomaly is AnomalyType.ROUNDING_ERROR:
                self._label(
                    AnomalyType.ROUNDING_ERROR,
                    "Settlement net is 1 paisa below the reconstructed value",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.ROUNDING_TOLERANCE_APPLIED],
                    amount_paisa=1,
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=bank["bank_transaction_id"],
                )
            elif anomaly is AnomalyType.TDS_DISCREPANCY:
                self._label(
                    AnomalyType.TDS_DISCREPANCY,
                    "TDS withheld exceeds the configured rate",
                    ReconciliationStatus.REVIEW_REQUIRED,
                    [ReasonCode.TDS_MISMATCH],
                    amount_paisa=15_000,
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                )
            elif anomaly is AnomalyType.GST_DISCREPANCY:
                self._label(
                    AnomalyType.GST_DISCREPANCY,
                    "GST on the gateway fee does not match the statutory rate",
                    ReconciliationStatus.REVIEW_REQUIRED,
                    [ReasonCode.GST_MISMATCH],
                    amount_paisa=2_500,
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                )
            elif anomaly is AnomalyType.DELAYED_SETTLEMENT:
                self._label(
                    AnomalyType.DELAYED_SETTLEMENT,
                    "Settlement landed 12 days after the order, well outside T+2",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.DELAYED_SETTLEMENT],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=bank["bank_transaction_id"],
                )
            elif anomaly is AnomalyType.TRUNCATED_BANK_REFERENCE:
                self._label(
                    AnomalyType.TRUNCATED_BANK_REFERENCE,
                    "Bank narration truncated the settlement reference",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.TRUNCATED_BANK_REFERENCE],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=bank["bank_transaction_id"],
                )
            elif anomaly is AnomalyType.DATE_FORMAT_DIFFERENCE:
                self._label(
                    AnomalyType.DATE_FORMAT_DIFFERENCE,
                    "Bank statement renders the value date in a different format",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.DATE_FORMAT_NORMALIZED],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=bank["bank_transaction_id"],
                )
            elif anomaly is AnomalyType.UNRECOGNISED_REFERENCE_FORMAT:
                self._label(
                    AnomalyType.UNRECOGNISED_REFERENCE_FORMAT,
                    "Acquirer narration format the built-in extractor cannot parse",
                    ReconciliationStatus.PARTIAL_MATCH,
                    [ReasonCode.MISSING_BANK_TRANSACTION],
                    amount_paisa=row["net_amount"],
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    bank_transaction_id=bank["bank_transaction_id"],
                )
            elif anomaly is AnomalyType.INVOICE_TYPO:
                self._label(
                    AnomalyType.INVOICE_TYPO,
                    "Invoice register carries an O-for-zero typo in the invoice number",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.INVOICE_TYPO_RESOLVED],
                    amount_paisa=gross,
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    invoice_id=record["invoice_id"],
                )
            elif anomaly is AnomalyType.CUSTOMER_NAME_ALIAS:
                self._label(
                    AnomalyType.CUSTOMER_NAME_ALIAS,
                    "Invoice uses the full legal entity name, the order uses the alias",
                    ReconciliationStatus.MATCHED,
                    [ReasonCode.COUNTERPARTY_ALIAS_RESOLVED],
                    amount_paisa=gross,
                    order_id=record["order_id"],
                    payment_id=pid,
                    settlement_id=sid,
                    invoice_id=record["invoice_id"],
                )

        # --- attach netted refunds to later settlements --------------------
        self._attach_netted_refunds(
            refund_donors, settlements, credits_by_settlement, anomalous_settlements
        )

        # --- unknown bank credits ------------------------------------------
        for n in range(mix.get(AnomalyType.UNKNOWN_BANK_CREDIT, 0)):
            amount = self.rng.randint(5_000, 150_000) * 100
            when = cfg.start_date + timedelta(days=self.rng.randint(5, cfg.day_span))
            row = {
                "bank_transaction_id": new_bank_id(),
                "transaction_date": when.isoformat(),
                "description": UNKNOWN_CREDIT_DESCRIPTIONS[
                    n % len(UNKNOWN_CREDIT_DESCRIPTIONS)
                ],
                "reference": "",
                "credit_amount": amount,
                "debit_amount": 0,
                "balance": 0,
                "transaction_type": "CREDIT",
            }
            bank_rows.append(row)
            self._label(
                AnomalyType.UNKNOWN_BANK_CREDIT,
                "Credit on the bank statement with no order, settlement or invoice",
                ReconciliationStatus.EXCEPTION,
                [ReasonCode.UNKNOWN_BANK_CREDIT],
                amount_paisa=amount,
                detected_on="bank",
                bank_transaction_id=row["bank_transaction_id"],
            )

        self._apply_running_balance(bank_rows)

        return GeneratedDataset(
            orders=orders,
            settlements=settlements,
            bank_transactions=bank_rows,
            invoices=invoices,
            ground_truth=self.ground_truth,
            manifest={
                "dataset_id": cfg.dataset_id,
                "mode": cfg.mode,
                "seed": cfg.seed,
                "units": "paise",
                "currency": "INR",
                "order_count": len(orders),
                "settlement_count": len(settlements),
                "bank_transaction_count": len(bank_rows),
                "invoice_count": len(invoices),
                "total_source_records": (
                    len(orders) + len(settlements) + len(bank_rows) + len(invoices)
                ),
                "anomaly_count": len(self.ground_truth),
                "accounting": cfg.accounting.describe(),
                "generated_start_date": cfg.start_date.isoformat(),
                "day_span": cfg.day_span,
            },
        )

    def _attach_netted_refunds(
        self,
        donors: List[Dict[str, Any]],
        settlements: List[Dict[str, Any]],
        credits_by_settlement: Dict[str, List[Dict[str, Any]]],
        anomalous_settlements: set,
    ) -> None:
        """Net each donor refund into an unrelated, later settlement.

        This is the case that separates a real reconciliation engine from a
        join: the refunded order already settled cleanly, and the claw-back
        surfaces inside somebody else's payout.
        """
        eligible = [
            s
            for s in settlements
            if s["refund_adjustment"] == 0
            and len(s["payment_ids"]) == 1
            and s["net_amount"] > 0
            and s["settlement_id"] not in anomalous_settlements
            and credits_by_settlement.get(s["settlement_id"])
        ]

        for donor in donors:
            host = None
            for candidate in eligible:
                if candidate["payment_ids"][0] == donor["payment_id"]:
                    continue
                if candidate["net_amount"] > donor["amount"]:
                    host = candidate
                    break
            if host is None:
                continue
            eligible.remove(host)
            host["refund_adjustment"] = donor["amount"]
            host["net_amount"] -= donor["amount"]
            host["netted_refund_payment_ids"] = [donor["payment_id"]]
            for credit in credits_by_settlement.get(host["settlement_id"], []):
                credit["credit_amount"] = host["net_amount"]
            self._label(
                AnomalyType.NETTED_REFUND,
                (
                    f"Refund for {donor['order_id']} netted inside unrelated payout "
                    f"{host['settlement_id']}"
                ),
                ReconciliationStatus.MATCHED,
                [ReasonCode.REFUND_NETTED],
                amount_paisa=donor["amount"],
                detected_on="settlement",
                order_id=donor["order_id"],
                payment_id=donor["payment_id"],
                settlement_id=host["settlement_id"],
            )

    @staticmethod
    def _apply_running_balance(bank_rows: List[Dict[str, Any]]) -> None:
        """Give the statement a coherent running balance in date order."""
        from app.services.normalization.dates import parse_date

        ordered = sorted(
            bank_rows,
            key=lambda r: (parse_date(r["transaction_date"]) or date.min, r["bank_transaction_id"]),
        )
        balance = 5_000_000_00  # opening balance of Rs.50,00,000.00
        for row in ordered:
            balance += row["credit_amount"] - row["debit_amount"]
            row["balance"] = balance
