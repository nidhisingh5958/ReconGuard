# 🔧 Self-healing rules

> **A promoted rule is executable configuration that changes what the next run matches — not a row in a table that a dashboard counts.**

Nav: [Architecture](architecture.md) · [Data model](data-model.md) · [Engine](reconciliation-engine.md) · [Auditability](auditability.md) · [Demo data](demo-data.md) · [Arbitration](arbitration.md) · **Self-healing rules** · [Forecasting & copilot](forecasting-and-copilot.md) · [Cash Resilience](cash-resilience.md) · [Finance Copilot](finance-copilot.md) · [Future AI layer](future-ai-layer.md)

---

## 🩹 The problem this solves

Acquirers and banks change their narration format without notice. When they do,
the built-in digit-run extractor stops finding the settlement key, previously
matched payouts fall out to exceptions, and somebody has to teach the system the
new shape.

The seed dataset contains exactly this failure, injected as
`UNRECOGNISED_REFERENCE_FORMAT` (6 per 500 orders):

```
ACH CR//PGWX/9910291/MERCHANT ACCT
```

It defeats **both** built-in paths, deliberately:

| Path | Why it fails |
|---|---|
| Digit-run extraction | Recovers `9910291`, not the settlement key `10291` — the acquirer prepends `99` |
| Amount + date fallback | Requires a gateway marker; `PGWX` contains none, so the narration is not recognised as a payout at all |

Result: the order becomes `PARTIAL_MATCH` (cash never located) **and** the credit
becomes `UNKNOWN_BANK_CREDIT`. One format change, two residuals, six times over.

> ⚠️ If you change `UNRECOGNISED_REFERENCE_TEMPLATE` in the generator, verify it
> still defeats both paths. A marker containing `RZP` would be caught by the
> amount+date fallback and the gap would silently disappear.

---

## 🔁 The loop

```
   ①  RECONCILE          463/510 matched · 90.78% · 35 residuals
              │
   ②  ARBITRATE          pairs 6 unknown credits with 6 unmatched receivables
              │          (exact amount, inside the date window, unambiguous)
              │
   ③  INDUCE             a pattern shared by all 6 narrations
              │          PGWX\s+99(\d{5})   anchor: PGWX   support: 6
              │
   ④  VALIDATE           replay the dataset with and without the rule
              │          +6 matched · 0 regressions · +2.27pp  →  APPROVED
              │
   ⑤  PROMOTE            a named human activates it            →  ACTIVE
              │
   ⑥  RECONCILE          469/504 matched · 93.06% · 29 residuals
                         −₹61,592.62 unexplained
```

Every arrow is measured. Nothing in this loop is asserted.

---

## 🔬 ③ Induction — deterministic, not generative

Arbitration pairing tells us something the base engine did not know: **which
settlement key is hiding inside a narration it could not parse.**
`proposal.py` turns a set of those pairings into a candidate rule:

1. **Locate** the target settlement key as a substring of the normalized narration.
2. **Split** the whitespace token containing it into literal-prefix / key / literal-suffix.
3. **Anchor** on the preceding alphabetic token, so the pattern cannot fire on an
   arbitrary number elsewhere on the statement.
4. **Group** samples by that shape. A shape needs `MIN_SUPPORT = 3` independent
   examples — one coincidence is not a format.
5. **Verify** against every supporting sample **and** against a control set of
   narrations it must not claim.

For the example above this yields:

```
pattern   PGWX\s+99(\d{5})
marker    PGWX
support   6 independent arbitration pairings
```

A proposal that fails step 5 is **discarded rather than surfaced**. The point of
proposing a rule is to save an operator work, and a rule they have to debug is
worse than no rule.

### Controls

Control narrations are drawn from `MATCHED` records in the same run — the lines
the base engine already parses correctly. A new rule that also fires on them
would be competing with a link that is already proved, so it is rejected.

---

## 🛡️ Rule safety validation

`REFERENCE_EXTRACTION` rules are regex, but deliberately not arbitrary code.
`validate_reference_rule()` runs at proposal time, at promotion time, **and**
again whenever a rule set is loaded, so a rule that would fail today is never
executed even if it was stored earlier.

