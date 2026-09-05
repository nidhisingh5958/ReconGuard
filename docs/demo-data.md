# Demo data

Nav: [Architecture](architecture.md) · [Data model](data-model.md) · [Reconciliation engine](reconciliation-engine.md) · [Auditability](auditability.md) · **Demo data** · [Arbitration](arbitration.md) · [Self-healing rules](self-healing-rules.md) · [Forecasting & copilot](forecasting-and-copilot.md) · [Future AI layer](future-ai-layer.md)

---

## Generating

```bash
cd backend
uv run python -m scripts.generate_dataset --messy               # 500 orders, seed 42 -> data/seed-500/
uv run python -m scripts.generate_dataset --clean --count 500
uv run python -m scripts.generate_dataset --messy --count 10000 --seed 7
```

Or via the API:

```bash
curl -X POST localhost:8000/api/data/generate \
  -H 'Content-Type: application/json' \
  -d '{"order_count":500,"seed":42,"mode":"messy"}'
```

## Two modes

**`--clean`** is a perfectly reconciling world: every order has exactly one
settlement, one bank credit and one invoice. A correct engine **must** score a
100% match rate here. Anything less is an engine bug, not a data problem, which
makes clean mode the strongest regression test in the repository
(`test_clean_mode_reconciles_perfectly`).

**`--messy`** is clean mode plus **nineteen** classes of individually labelled
anomalies.

## Determinism

The same seed produces byte-identical output. Reproducibility is what makes a
match-rate change between two runs attributable to an engine change rather than
to data drift.

## The seed dataset (500 orders, seed 42)

| Source | Rows |
|---|---:|
| Orders | 500 |
| Settlements | 494 |
| Bank transactions | 495 |
| Invoices | 500 |
| **Total source records** | **1,989** |
| Reconciliation records produced | 510 (before self-healing) / 504 (after) |
| Labelled anomalies | 96 |

Reconciliation records exceed orders because each unidentified bank credit
becomes its own record.

## Anomaly mix

Scaled proportionally for other dataset sizes.

| # | Anomaly | Count | Expected status | Reason code |
|--:|---|--:|---|---|
| 1 | `MISSING_SETTLEMENT` | 6 | EXCEPTION | `MISSING_SETTLEMENT` |
| 2 | `DUPLICATE_SETTLEMENT` | 4 | DUPLICATE | `DUPLICATE_SETTLEMENT` |
| 3 | `MISSING_BANK_TRANSACTION` | 6 | PARTIAL_MATCH | `MISSING_BANK_TRANSACTION` |
| 4 | `DUPLICATE_BANK_TRANSACTION` | 4 | DUPLICATE | `DUPLICATE_BANK_TRANSACTION` |
| 5 | `INVOICE_TYPO` | 4 | MATCHED | `INVOICE_TYPO_RESOLVED` |
| 6 | `CUSTOMER_NAME_ALIAS` | 5 | MATCHED | `COUNTERPARTY_ALIAS_RESOLVED` |
| 7 | `DATE_FORMAT_DIFFERENCE` | 5 | MATCHED | `DATE_FORMAT_NORMALIZED` |
| 8 | `ROUNDING_ERROR` (₹0.01) | 5 | MATCHED | `ROUNDING_TOLERANCE_APPLIED` |
| 9 | `PARTIAL_REFUND` | 5 | MATCHED | `PARTIAL_REFUND` |
| 10 | `NETTED_REFUND` | 5 | MATCHED | `REFUND_NETTED` |
| 11 | `AGGREGATED_SETTLEMENT` | 12 (4 groups × 3) | MATCHED | `AGGREGATED_SETTLEMENT` |
| 12 | `SPLIT_SETTLEMENT` | 4 | MATCHED | `SPLIT_SETTLEMENT` |
| 13 | `DELAYED_SETTLEMENT` | 5 | MATCHED | `DELAYED_SETTLEMENT` |
| 14 | `CHARGEBACK` | 3 | REVIEW_REQUIRED | `CHARGEBACK` |
| 15 | `TDS_DISCREPANCY` | 4 | REVIEW_REQUIRED | `TDS_MISMATCH` |
| 16 | `GST_DISCREPANCY` | 4 | REVIEW_REQUIRED | `GST_MISMATCH` |
| 17 | `TRUNCATED_BANK_REFERENCE` | 5 | MATCHED | `TRUNCATED_BANK_REFERENCE` |
| 18 | `UNKNOWN_BANK_CREDIT` | 4 | EXCEPTION | `UNKNOWN_BANK_CREDIT` |
| 19 | `UNRECOGNISED_REFERENCE_FORMAT` | 6 | PARTIAL_MATCH **+** EXCEPTION | `MISSING_BANK_TRANSACTION` **+** `UNKNOWN_BANK_CREDIT` |

