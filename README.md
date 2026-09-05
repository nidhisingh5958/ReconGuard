<div align="center">

# 🛡️ ReconGuard

### The self-auditing finance controller

**Deterministic reconciliation · Verified AI · Zero silent exceptions**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![React](https://img.shields.io/badge/React-18.3-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-6.4-646CFF?logo=vite&logoColor=white)](https://vite.dev/)
[![Tailwind](https://img.shields.io/badge/Tailwind-3.4-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)

[![Match rate](https://img.shields.io/badge/match_rate-93.06%25-3FCF8E)](docs/demo-data.md)
[![Ground truth](https://img.shields.io/badge/precision%20%2F%20recall-100%25%20%2F%20100%25-3FCF8E)](docs/demo-data.md)
[![Clean mode](https://img.shields.io/badge/clean_mode-100.00%25-3FCF8E)](docs/demo-data.md)
[![Throughput](https://img.shields.io/badge/throughput-~9%2C700%20rec%2Fsec-56A8F5)](docs/architecture.md)
[![Money](https://img.shields.io/badge/money-integer_paise-F0B429)](docs/data-model.md)
[![LLM required](https://img.shields.io/badge/LLM_required-no-3FCF8E)](docs/arbitration.md)
[![Security](https://img.shields.io/badge/security-policy-FF6B6B)](SECURITY.md)

</div>

---

ReconGuard reconciles orders, payment-gateway settlements, bank statements and
the invoice register into one provable position. Every match is backed by an
accounting invariant and its literal arithmetic. Every exception states what
could *not* be established.

> ### 🎯 The governing principle
> **Never use an LLM for something that can be deterministically calculated or verified.**

AI operates only on unresolved residuals, and even there it cannot choose an
amount, name an account, or write a record. Everything it proposes is
re-verified deterministically before it counts.

---

## ⚡ Quick start

Two terminals. No external services, no API keys.

```bash
# 1️⃣  backend
cd backend
uv sync --extra dev                              # installs all deps into .venv
uv run python -m scripts.generate_dataset --messy   # 500 orders → data/seed-500/
uv run uvicorn app.main:app --reload            # http://127.0.0.1:8000  · docs at /docs

# 2️⃣  frontend
cd frontend
npm install
npm run dev                                      # http://127.0.0.1:5173
```

Then press **Run reconciliation** in the top-right.

🗄️ SQLite is the zero-config default. For PostgreSQL, set one variable:

```bash
RECONGUARD_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/reconguard
```

## 🔬 Verify it

```bash
cd backend  && uv run pytest              # 180 tests — engine, accounting, arbitration, rules
cd backend  && uv run python -m scripts.benchmark   # throughput + ground-truth precision/recall
cd frontend && npm test && npm run build     # 17 tests + typecheck + production build
```

[![Backend tests](https://img.shields.io/badge/backend_tests-180_passing-3FCF8E)](backend/tests)
[![Frontend tests](https://img.shields.io/badge/frontend_tests-17_passing-3FCF8E)](frontend/src)

---

## 🔄 The self-healing demo

An acquirer changes its bank narration format. Six payouts stop matching. Watch
the system diagnose it, propose a fix, prove the fix works, and — only after a
human approves — apply it.

```
①  RECONCILE     463/510 matched · 90.78% · 35 residuals
②  ARBITRATE     pairs 6 unknown credits with 6 unmatched receivables
③  INDUCE        PGWX\s+99(\d{5})   anchor PGWX   support 6
④  VALIDATE      replay: +6 matched · 0 regressions · +2.27pp  →  APPROVED
⑤  PROMOTE       a named human activates it                    →  ACTIVE
⑥  RECONCILE     469/504 matched · 93.06% · 29 residuals · −₹61,592.62 unexplained
```

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

📖 Full walkthrough: **[docs/self-healing-rules.md](docs/self-healing-rules.md)**

---

## 📊 Measured results — seed dataset, 500 orders, seed 42

| | |
|---|---:|
| 📥 Source records | 1,989 |
| 🧾 Reconciliation records | 504 |
| ✅ Deterministic matches | 469 |
| 🎯 **Match rate** | **93.06%** |
| ⚠️ Residuals | 29 |
| ❓ Unresolved (no attributed cause) | **0** |
| ⏱️ Processing time | 53 ms |
| 🚀 Throughput | ~9,700 records/sec |
| 📖 Audit events written | 1,017 |
| 🔍 **Ground-truth precision / recall** | **100% / 100%** (102 of 102) |
| 🧪 **Clean-mode control** | **100.00%** |

The match rate is **not configured anywhere**. It emerges from the data.
Scaling is linear: 500 → 10,000 records is 20× the volume for ~26× the time.

---

## 🧩 What is built

### ⚙️ Deterministic core

| Area | Status |
|---|---|
| 💰 Integer-paise money core | ✅ floats rejected at the boundary |
| 🧮 Fee / GST / TDS / net settlement engine | ✅ all rates configurable |
| 🔤 Normalization (dates, references, aliases, typos) | ✅ originals preserved |
| 🎯 Five deterministic matching layers | ✅ |
| 🔗 N:M aggregation and split settlements | ✅ |
| 💸 Refund netting and chargebacks | ✅ |
| 🚨 Honest exception list | ✅ no fabricated resolutions |
| 📖 Append-only audit trail | ✅ |
| 📈 Run metrics and run comparison | ✅ |
| 🧪 Synthetic generator, 19 labelled anomaly classes | ✅ |

### 🤖 Intelligence layer

| Area | Status |
|---|---|
| 🧭 Deterministic arbitrator | ✅ **the default** — no model, no network, no key |
| 🧠 LLM arbitrator (Anthropic / OpenAI) | ✅ implemented, optional, falls back safely |
| 🛡️ Verification gate | ✅ 12 adversarial tests |
| 🧾 Journal entries + trial balance | ✅ `PROPOSED → APPROVED → POSTED` |
| 🔧 Rule induction from evidence | ✅ |
| 📏 Rule validation by replay | ✅ regressions disqualifying |
| 🔐 Rule promotion (human gate) | ✅ requires evidence **and** a named actor |
| 📈 Cash forecasting | ✅ committed pipeline + backtested band |
| 💬 Finance copilot | ✅ grounded retrieval, 8 intents |

---

## 🖥️ The interface

An accounting terminal, not a chatbot. Dense tables, tabular figures, hairline
rules, one restrained amber accent.

| Page | Purpose |
|---|---|
| 📊 **Overview** | headline metrics, status distribution, largest unexplained value |
| 🔍 **Reconciliation** | dense working table; every row opens a full proof drawer |
| 🚨 **Exceptions** | the honest exception list, ranked by exposure |
| 📖 **Audit Trail** | chronological, filterable, expandable to exact arithmetic |
| 🧾 **Journal** | proposed corrections, approval workflow, trial balance |
| 🔧 **Rules** | the self-healing workflow with replay evidence |
| 💰 **Cash Position** | committed obligations vs a backtested forecast band |
| 💬 **Copilot** | grounded Q&A + arbitration console |

---

## 🗂️ Repository layout

```
backend/     FastAPI + deterministic engine + intelligence layer
frontend/    React · TypeScript · Vite · Tailwind · Recharts
data/        generated datasets (JSON, integer paise) + SQLite database
docs/        architecture · data-model · reconciliation-engine · auditability
             demo-data · arbitration · self-healing-rules
             forecasting-and-copilot · roadmap
```

## 🔌 API

<details>
<summary><b>27 endpoints</b> — click to expand</summary>

```http
# system & data
GET  /api/health                                  works with no AI configured
POST /api/data/generate                           deterministic synthetic data

# reconciliation
POST /api/reconciliation/run
GET  /api/reconciliation/runs
GET  /api/reconciliation/runs/{run_id}
GET  /api/reconciliation/runs/compare             baseline vs candidate deltas
GET  /api/reconciliation/records                  filter, search, paginate
GET  /api/reconciliation/records/{id}
GET  /api/reconciliation/records/{id}/explain     why was this matched?

# operations
GET  /api/exceptions                              ranked by exposure
GET  /api/audit                                   chronological, filterable
GET  /api/metrics

# arbitration
POST /api/arbitration/run
GET  /api/arbitration/results
GET  /api/arbitration/queue                       what an arbitrator would receive

# self-healing rules
GET  /api/rules
POST /api/rules/{id}/validate                     replay and measure
POST /api/rules/{id}/promote                      requires APPROVED + named actor
POST /api/rules/{id}/reject
POST /api/rules/{id}/retire

# accounting
GET  /api/journal
POST /api/journal/{id}/decide                     APPROVE | REJECT | POST
GET  /api/journal/trial-balance                   POSTED entries only
GET  /api/accounting/chart

# cash & copilot
GET  /api/cash-position                           committed only, no prediction
GET  /api/cash-position/forecast                  backtested band
POST /api/copilot/ask                             grounded retrieval
```

</details>

---

## 🔒 Design constraints held throughout

- 💰 Money is `int` paise everywhere. `rupees_to_paisa(1000.25)` raises `TypeError`.
- 📏 No metric is hardcoded. Match rate and throughput are measured per run.
- 🎚️ No confidence score is invented. Each value is a constant bound to a named rule.
- 🧾 No evidence is fabricated. Evidence points only at records that exist.
- 🗃️ Source data is never mutated; normalization adds a view and a trace.
- 🚨 A residual never leaves the engine without a reason code and evidence.
- 🙅 An unidentified bank credit is never attached to a plausible nearby order.
- 🤖 **The AI cannot choose an amount, name an account, or write a record.**
- ✍️ Every ledger or rule change is attributed to a named actor.
- 🔌 The whole system runs with `OPENAI_API_KEY` absent and no AI provider configured.

---

## 📚 Documentation

| Document | Contents |
|---|---|
| 🏗️ [architecture.md](docs/architecture.md) | pipeline, layering, module map, performance |
| 🗃️ [data-model.md](docs/data-model.md) | four sources, canonical model, variance vs exposure |
| ⚙️ [reconciliation-engine.md](docs/reconciliation-engine.md) | formulas, five layers, confidence, classification |
| 📖 [auditability.md](docs/auditability.md) | audit schema, reproducibility, "why was this matched?" |
| 🧪 [demo-data.md](docs/demo-data.md) | generator, 19 anomaly classes, measured results |
| 🤖 [arbitration.md](docs/arbitration.md) | the verification gate, journal entries, chart of accounts |
| 🔧 [self-healing-rules.md](docs/self-healing-rules.md) | induction, replay validation, promotion gates |
| 📈 [forecasting-and-copilot.md](docs/forecasting-and-copilot.md) | backtested forecasting, grounded Q&A |
| 🔭 [future-ai-layer.md](docs/future-ai-layer.md) | roadmap: shipped, deliberately absent, next |
| 🔒 [SECURITY.md](SECURITY.md) | threat model, AI containment, known gaps |

---

## 🎥 Product demo

<video src="assets/videos/ReconGuard_Demo.mp4" controls width="100%">
     <a href="assets/videos/ReconGuard_Demo.mp4">Watch the ReconGuard demo</a>
</video>


