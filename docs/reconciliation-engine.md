# Reconciliation engine

Nav: [Architecture](architecture.md) · [Data model](data-model.md) · **Reconciliation engine** · [Auditability](auditability.md) · [Demo data](demo-data.md) · [Arbitration](arbitration.md) · [Self-healing rules](self-healing-rules.md) · [Forecasting & copilot](forecasting-and-copilot.md) · [Future AI layer](future-ai-layer.md)

---

## Accounting formulas

All rates are configuration (`AccountingConfig`), never constants at a call site.

```
RULE-FEE-001   gateway_fee = gross        × gateway_fee_bps / 10000     (default 200 bps = 2.00%)
RULE-TAX-001   gst         = gateway_fee  × gst_on_fee_bps  / 10000     (default 1800 bps = 18.00%)
RULE-TAX-002   tds         = gross        × tds_bps         / 10000     (default 10 bps = 0.10%, s.194-O)
RULE-ADJ-001   netted_refunds = Σ refund_adjustment attributed to this payout
RULE-NET-001   net = gross − gateway_fee − gst − tds − netted_refunds ± adjustments
RULE-NET-002   self-consistency: reported_net == gross − reported components
RULE-TOL-001   |variance| ≤ rounding_tolerance_paisa   (default 1 paisa = ₹0.01)
```

Each component is rounded `ROUND_HALF_UP` to the paisa **once**, at the point it
is computed. Rounding is never compounded.

GST is levied on the **gateway fee**, not on the gross. On ₹1,000.00 that is
₹3.60, not ₹180.00 — a distinction `tests/test_accounting.py` asserts explicitly.

### Worked example

Gross ₹1,000.00 = `100000` paise, TDS configured at 0.02%:

```
100000 - 2000 - 360 - 20 = 97620
```

At the default 0.10% TDS the same order yields `100000 - 2000 - 360 - 100 = 97540`.
Both are reproducible from configuration alone.

### Why fees are summed per component, never charged on a total

For an aggregated or split payout, the expected fee is the **sum of the fees on
each component**, not the fee on the combined gross. Rounding does not
distribute over a sum:

```
3 × 2% of ₹125.25  = 3 × 251 paise = 753 paise
    2% of ₹375.75  =                 752 paise
```

Using the second would manufacture a 1-paisa variance on every aggregated
payout — a phantom exception on real, correct data.

## The five matching layers

Layers run in order, strongest evidence first, and stop at the first that
resolves.

### Layer 1 — Exact identifiers

`payment_id`, `settlement_id`, `invoice_id`, `order_id`, bank reference.
Confidence **1.00**. The bank told us the settlement id; nothing probabilistic
remains.

Bank narrations are parsed by **structured key extraction**, not fuzzy string
similarity: digit runs of length ≥ 4 and alphanumeric tokens are pulled out and
looked up in an exact index. A match is therefore provable or absent.

Invoice links tolerate transcription errors through a fixed character-confusion
fold (`O→0`, `I→1`, `L→1`, `S→5`, `B→8`) after stripping the document prefix.
The folded key must resolve to exactly one invoice. `INV-1O001` and `INV-10001`
both fold to `10001`; `INV-10002` does not.

Counterparty aliases fold legal-form suffixes (`PVT`, `LTD`, `LLP`, …) and
punctuation, so `Acme Retail Pvt Ltd` and `ACME  RETAIL.` compare equal without
any similarity scoring.

### Layer 2 — Financial equation (an accounting invariant)

**This is not a fuzzy match.** When

```
gross − gateway_fee − gst − tds − netted_refunds = net
```

closes to the paisa, the settlement is *proved* to correspond to the payment.
That proof is what earns confidence 1.00.

When it does not close, the gap is attributed rather than shrugged at. Two
independent checks run:

1. **Component check** — does each reported component equal what the configured
   rate produces? A gap localises the fault to the fee, the GST or the TDS.
2. **Self-consistency check** — do the settlement's own reported numbers add up
   to its own reported net? A gap here is an arithmetic fault inside the source.

A wrong fee whose GST is correct *for that wrong fee* reports one fault, not
two: GST is verified against the reported fee so an error cannot cascade.

### Layer 3 — Exact amount + date window

Used only when no reference survives. Requires **all three**: exact payout
amount, value date within `settlement_date_tolerance_days` (default ±3), and a
narration identifying the gateway as counterparty. Confidence **0.90**.

### Layer 4 — Aggregation (N:M)

Four shapes, decided from covered-payment sets and amounts:

| Shape | Test | Match type |
|---|---|---|
| SIMPLE | one settlement, one covered payment | `EXACT_PAYMENT_ID` |
| AGGREGATED | one settlement, N covered payments | `AGGREGATED_SETTLEMENT` |
| SPLIT | N settlements whose grosses **sum to** the order gross | `SPLIT_SETTLEMENT` |
| DUPLICATE | N settlements each claiming the **whole** order gross | `DUPLICATE` |

