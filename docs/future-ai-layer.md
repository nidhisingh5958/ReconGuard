# 🔭 Roadmap & AI layer status

Nav: [Architecture](architecture.md) · [Data model](data-model.md) · [Reconciliation engine](reconciliation-engine.md) · [Auditability](auditability.md) · [Demo data](demo-data.md) · [Arbitration](arbitration.md) · [Self-healing rules](self-healing-rules.md) · [Forecasting & copilot](forecasting-and-copilot.md) · **Roadmap**

---

> This document was originally a design sketch for a layer that did not exist.
> Most of it is now built. It is kept as the honest status page: what shipped,
> what is deliberately absent, and what a next phase would actually need.

## ✅ Shipped

| Capability | Status | Reference |
|---|---|---|
| 🤖 Residual arbitration | ✅ Deterministic arbitrator (default) **and** LLM arbitrator over Anthropic/OpenAI | [arbitration.md](arbitration.md) |
| 🛡️ Verification gate | ✅ Every proposal re-checked; rejects downgrade to `UNRESOLVED` | [arbitration.md](arbitration.md#️-the-verification-gate) |
| 🧾 Journal entries | ✅ Built, verified, `PROPOSED → APPROVED → POSTED`, trial balance | [arbitration.md](arbitration.md#-journal-entries) |
| 🔧 Rule induction | ✅ Patterns induced from arbitration pairings | [self-healing-rules.md](self-healing-rules.md#-③-induction--deterministic-not-generative) |
| 📏 Rule validation | ✅ Replay-based, regressions disqualifying | [self-healing-rules.md](self-healing-rules.md#-④-validation-by-replay) |
| 🔐 Rule promotion | ✅ Requires measured evidence **and** a named human | [self-healing-rules.md](self-healing-rules.md#-⑤-promotion--the-human-gate) |
| ⚙️ Promoted rules change the engine | ✅ Loaded per run; fallback-only, never overrides | [self-healing-rules.md](self-healing-rules.md#️-how-a-promoted-rule-executes) |
| 📈 Cash forecasting | ✅ Committed pipeline + backtested band | [forecasting-and-copilot.md](forecasting-and-copilot.md) |
| 🧭 Finance copilot | ✅ Grounded retrieval, 8 intents | [forecasting-and-copilot.md](forecasting-and-copilot.md#-part-2--finance-copilot) |

## 🚫 Deliberately absent

These are **choices**, not gaps:

- **Automatic promotion.** Validation is automatic because measuring is safe.
  Promotion is not, because it changes what the engine matches on every future
  run. That gate stays human.
- **Auto-posting of journal entries.** Every entry needs an explicit, attributed
  decision. Nothing reaches the ledger on a model's say-so.
- **A language layer over the copilot.** Retrieval already guarantees the answer
  cannot be wrong. Adding generation before there is a reason to would trade
  that guarantee for prose.
- **Point-estimate forecasts.** Projection is reported as a band with a
  backtested coverage figure. A single confident number would be less honest and
  less useful.

## 🧱 What a next phase would need

| # | Work | Why it is not trivial |
|--:|---|---|
| 1 | **A second dynamic rule type** | Induction and validation are per-type. The lifecycle, safety validation and engine integration are already type-agnostic; each new type needs an inducer and a replay validator. |
| 2 | **Authentication and authorisation** | The `actor` field is self-declared. It gives attribution, not identity. See [SECURITY.md](../SECURITY.md#-known-gaps). |
| 3 | **Multi-currency** | Everything is integer paise in INR. Multi-currency needs a currency dimension on every amount plus an FX-rate source with its own audit trail. |
| 4 | **Streaming / incremental reconciliation** | The engine is batch and rebuilds indexes per run. Incremental matching needs index persistence and careful invalidation. |
| 5 | **Regex safety hardening** | Promoted patterns are structurally validated but not analysed for catastrophic backtracking. See [SECURITY.md](../SECURITY.md#-on-regex-denial-of-service). |
| 6 | **Copilot language layer** | Constrained to `answer_question()` output, forbidden from adding to it. |

## 🧭 The principle that has not moved

> **Never use an LLM for something that can be deterministically calculated or
> verified.**

Everything above was built inside that constraint. The arbitration layer exists
because some residuals genuinely need judgement — and even there, the judgement
is bounded, the amount comes from the engine, and the answer is verified before
it counts.

---

**Back:** [📈 Forecasting & copilot](forecasting-and-copilot.md) · **Up:** [📘 README](../README.md)