| Requirement | Why | Rejected example |
|---|---|---|
| Must compile | Obvious | `([0-9` → *unterminated character set* |
| Exactly one capture group | The group *is* the settlement key | `(A)(\d{5})` → *found 2* |
| Mandatory anchor (≥3 chars) | An unanchored pattern would claim every number on the statement, including amounts and account numbers | `(\d{5})` with no marker |
| ≤ 240 characters | Far beyond anything a narration format needs | — |
| Extracted key ≥ 4 digits | Shorter is not a settlement reference | — |

---

## 📏 ④ Validation by replay

**A rule is promoted because a replay showed it helped, never because something
was confident about it.**

`validate_rule()` runs the engine twice over the same dataset — once without the
candidate, once with it — and compares record by record. This is only meaningful
because the engine is reproducible: identical input yields identical output
including ids, so **every difference is attributable to the rule and nothing
else**.

Two measurements, and the second matters more:

- **Improvement** — how many records moved into `MATCHED`
- **Regression** — whether **any** record that was `MATCHED` stopped being matched

> A rule that fixes six records and breaks one is not a good trade. Regressions
> are **disqualifying**, not merely subtracted, and the specific records are
> named so a human can see what would have broken.

The candidate is measured **on top of** already-promoted rules, because that is
the configuration it would actually run in.

| Verdict | Meaning | Resulting status |
|---|---|---|
| `IMPROVES` | match delta > 0, zero regressions | `APPROVED` |
| `NEUTRAL` | nothing moved | `REJECTED` |
| `REGRESSES` | at least one record stopped matching | `REJECTED` |
| `INVALID` | failed structural safety validation | `REJECTED`, never replayed |

---

## 🔐 ⑤ Promotion — the human gate

```
PROPOSED ──▶ VALIDATING ──▶ APPROVED ──▶ ACTIVE ──▶ RETIRED
                  │              │
                  └──────────────┴──▶ REJECTED
```

The lifecycle is split so the **safe half is automatic and the consequential
half is not**:

- **Measurement is automatic** because measuring is safe, and a human reading
  numbers off a screen adds nothing to their reliability.
- **Promotion requires a person** because it is the only transition that changes
  what the engine does.

`registry.promote()` refuses unless:

| Guard | Error |
|---|---|
| Status is `APPROVED` | *"only an APPROVED rule may be promoted, and approval requires a replay that improved matching with no regressions"* |
| A named actor is supplied | *"an unattributed change to what the engine matches is not auditable"* |
| Safety validation still passes | *"no longer passes safety validation"* |

---

## ⚙️ How a promoted rule executes

```python
# indexes.py — a dynamic rule is a FALLBACK, never an override
if rules and not any(k in index.settlement_key_to_ids for k in keys):
    for key, rule_id in rules.extract_keys(extracted.normalized):
        ...
```

**A promoted rule can add matches but can never take a bank row away from a link
the base engine already proved.** It runs only where the built-in extractor
produced nothing that resolves.
`test_a_dynamic_rule_never_overrides_a_proved_built_in_match` locks this in with
a deliberately greedy pattern.

Matches sourced from a rule are attributed: the result carries
`PROMOTED_RULE_APPLIED` (an *informational* reason code — it explains how a
match was proved and never blocks it), the rule id appears in `rule_ids`, and
the evidence names it:

> *Settlement key 10291 was recovered from narration `'ACH CR//PGWX/9910291/MERCHANT ACCT'`
> by promoted rule RULE-DYN-001; the built-in extractor found nothing usable in it*

---

## 📊 Measured result

| | Before | After | Δ |
|---|---:|---:|---:|
| Deterministic matches | 463 | 469 | **+6** |
| Residuals | 35 | 29 | **−6** |
| Match rate | 90.78% | 93.06% | **+2.27pp** |
| Regressions | — | — | **0** |
| Unexplained value | — | — | **−₹61,592.62** |

---

## 🔌 API

```http
GET  /api/rules                       catalogue, validations, lifecycle
POST /api/rules/{id}/validate         { dataset_id? }  → replay and record
POST /api/rules/{id}/promote          { actor, note }  → requires APPROVED
POST /api/rules/{id}/reject           { actor, note }
POST /api/rules/{id}/retire           { actor, note }  → requires ACTIVE
```