The split/duplicate discriminator is the gross, and it matters. Two settlements
of equal amount for one payment are ambiguous on their face — they could be a
double payout or an even two-way split. A settlement claiming the *entire* order
gross is paying the payment in full, so a second one claiming the same is a
duplicate; settlements whose grosses *sum to* the order gross are legs of a
split, however similar their amounts look.

### Layer 5 — Netting

**The rule this layer exists to enforce: when a refund or chargeback is netted
inside a settlement, the original order is NOT missing.** Reporting it as
missing would be the most damaging false positive this system could produce,
because it sends an operator hunting for money that was correctly clawed back.

Instead an `AdjustmentRecord` is produced naming the refunded payment, the
settlement that absorbed it, the amount and the evidence for all three.

Attribution is taken from the source, never inferred: `netted_refund_payment_ids`
when the settlement itemises it (real gateway reports do), otherwise the
payments the settlement covers. A refund that cannot be attributed is surfaced
as unattributed rather than quietly spread across whatever is nearby.

A chargeback debit referencing a known settlement reduces the **actual** amount,
because the cash arrived and then left again. Leaving the actual at the gross
payout would report a reversed transaction as fully settled with zero exposure.

## Confidence model

Confidence is not a probability and is never sampled, learned or guessed. Each
value is a fixed constant bound to a named rule, stored alongside the number.

| Value | Method | Basis |
|---:|---|---|
| 1.00 | `EXACT_IDENTIFIER` | an exact identifier matched |
| 1.00 | `ACCOUNTING_INVARIANT` | the equation closed to the paisa |
| 1.00 | `REFERENCE_EXTRACTION_EXACT` | narration carried the settlement id verbatim |
| 0.99 | `ACCOUNTING_INVARIANT_WITHIN_ROUNDING_TOLERANCE` | closed inside the ₹0.01 tolerance |
| 0.95 | `REFERENCE_PREFIX_UNIQUE` | truncated reference resolved to exactly one settlement, amount agreeing |
| 0.90 | `AMOUNT_DATE_COUNTERPARTY_COMPOSITE` | exact amount + date window + gateway narration |
| 0.00 | `NOT_ESTABLISHED` | no link proved |

A composite result takes the **minimum** of its constituent confidences — not
the product, not an average. A chain of evidence is exactly as strong as its
weakest verified link, and multiplying independent-looking factors would invent
precision the rules do not have. The method recorded on the result names the
link that set the ceiling.

## Status classification

A result is only `MATCHED` when the money is fully explained.

| Status | Meaning |
|---|---|
| `MATCHED` | invariant proved **and** bank credit located |
| `PARTIAL_MATCH` | settlement proved, cash not located |
| `REVIEW_REQUIRED` | a quantified discrepancy attributed to a specific component |
| `DUPLICATE` | the same payout appears more than once; exposure is the excess |
| `EXCEPTION` | no counterpart exists at all |
| `UNRESOLVED` | end of the deterministic layers with no explanation — the only status handed to an arbitrator |

Reason codes split into two families, and rendering them identically would
mislead:

- **Informational** (`ROUNDING_TOLERANCE_APPLIED`, `AGGREGATED_SETTLEMENT`,
  `REFUND_NETTED`, `TRUNCATED_BANK_REFERENCE`, `DATE_FORMAT_NORMALIZED`,
  `INVOICE_TYPO_RESOLVED`, …) explain **how** a match was proved and never
  block it.
- **Blocking** (`NET_AMOUNT_VARIANCE`, `TDS_MISMATCH`, `GST_MISMATCH`,
  `CHARGEBACK`, `INVOICE_LINK_BROKEN`, …) force human review.

**Structural guarantee:** there is no path through `classify()` that produces
`MATCHED` without a proved invariant, and no path that produces any residual
status without a reason code.
`tests/test_ground_truth.py::test_every_residual_is_explained` asserts this
across the whole seed dataset.

## Exception philosophy

An exception states what could **not** be established. It carries no suggested
fix, no auto-clear, and no confidence score invented to make an unknown look
handled:

```
REC-00502   ₹1,49,724.00   Unknown bank credit
  - No matching order
  - No matching settlement
  - No matching invoice
  Status: HUMAN REVIEW REQUIRED
```

An unidentified credit is never speculatively attached to a plausible nearby
order, even when one exists with a similar date.
`test_unknown_credit_is_never_attached_to_a_plausible_nearby_order` proves this.

## Metrics

```
match_rate     = deterministic_matches / records_processed
exception_rate = (exceptions + unresolved) / records_processed
throughput     = records_processed / processing_time_seconds
residuals      = review_required + exceptions + duplicates + unresolved
```

`records_processed` counts reconciliation results: one per order **plus one per
unidentified bank credit**. That denominator is deliberate — an unidentified
credit is a record the system had to decide about, and excluding it would
flatter the match rate.

---

**Back:** [🗃️ Data model](data-model.md) · **Next:** [📖 Auditability](auditability.md) · **Up:** [📘 README](../README.md)
