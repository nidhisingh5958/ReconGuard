# Auditability

Nav: [Architecture](architecture.md) · [Data model](data-model.md) · [Reconciliation engine](reconciliation-engine.md) · **Auditability** · [Demo data](demo-data.md) · [Arbitration](arbitration.md) · [Self-healing rules](self-healing-rules.md) · [Forecasting & copilot](forecasting-and-copilot.md) · [Future AI layer](future-ai-layer.md)

---

## The bar

Every audit event must be able to answer *"why was this matched?"* without the
reader needing access to the engine source. That means the literal arithmetic
and the source record ids both live on the event.

## AuditEvent

| Field | Purpose |
|---|---|
| `audit_id` | `AUD-000001`, sequential and unique within a run |
| `timestamp` | UTC |
| `action` | see the action vocabulary below |
| `actor` | `deterministic-engine` today; an arbitrator would be named here |
| `reconciliation_id` | the decision this event belongs to |
| `run_id` | the run |
| `source_records` | every record id involved |
| `rule_id` | the rule that fired |
| `calculation` | **the literal arithmetic with real values substituted** |
| `previous_state` / `new_state` | the transition, rather than an overwrite |
| `evidence` | record ids backing the conclusion |
| `detail` | structured payload (confidence, variances, adjustment) |
| `system_version` | which build produced this |

## Actions

| Action | Emitted when |
|---|---|
| `RUN_STARTED` / `RUN_COMPLETED` | run boundaries, with configuration and final metrics |
| `DATA_INGESTED` | indexes built, with counts per source |
| `ADJUSTMENT_RECORDED` | a netted refund or chargeback becomes an `AdjustmentRecord` |
| `RECONCILIATION_MATCH` / `_PARTIAL` / `_DUPLICATE` / `_EXCEPTION` | a decision is reached |
| `INVARIANT_VERIFIED` / `INVARIANT_VIOLATED` | the accounting equation is tested |
| `ARBITRATION_REQUESTED` / `ARBITRATION_SKIPPED` | reserved for the AI layer |
| `RULE_PROPOSED` / `RULE_STATUS_CHANGED` | reserved for rule promotion |

The seed run of 500 orders writes **1,011 audit events**.

## Append-only

The ledger has no update and no delete path. `AuditLedger.record()` appends;
`AuditEventRow` is never mutated by application code. State changes are recorded
as `previous_state` → `new_state` pairs rather than by overwriting a field.

Evidence and calculations are stored as JSON **snapshots** on the record. They
capture what the engine proved at the moment of the run. Re-deriving them later
from a changed engine would silently rewrite history.

## A real event

```json
{
  "audit_id": "AUD-000013",
  "action": "RECONCILIATION_MATCH",
  "actor": "deterministic-engine",
  "reconciliation_id": "REC-00001",
  "rule_id": "RULE-MATCH-001",
  "calculation": "1027400 - 20548 - 3699 - 1027 - 775300 = 226826 == reported net 226826",
  "previous_state": "UNRECONCILED",
  "new_state": "MATCHED",
  "source_records": ["ORD-10001", "PAY-89001", "SET-10005", "BANK-77005", "INV-10001"],
  "detail": {
    "match_type": "EXACT_PAYMENT_ID",
    "confidence": 1.0,
    "confidence_method": "EXACT_IDENTIFIER",
    "reason_codes": ["REFUND_NETTED"],
    "variance_paisa": 0
  },
  "system_version": "reconguard/0.1.0"
}
```

## "Why was this matched?"

`GET /api/reconciliation/records/{id}/explain` assembles the complete answer
from stored evidence. It contains **no language model**. The answer is read
back, not generated:

```
verdict   Matched by EXACT_PAYMENT_ID at confidence 1.00 (EXACT_IDENTIFIER).
          The settlement equation closed exactly at Rs.2,268.26.

CALCULATION
  Gateway fee               1027400 x 200/10000 = 20548                    [RULE-FEE-001]
  GST on gateway fee        20548 x 1800/10000 = 3699                      [RULE-TAX-001]
  TDS withheld              1027400 x 10/10000 = 1027                      [RULE-TAX-002]
  Refunds netted in payout  netted refunds = 775300                        [RULE-ADJ-001]
  Expected net settlement   1027400 - 20548 - 3699 - 1027 - 775300 = 226826 [RULE-NET-001]
  Invariant verified        ... == reported net 226826                     [RULE-NET-001]

MATCHING LOGIC
  Layer 1 - exact identifiers      Order ORD-10001 resolved to payment PAY-89001,
                                   settlements SET-10005
  Layer 2 - accounting invariant   Expected Rs.2,268.26 vs actual Rs.2,268.26, variance Rs.0.00
  Layer 5 - netting                1 adjustment(s): REFUND_NETTING
  Layers 1/3 - bank confirmation   Cash confirmed by BANK-77005 via EXACT_IDENTIFIER

EVIDENCE
  [SETTLEMENTS] SET-10005  Settlement reports refund_adjustment of 775300 paise
                           attributed to PAY-89132
  [ORDERS]      ORD-10132  Order ORD-10132 records refund_amount 775300 paise,
                           status 'refunded'
  [BANK]        BANK-77005 Narration 'RZP  SETTLEMENT   SET-10005' contains
                           settlement key 10005; credit 226826 paise
```

That example is the netting guarantee visible end to end: `ORD-10001`'s payout
was reduced by a refund belonging to a **different** order, and both orders
reconcile because the adjustment names the relationship.

## Reproducibility

Reproducibility is a product requirement, not a nicety. Identical input
produces byte-identical output, including generated ids:

- ids come from per-run sequence counters, not UUIDs or timestamps
- orders are processed in sorted id order
- settlements are processed in sorted id order when claiming bank credits
- the synthetic generator is seeded

Asserted by `test_run_is_reproducible` and `test_generator_is_byte_deterministic`.

This is why run comparison is meaningful: when two runs over the same dataset
differ, the difference is attributable to an engine change and never to data
drift or iteration order. Comparing the seed dataset against itself yields
`deterministic_match_delta = 0` and `reason_code_deltas = {}`.

## Filtering

`GET /api/audit` filters by `run_id`, `reconciliation_id`, `action`, `rule_id`,
`actor`, `new_state`, `source_record`, `date_from`, `date_to`. The response also
returns facets (the distinct actions, rules and actors present) so the UI builds
its filter controls from real data rather than a hardcoded list.

---

**Back:** [⚙️ Reconciliation engine](reconciliation-engine.md) · **Next:** [🧪 Demo data](demo-data.md) · **Up:** [📘 README](../README.md)
