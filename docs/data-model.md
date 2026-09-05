# Data model

Nav: [Architecture](architecture.md) · **Data model** · [Reconciliation engine](reconciliation-engine.md) · [Auditability](auditability.md) · [Demo data](demo-data.md) · [Arbitration](arbitration.md) · [Self-healing rules](self-healing-rules.md) · [Forecasting & copilot](forecasting-and-copilot.md) · [Future AI layer](future-ai-layer.md)

---

## Money is always an integer number of paise

This is the single most important rule in the codebase.

- `₹1,000.25` is stored, computed and transmitted as `100025`.
- Rates are basis points, so a rate is itself exact: 2% is `200` bps, not `0.02`.
- `rupees_to_paisa()` **raises `TypeError` on a float input**. Passing `1000.25`
  is a programming error, because that value is not exactly representable in
  binary floating point.
- Database columns are `BigInteger`. There is no `Float`, `Numeric` or `Decimal`
  money column anywhere in the schema.
- The frontend formats integers for display and never divides them into floats
  before grouping (`frontend/src/lib/format.ts`).

`Decimal` is used in exactly one place — inside `apply_rate_bps()` — to perform
a single `ROUND_HALF_UP` quantisation to the paisa. The result is an `int`.

## On-disk source format

Files use the published source field names with **integer paise values**. The
manifest states this explicitly (`"units": "paise"`). The ingestion layer maps
each amount onto a `_paisa`-suffixed attribute, which is where the unit becomes
enforced by the type system rather than by convention.

### Source A — Orders (`orders.json`)

| Field | Type | Notes |
|---|---|---|
| `order_id` | str | `ORD-10001` |
| `customer_id`, `customer_name` | str | name may be an alias of the invoice name |
| `invoice_id` | str | links to Source D |
| `payment_id` | str | links to Source B |
| `gross_amount` | int paise | |
| `refund_amount` | int paise | refunded later; netted where the settlement says |
| `currency` | str | `INR` |
| `order_date` | str | ISO |
| `status` | str | `paid`, `partially_refunded`, `refunded`, `chargeback` |

### Source B — Razorpay settlements (`settlements.json`)

| Field | Type | Notes |
|---|---|---|
| `settlement_id` | str | `SET-10291` |
| `payment_id` | str | primary leg |
| `payment_ids` | list[str] | **all** payments covered; length > 1 means aggregation |
| `gross_amount` | int paise | |
| `gateway_fee`, `gst_on_fee`, `tds` | int paise | as reported by the gateway |
| `refund_adjustment` | int paise | refunds netted inside this payout |
| `netted_refund_payment_ids` | list[str] | which payments the refund belongs to |
| `net_amount` | int paise | as reported |
| `settlement_date`, `status` | str | |

`payment_ids` is what makes N:M real rather than implied. `netted_refund_payment_ids`
is what lets a refund be attributed to a payment other than the one being paid
out, which is the case that separates a reconciliation engine from a join.

### Source C — Bank statement (`bank_statement.json`)

| Field | Type | Notes |
|---|---|---|
| `bank_transaction_id` | str | |
| `transaction_date` | str | **format varies deliberately**: ISO, `DD/MM/YYYY`, `DD-Mon-YYYY` |
| `description` | str | messy narration, see below |
| `reference` | str | may be truncated or empty |
| `credit_amount`, `debit_amount`, `balance` | int paise | balance is a running total |
| `transaction_type` | str | `CREDIT` / `DEBIT` |

Narrations for one settlement legitimately arrive as any of:

```
RAZORPAY SETTLEMENT SET-10291      RZP SET-10291           NEFT-RZPSET10291-HDFC
RAZORPAY SETTLE 10291              rzp set-10291           RZP SET-1029   (truncated)
Settlement payout / 10291          RZP  SETTLEMENT   SET-10291  (whitespace)
```

### Source D — Invoice / tax register (`invoices.json`)

| Field | Type | Notes |
|---|---|---|
| `invoice_id` | str | may carry an O-for-zero transcription typo |
| `customer_name` | str | may be the full legal entity name |
| `gstin` | str | structurally plausible, not real |
| `taxable_amount`, `gst_amount`, `total_amount`, `tds_amount` | int paise | `taxable + gst = total` |
| `invoice_date`, `status` | str | |

### Ground truth (`ground_truth.json`)

Never served to the operator UI. Exists so precision and recall are measurable.

| Field | Notes |
|---|---|
| `anomaly_id`, `anomaly_type` | one of 18 classes |
| `expected_status`, `expected_reason_codes` | what a correct engine must conclude |
| `detected_on` | `order` \| `settlement` \| `bank` — which record carries the detection |
| `order_id`, `payment_id`, `settlement_id`, `bank_transaction_id`, `invoice_id` | |
| `amount_paisa`, `description` | |

`detected_on` exists because the detection does not always land on the order.
A refund netted into an unrelated payout is *labelled* against the refunded
order but *detected* on the record owning the host settlement. Without this
field, per-record recall could only be measured in aggregate.

## Canonical model

`CanonicalTransaction` (`app/domain/canonical.py`) is the normalized view.
Normalization **never overwrites a source value**. Every transformation that
actually changed something leaves a `NormalizationStep`:

```python
NormalizationStep(
    field_name="description",
    original_value="RZP  SETTLEMENT   SET-10005",
    normalized_value="RZP SETTLEMENT SET 10005",
    rule="RULE-NORM-020",
)
```

Identity transformations are dropped from the trace, because a trace full of
no-ops buries the one transformation an auditor cares about.

## Reconciliation result

`ReconciliationResult` is the engine's output contract. Key fields:

| Field | Meaning |
|---|---|
| `status` | MATCHED · PARTIAL_MATCH · REVIEW_REQUIRED · DUPLICATE · EXCEPTION · UNRESOLVED |
| `match_type` | how the link was established |
| `confidence` + `confidence_method` | a number and the named rule that produced it |
| `expected_amount_paisa` | what the accounting equation says the payout should be |
| `actual_amount_paisa` | what was actually reported/received |
| `variance_paisa` | `actual - expected` |
| `calculation` | ordered `CalculationLine`s with literal arithmetic |
| `evidence` | `Evidence` items pointing at real records |
| `adjustments` | `AdjustmentRecord`s from the netting layer |
| `reason_codes` | at least one on every non-matched result |

### Variance vs exposure

These are different numbers and conflating them hides money.

- **variance** = `actual − expected`. A `PARTIAL_MATCH` has variance **zero**:
  the settlement arithmetic is provably correct.
- **exposure** (`repo.exposure_paisa`) = money at stake. For a `PARTIAL_MATCH`
  it is the full payout awaited; for a duplicate it is the doubled amount; for
  an exception it is the unexplained value.

The exception desk ranks by exposure. Ranking by variance would push
"settlement issued, cash never arrived" to the bottom of the list.

## Persistence

| Table | Purpose |
|---|---|
| `reconciliation_runs` | one row per run, every metric measured |
| `reconciliation_records` | one row per decision, with its proof in JSON |
| `audit_events` | append-only; nothing updates or deletes here |
| `rules` | rule catalogue |
| `datasets` | dataset manifests |

Evidence, calculations and reason codes are stored as JSON **snapshots** rather
than normalised away. They record what the engine proved *at run time*.
Re-deriving them later from a changed engine would silently rewrite history,
which is the opposite of an audit trail.

---

**Back:** [🏗️ Architecture](architecture.md) · **Next:** [⚙️ Reconciliation engine](reconciliation-engine.md) · **Up:** [📘 README](../README.md)