Nine of the nineteen classes are things the engine is expected to **resolve**,
not merely flag. That split is deliberate: a demo where every anomaly becomes an
exception would show a matching engine that gives up, not one that works.

Class 19 is the only one that maps to **two** reason codes, because one
unparseable narration produces two residuals: the payout is left without its
cash, and the credit is left without its payout. It is also the only class the
base engine is *expected to fail on* — it exists so the
[self-healing loop](self-healing-rules.md) has a real gap to close.

### Notes on the harder cases

- **Netted refund.** Order A settles cleanly and is refunded later; the
  claw-back is netted inside order **B**'s unrelated payout. Both must
  reconcile. This is the case that separates a reconciliation engine from a join.
- **Split settlement.** Legs are deliberately unequal (60/40). Two identical legs
  would be genuinely indistinguishable from a duplicate payout on their face.
- **Aggregated settlement.** Group members share an order date, because a real
  consolidated payout batches one settlement cycle. Scattering them across the
  quarter would make every member look like a late payout for reasons unrelated
  to aggregation.
- **Truncated reference.** The narration loses the last digit. Resolution
  requires the 4-digit prefix to identify exactly one settlement *once the payout
  amount is also required to agree*. If it stays ambiguous, the engine refuses
  rather than guessing.
- **Anomaly isolation.** A settlement already carrying an injected anomaly is
  excluded from the netted-refund host pool, so each labelled anomaly stays
  independently measurable instead of compounding with another.
- **Unrecognised reference format.** `ACH CR//PGWX/99{key}/MERCHANT ACCT`
  defeats both built-in paths on purpose: the digit run yields `9910291` rather
  than the key `10291`, and `PGWX` carries no gateway marker so the amount+date
  fallback declines it too. See [self-healing-rules.md](self-healing-rules.md).

## Measured results

```bash
cd backend && uv run python -m scripts.benchmark
```

### Ground truth: 100% precision and recall

Measured per **reason code** rather than per anomaly class, because one class can
legitimately raise two codes on two different records.

```
reason code                      expected  detected  precision   recall
AGGREGATED_SETTLEMENT                  12        12    100.0%   100.0%
CHARGEBACK                              3         3    100.0%   100.0%
COUNTERPARTY_ALIAS_RESOLVED             5         5    100.0%   100.0%
DATE_FORMAT_NORMALIZED                  5         5    100.0%   100.0%
DELAYED_SETTLEMENT                      5         5    100.0%   100.0%
DUPLICATE_BANK_TRANSACTION              4         4    100.0%   100.0%
DUPLICATE_SETTLEMENT                    4         4    100.0%   100.0%
GST_MISMATCH                            4         4    100.0%   100.0%
INVOICE_TYPO_RESOLVED                   4         4    100.0%   100.0%
MISSING_BANK_TRANSACTION               12        12    100.0%   100.0%
MISSING_SETTLEMENT                      6         6    100.0%   100.0%
PARTIAL_REFUND                          5         5    100.0%   100.0%
REFUND_NETTED                           5         5    100.0%   100.0%
ROUNDING_TOLERANCE_APPLIED              5         5    100.0%   100.0%
SPLIT_SETTLEMENT                        4         4    100.0%   100.0%
TDS_MISMATCH                            4         4    100.0%   100.0%
TRUNCATED_BANK_REFERENCE                5         5    100.0%   100.0%
UNKNOWN_BANK_CREDIT                    10        10    100.0%   100.0%
OVERALL                               102       102    100.0%   100.0%
```

### Run metrics

**Before self-healing** — the reference-format gap is open:

```
records processed     510
deterministic matches 463
partial matches        12
review required        11
duplicates              8
exceptions             16
unresolved              0
match rate          90.78%
exception rate       3.14%
total reconciled   Rs.2,13,02,329.01
unexplained value  Rs.8,63,527.44
audit events        1,017

CLEAN-MODE CONTROL   match rate 100.00%, residuals 0
```

**After the induced rule is validated and promoted** (see
[self-healing-rules.md](self-healing-rules.md)):

```
records processed     504
deterministic matches 469
residuals              29
match rate          93.06%
                    +6 matches · 0 regressions · +2.27pp · -Rs.61,592.62 unexplained
```

`unresolved = 0` is the meaningful number: every residual has an attributed
cause. The deterministic engine hands nothing to a future arbitrator that it
could not itself explain — which is the honest starting point for that layer.

**The match rate is not configured anywhere.** It emerges from the data. It is
asserted only to fall inside a sane band (85–98%) with 25–75 residuals, never
against a hardcoded figure.

---

**Back:** [📖 Auditability](auditability.md) · **Next:** [🤖 Arbitration](arbitration.md) · **Up:** [📘 README](../README.md)
