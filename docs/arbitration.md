# 🤖 Arbitration

> **Where AI is allowed to operate, and what stops it from being wrong.**

Nav: [Architecture](architecture.md) · [Data model](data-model.md) · [Engine](reconciliation-engine.md) · [Auditability](auditability.md) · [Demo data](demo-data.md) · **Arbitration** · [Self-healing rules](self-healing-rules.md) · [Forecasting & copilot](forecasting-and-copilot.md) · [Future AI layer](future-ai-layer.md)

---

## 🎯 The position

The deterministic engine resolves 469 of 504 records on the seed dataset and
attributes a specific cause to all 35 of the rest. Arbitration therefore reasons
about **35 explained residuals**, never 504 raw transactions.

That ratio is the design. An arbitrator is a component sitting on top of a
finished engine, handling the residue — not the thing doing the reconciliation.

```
      504 records
         │
         ├── 469  MATCHED         ← never seen by an arbitrator
         │
         └──  35  residuals       ← the only thing an arbitrator sees
                  │
                  ├── candidates found by deterministic retrieval
                  ├── arbitration decides (policy, or a model)
                  ├── verification gate re-checks the decision
                  └── proposal recorded, awaiting a human
```

## 🔒 Three rules, enforced not documented

### 1. The arbitrator receives only residuals

`ResidualCase` is the only shape any implementation sees. It is built by
`build_residual_case()` from evidence the engine already proved, plus candidates
from deterministic retrieval. It carries no dataset, no matched records and no
raw ledger.

`LLMResidualArbitrator.PERMITTED_INPUT_FIELDS` enumerates the permitted fields
explicitly, so a future implementation cannot quietly widen its own access.
`test_the_prompt_carries_only_permitted_fields` asserts the prompt contains
nothing else.

### 2. The arbitrator cannot write

`resolve()` returns an `ArbitrationResult` — a **proposal**. It has no path to a
financial record. Everything passes `verify_arbitration()` first.

### 3. The system works with no arbitrator

`NullArbitrator` is the fallback of last resort and declines every case
honestly. The degradation ladder never fails upward:

```
configured provider unreachable  →  DeterministicArbitrator
DeterministicArbitrator broken   →  NullArbitrator (declines)
```

A misconfigured AI provider produces honest exceptions, never an outage and
never a guess.

---

## 🧭 Deterministic candidate retrieval

Before anything reasons about a residual, `candidates.py` assembles the
plausible counterparts from the *other* residuals in the same run. This is
ordinary arithmetic over amounts and dates — reproducible, no model involved.

The pairing that matters in practice:

| Side | Reason codes | Meaning |
|---|---|---|
| 💰 Credit side | `UNKNOWN_BANK_CREDIT` | cash arrived with no home |
| 📄 Receivable side | `MISSING_SETTLEMENT`, `MISSING_BANK_TRANSACTION` | money owed with no cash located |

An unidentified credit and an order whose settlement is missing are frequently
**the same transaction with a broken reference**. The engine will not join them
— it refuses to guess. But it can legitimately place them side by side and
quantify the distance.

Amount tolerance defaults to **zero**. A near miss on money is usually a
different transaction, not the same one rounded.

**Ambiguity is never broken by guessing.** `unique_exact_candidate()` returns a
candidate only when exactly one matches the amount exactly. Two credits of the
same amount are genuinely indistinguishable on this evidence, and saying so is
the correct answer.

---

## ⚙️ The deterministic arbitrator — the default

`DeterministicArbitrator` requires no model, no network and no API key. It is
the default, and that is not a placeholder.

**Why an arbitrator that does not use AI is the right default:** most of what a
residual needs is not judgement at all. A payout that is proved but uncollected
needs an accrual. A duplicate receipt needs a liability recognised. An
unidentified credit needs parking in suspense. Those are bookkeeping *policy*,
and applying policy deterministically is strictly better than asking a model to
reproduce it.

### Bookkeeping policy table

| Reason code | Action | Confidence | Rule |
|---|---|---:|---|
| `MISSING_SETTLEMENT` | `ACCRUE_SETTLEMENT_RECEIVABLE` | 0.80 | `RULE-ARB-011` |
| `MISSING_BANK_TRANSACTION` | `ACCRUE_SETTLEMENT_RECEIVABLE` | 0.80 | `RULE-ARB-011` |
| `UNKNOWN_BANK_CREDIT` | `PARK_UNIDENTIFIED_CREDIT` | 0.80 | `RULE-ARB-012` |
| `DUPLICATE_SETTLEMENT` | `RECOGNISE_DUPLICATE_LIABILITY` | 0.80 | `RULE-ARB-013` |
| `DUPLICATE_BANK_TRANSACTION` | `RECOGNISE_DUPLICATE_LIABILITY` | 0.80 | `RULE-ARB-013` |
| `CHARGEBACK` | `BOOK_CHARGEBACK_LOSS` | 0.80 | `RULE-ARB-014` |
| `TDS_MISMATCH` | `BOOK_TDS_DIFFERENCE` | 0.75 | `RULE-ARB-015` |
| `GST_MISMATCH` | `BOOK_GST_DIFFERENCE` | 0.75 | `RULE-ARB-015` |
| `GATEWAY_FEE_MISMATCH` | `BOOK_FEE_DIFFERENCE` | 0.75 | `RULE-ARB-015` |
| `NET_AMOUNT_VARIANCE` | `BOOK_VARIANCE` | 0.75 | `RULE-ARB-016` |

### When it reaches RESOLVE

Exactly one situation: an unidentified credit and an unmatched receivable that
agree **to the paisa**, inside the date window, with no other candidate
competing. Confidence **0.95** (`RULE-ARB-010`).

