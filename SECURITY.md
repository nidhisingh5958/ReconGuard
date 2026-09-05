# 🔒 Security Policy

ReconGuard handles financial records. This document covers how to report a
vulnerability, what the system's security posture actually is today, and — just
as importantly — what it is **not** yet hardened for.

---

## 📮 Reporting a vulnerability

**Do not open a public issue for a security vulnerability.**

| | |
|---|---|
| 📧 Contact | `security@` the project owner's domain |
| ⏱️ Acknowledgement | within 3 working days |
| 🔍 Triage and severity | within 10 working days |
| 🛠️ Fix target | Critical 7 days · High 30 days · Medium 90 days |

Please include: affected version or commit, reproduction steps, the impact you
believe it has, and any proof-of-concept. If you would like credit in the
release notes, say so and how you want to be named.

We will not pursue legal action against good-faith research that stays within
the boundaries below.

### In scope

- The reconciliation engine and accounting layers
- The API surface (`backend/app/api/`)
- Authentication and authorisation, once implemented (see [Known gaps](#-known-gaps))
- The arbitration verification gate — see [Threat model](#-threat-model)
- Dependency vulnerabilities with a demonstrated path to exploitation here

### Out of scope

- Attacks requiring physical access to a developer machine
- Social engineering
- Denial of service by volume against a local development server
- Findings in the synthetic data generator, which produces fictional records
- "Missing security header" reports with no demonstrated impact

---

## 🛡️ Security posture

### What the design already guarantees

| Property | How it is enforced | Verified by |
|---|---|---|
| 🧮 No floating-point money | `rupees_to_paisa()` raises `TypeError` on a `float`; every money column is `BigInteger` paise | `test_accounting.py::test_float_money_input_is_rejected` |
| 📖 Append-only audit trail | No update or delete path exists for `audit_events`; state changes are `previous_state`→`new_state` pairs | [`docs/auditability.md`](docs/auditability.md) |
| 🤖 No model can write a financial record | An arbitrator returns a *proposal*; `verify_arbitration()` gates every one | `test_arbitration.py` (12 adversarial gate tests) |
| 🔢 No model can choose an amount | Amounts come from the engine; the batch total must equal the residual's unexplained amount to the paisa | `test_llm_arbitrator_uses_the_engine_amount_not_the_model_amount` |
| 🏷️ No model can name an account | `chart_of_accounts.resolve()` rejects anything outside the 12-account chart | `test_an_unknown_account_is_rejected` |
| ✍️ Ledger changes are attributed | `posting.decide()` and `registry.promote()` refuse an empty actor | `test_a_journal_decision_requires_a_named_actor` |
| 🧾 Nothing posts itself | `PROPOSED → APPROVED → POSTED`, each step explicit; the batch is re-verified at posting time | `test_posting_without_approval_is_refused` |
| 🔁 Reproducibility | Sequence-based ids, sorted iteration, seeded generator — identical input yields identical output | `test_run_is_reproducible` |

### 🧠 Threat model for the AI layer

The delegated component is treated as **untrusted input**, not as a trusted
subsystem. A model that is compromised, prompt-injected, or simply wrong is
assumed, and the containment is structural rather than advisory:

```
                    ┌──────────────────────────────────────────┐
  residual case ───▶│  arbitrator (may be a language model)    │───▶ proposal
  (bounded view)    └──────────────────────────────────────────┘        │
                                                                         ▼
                    ┌──────────────────────────────────────────┐
                    │  verify_arbitration()  — deterministic    │
                    │  • cites only records it was shown?       │
                    │  • action inside the permitted vocabulary?│
                    │  • RESOLVE only on exact amount agreement?│
                    │  • journal balances AND equals the        │
                    │    engine's unexplained amount?           │
                    └──────────────────────────────────────────┘
                             │ pass                  │ fail
                             ▼                       ▼
                       recorded proposal      downgraded to UNRESOLVED,
                       (still needs a human)  reasons recorded, never dropped
```

Concretely:

- 🔒 **Bounded input.** `ResidualCase` is the only shape any model sees.
  `LLMResidualArbitrator.PERMITTED_INPUT_FIELDS` enumerates the fields, so the
  implementation cannot widen its own access. The dataset, the matched records
  and the raw ledger are never in a prompt.
- 🚫 **Confidence carries no authority.** The gate weighs arithmetic and
  provenance only. A proposal asserting `confidence: 1.0` fails exactly the same
  checks as one asserting `0.1`. Model-asserted confidence is additionally
  capped at `0.90`, because `1.00` in this system means an identifier matched or
  an invariant closed.
- 🧯 **Failure degrades, never escalates.** A provider error, an unparseable
  response, or a rejected proposal falls back to the deterministic arbitrator.
  A misconfigured AI provider produces honest exceptions, not an outage and not
  a guess.
- ⚖️ **Rule promotion needs evidence *and* a person.** A rule reaches `ACTIVE`
  only after a replay showed it improved matching with zero regressions, and
  only when a named actor promotes it. A promoted rule can add matches but
  cannot displace one the built-in path already proved.

### 🔐 Handling of secrets

- API keys are read from the environment only (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`) and are never logged, persisted, or returned by any endpoint.
- `GET /api/health` reports the provider *name* and whether AI is enabled. It
  never reports whether a key is present or valid.
- `.env` is gitignored. `.env.example` contains no real values.
- The synthetic generator produces fictional customers and structurally
  plausible but invalid GSTINs. No dataset in this repository contains real
  personal or financial data.

---

## ⚠️ Known gaps

This is a hackathon build. These are stated plainly rather than left for you to
discover, and **must be closed before any deployment handling real financial
data**:

| Gap | Impact | Notes |
|---|---|---|
| 🔓 **No authentication or authorisation** | Every endpoint is unauthenticated | The `actor` field on decisions is *self-declared*, not verified. It gives attribution, not identity. |
| 🌐 **CORS is open to localhost dev origins** | Fine locally, wrong in production | `backend/app/main.py` |
| 🧾 **No rate limiting** | A caller can trigger unbounded reconciliation runs | Runs are CPU-bound and can be large |
| 📝 **No request audit for API callers** | The audit trail records engine decisions, not who called the API | Complements, does not replace, the engine audit trail |
| 🗄️ **SQLite by default** | No encryption at rest; single-writer | PostgreSQL is supported via `RECONGUARD_DATABASE_URL` and is the intended production target |
| 🔑 **No secret management integration** | Keys come from environment variables only | No Vault/KMS/Secrets Manager wiring |
| 🧪 **Dynamic rules execute regex** | A promoted rule runs `re` against narrations | Mitigated: patterns are structurally validated (must compile, exactly one capture group, mandatory anchor, length cap) and require a replay plus a human. Not currently protected against a deliberately catastrophic-backtracking pattern — see below. |

### 🐌 On regex denial of service

`ReferenceExtractionRule` compiles operator-supplied patterns. Validation
rejects non-compiling patterns, patterns without an anchor, and patterns over
240 characters, but it does **not** analyse for catastrophic backtracking. In
the current design a malicious pattern would need to survive proposal, a replay
and a human promotion, so the practical risk is low — but if you expose rule
authoring to untrusted users, add a timeout or a linear-time engine (`re2`)
first.

---

## 🔢 Supported versions

| Version | Supported |
|---|---|
| `0.2.x` (current) | ✅ |
| `< 0.2` | ❌ |

## 🔗 Related documentation

- [`docs/auditability.md`](docs/auditability.md) — audit event schema and reproducibility guarantees
- [`docs/arbitration.md`](docs/arbitration.md) — the verification gate in full
- [`docs/self-healing-rules.md`](docs/self-healing-rules.md) — rule safety validation and promotion gates
- [`README.md`](README.md) — project overview