### Reproduce the loop

```bash
A=http://127.0.0.1:8000/api
curl -X POST $A/reconciliation/run          -H 'Content-Type: application/json' -d '{"label":"before"}'
curl -X POST $A/arbitration/run             -H 'Content-Type: application/json' -d '{"arbitrator":"deterministic"}'
curl -X POST $A/rules/RULE-DYN-001/validate -H 'Content-Type: application/json' -d '{}'
curl -X POST $A/rules/RULE-DYN-001/promote  -H 'Content-Type: application/json' \
     -d '{"actor":"you@company.com","note":"Acquirer changed narration format."}'
curl -X POST $A/reconciliation/run          -H 'Content-Type: application/json' -d '{"label":"after"}'
curl "$A/reconciliation/runs/compare?baseline=RUN-00001&candidate=RUN-00002"
```

> 💡 If the database already holds a promoted `RULE-DYN-001`, delete
> `data/reconguard.db*` to see the before/after contrast again.

---

## 🎨 Multi-Pattern Self-Healing Rules (Phase 3)

ReconGuard Phase 3 expands self-healing rule induction beyond reference extraction to cover gateway fee rounding/tolerances and date window drifts:

| Rule Type | Pattern Induced / Applied | Engine Integration Layer | Safe DSL Operator |
|---|---|---|---|
| `REFERENCE_EXTRACTION` | Regex pattern matching with mandatory anchor and digit group | Extraction Layer (`indexes.py`) | Regex capture group with prefix anchor |
| `AMOUNT_TOLERANCE` | Gateway fee rounding & variance absorption (`amount_tolerance`) | Matching Layer 4 (`bank_matching.py`) | `abs(settlement.net - bank.credit) <= tolerance` |
| `DATE_TOLERANCE` | Date window expansion for weekend / holiday settlement delays | Matching Layer 4 (`bank_matching.py`) | `abs((bank.date - settlement.date).days) <= tolerance` |

### 🔒 Safe Dynamic DSL Execution
All dynamic rules operate via structural AST-like execution classes (`AmountToleranceRule`, `DateToleranceRule`, `ReferenceRule`).
- Zero reliance on Python `eval()` or `exec()`.
- Immutable parameters and strict structural type validation.
- Rules are fallback matches (`ReasonCode.PROMOTED_RULE_APPLIED`), never overriding deterministic built-in invariants.

---

## 📊 Backtest Metrics & AI Dependency Reduction

Replay backtesting measures the precise operational impact of a candidate rule across historical runs:

$$\text{AI Dependency Reduction} = 1 - \frac{\text{AI\_residuals\_after\_rule}}{\text{AI\_residuals\_before\_rule}}$$

- **Records Affected**: Number of total residual records touched by the rule.
- **Additional Matches**: Net new valid matches converted from residual exceptions.
- **False Positives**: Incorrect matches detected against ground-truth validation sets.
- **Precision & Recall**: Standard statistical quality metrics ($P = \frac{TP}{TP + FP}$).
- **Estimated AI Calls Avoided**: Reduction in AI LLM calls required per reconciliation run.
- **Estimated Cost Avoided ($)**: Cost savings based on LLM prompt/completion token pricing (~$0.01 per residual case).

---

## 🚀 90-Second Interactive Demo Scenario

For live demonstration and evaluation, ReconGuard provides an automated demo scenario endpoint:

```http
POST /api/rules/demo-scenario
```

1. Executes initial baseline reconciliation and AI arbitration.
2. Identifies residual patterns (gateway rounding, reference formatting, date window drift).
3. Induces high-confidence rule proposals (`RULE-DYN-001`, `RULE-DYN-002`, `RULE-DYN-003`).
4. Replays backtests to verify zero regressions and calculate AI Dependency Reduction (typically ~57% reduction in AI residuals).
5. Exposes interactive Human Approval controls on the `/rules` frontend page to activate rules into the deterministic engine.

---

**Back:** [🤖 Arbitration](arbitration.md) · **Next:** [📈 Forecasting & copilot](forecasting-and-copilot.md) · **Up:** [📘 README](../README.md)