That is not a guess. It is a one-to-one pairing the base engine declined only
because the bank reference was unusable.

Everything else is `PROBABLE` (a booking proposal) or `UNRESOLVED`.

---

## 🧠 The LLM arbitrator

`LLMResidualArbitrator` is fully implemented over Gemini, Anthropic and OpenAI.
What the model is asked to do is narrow, and that narrowness is the point:

- which of the **offered** candidates (if any) explains this residual
- which of the **permitted** bookkeeping actions applies
- a short rationale grounded in the evidence it was shown

It does **not** compute anything, does **not** choose an amount, and **cannot**
name an account.

| Guard | Mechanism |
|---|---|
| 🔢 Amount | Taken from the engine. `JournalBuilder` builds the batch from the action, not from the response. |
| 🎚️ Confidence ceiling | `MAX_MODEL_CONFIDENCE = 0.90`. `1.00` means an identifier matched or an invariant closed; no model produces that kind of evidence. |
| 📋 Action vocabulary | Anything outside `PERMITTED_ACTIONS` is dropped before the journal builder and rejected by the gate. |
| 🧾 JSON parsing | Fenced and prose-wrapped output is unwrapped; **malformed JSON is an error, never repaired**. |
| 🪂 Failure | Provider error, unparseable output, or nonsense decision → falls back to the deterministic arbitrator with the reason appended. |

Configure with `RECONGUARD_AI_PROVIDER=gemini` (or `anthropic` or `openai`) plus
the matching API key. Gemini uses `GEMINI_API_KEY` and defaults to
`gemini-2.5-flash`; override it with `GEMINI_MODEL` when needed. The default is
`none`.

---

## 🛡️ The verification gate

This is the "Verified AI" half of the product. Every proposal, whatever produced
it, passes through `verify_arbitration()`.

**The gate weighs arithmetic and provenance. It does not weigh confidence**,
because a confident wrong answer is the failure mode this whole system exists to
prevent.

A proposal is rejected when it:

| Check | Rule | Test |
|---|---|---|
| Cites a record it was never shown | `RULE-VER-001` | `test_a_proposal_citing_a_record_it_was_never_shown_is_rejected` |
| Claims `RESOLVE` with no evidence | `RULE-VER-001` | `test_resolve_without_evidence_is_rejected` |
| Proposes an action outside the vocabulary | `RULE-VER-002` | `test_an_action_outside_the_vocabulary_is_rejected` |
| Attaches a journal that does not balance, names an unknown account, or whose total ≠ the unexplained amount | `RULE-VER-003` | `test_a_batch_whose_total_differs_from_the_residual_is_rejected` |
| Claims `RESOLVE` on amounts that do not agree to the paisa | `RULE-VER-004` | `test_resolve_against_a_non_matching_amount_is_rejected` |

**A rejected proposal is downgraded to `UNRESOLVED` and the reasons are
recorded. Nothing is silently dropped** — what an arbitrator got wrong is
exactly the evidence needed to decide whether to keep trusting it.

---

## 🧾 Journal entries

An entry is a balanced pair by construction (one debit account, one credit
account, one integer-paise amount), so "debits equal credits" is structurally
true. That check alone would be theatre.

**The check that matters:** the batch total must equal the exact amount the
residual left unexplained.

> A model can propose an *explanation*. It cannot propose a *number*: the number
> is already known, to the paisa, from the deterministic engine.

### Chart of accounts

12 accounts. `resolve()` rejects anything else.

| Code | Account | Type |
|---|---|---|
| `1000` | Bank Account | Asset |
| `1100` | Settlement Receivable | Asset |
| `1200` | Suspense Account | Asset |
| `1300` | Accounts Receivable | Asset |
| `1400` | GST Input Credit | Asset |
| `1500` | TDS Receivable | Asset |
| `2000` | Merchant Payable | Liability |
| `4000` | Revenue | Income |
| `5000` | Gateway Fee Expense | Expense |
| `5300` | Chargeback Loss | Expense |
| `5400` | Refunds | Expense |
| `9000` | Reconciliation Variance | Expense |

### Posting lifecycle

```
PROPOSED ──approve──▶ APPROVED ──post──▶ POSTED
    │                     │
    └────── reject ───────┴──────────────▶ REJECTED
```

- Every transition requires a **named actor**; an unattributed ledger change is
  not auditable.
- `POST` is refused unless the entry is `APPROVED`.
- The batch is **re-verified at posting time**, not trusted from proposal time:
  the two events are separated by a human decision and possibly a configuration
  change, and the check is cheap.
- The trial balance reflects `POSTED` entries only. Including proposals would
  make it a wish rather than a balance.

---

## 🔌 API

```http
POST /api/arbitration/run          { run_id?, arbitrator?, propose_rules? }
GET  /api/arbitration/results      ?run_id=&decision=&accepted_only=
GET  /api/arbitration/queue        what an arbitrator would receive
GET  /api/journal                  ?run_id=&status=&residual_id=
POST /api/journal/{id}/decide      { decision: APPROVE|REJECT|POST, actor, note }
GET  /api/journal/trial-balance    ?run_id=
GET  /api/accounting/chart
```

## 📊 Measured on the seed dataset

```
residuals examined      47
accepted by the gate    47
rejected                 0
decisions               RESOLVE 12 · PROBABLE 35
journal entries         47 proposed, none posted
rules induced            1 (see self-healing-rules.md)
```

---

**Back:** [🧪 Demo data](demo-data.md) · **Next:** [🔧 Self-healing rules](self-healing-rules.md) · **Up:** [📘 README](../README.md)
