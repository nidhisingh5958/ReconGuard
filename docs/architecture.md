# Architecture

Nav: **Architecture** · [Data model](data-model.md) · [Reconciliation engine](reconciliation-engine.md) · [Auditability](auditability.md) · [Demo data](demo-data.md) · [Arbitration](arbitration.md) · [Self-healing rules](self-healing-rules.md) · [Forecasting & copilot](forecasting-and-copilot.md) · [Cash Resilience](cash-resilience.md) · [Finance Copilot](finance-copilot.md) · [Future AI layer](future-ai-layer.md)

---

## The governing principle

> Never use an LLM for something that can be deterministically calculated or verified.

ReconGuard is a deterministic financial control engine. An AI arbitrator sits on top receiving only residual anomalies. Financial forecasts use empirical P10/P50/P90 decile bands and deterministic payroll risk calculations. The Finance Copilot enforces an evidence verification gate so that LLMs act purely as an interpretation layer.

## Pipeline

```
DATA SOURCES          orders.json · settlements.json · bank_statement.json · invoices.json
        |
    INGESTION         app/services/ingestion/     typed records, units made explicit
        |
  NORMALIZATION       app/services/normalization/ canonical view, originals preserved
        |
 DETERMINISTIC        app/services/accounting/    fee, GST, TDS, net settlement
 FINANCIAL ENGINE                                 integer paise, ROUND_HALF_UP
        |
 RECONCILIATION       app/services/reconciliation/ five ordered matching layers
 ENGINE
        |
   MATCHED / PARTIAL / REVIEW / DUPLICATE / EXCEPTION / UNRESOLVED
        |
   AUDIT LEDGER       app/services/audit/         append-only, every decision
        |
  METRICS + UI        app/services/metrics/ · frontend/
```

Integrated Residual AI Arbitrator, Self-Healing Rule Promotion, Cash Resilience & Copilot:

```
RESIDUALS  ──▶  AI ARBITRATOR  ──▶  PATTERN INDUCTION  ──▶  SAFE DSL RULE CANDIDATE
                                                                      │
RECONCILIATION ENGINE  ◀──  HUMAN APPROVAL GATE  ◀──  REPLAY BACKTESTING & METRICS
        │
        ├──▶ CASH RESILIENCE CONTROLLER ──▶ 13-Week Decile Bands & Payroll Risk Alert
        │
        └──▶ FINANCE COPILOT ────────────▶ Grounded Retrieval & Evidence Verification Gate
```

## Layering, and what each layer may depend on

| Layer | Location | May import | Purpose |
|---|---|---|---|
| Core | `app/core/` | nothing app-level | money arithmetic, config, ids, versions |
| Domain | `app/domain/` | core | pure dataclasses, enums. No I/O, no ORM |
| Services | `app/services/` | core, domain | all business logic |
| Repositories | `app/repositories/` | domain, models | persistence and queries |
| API | `app/api/` | everything | HTTP boundary only |

The rule that makes this useful: **the reconciliation engine imports no
database, no HTTP framework and no AI client.** `ReconciliationEngine.run()`
takes a `SourceDataset` of plain dataclasses and returns a
`ReconciliationOutput` of plain dataclasses. That is what lets the engine be
unit-tested in milliseconds and benchmarked without a server running, and it is
why `tests/test_matching.py` can assert a financial outcome without any
fixtures beyond three objects.

## Backend module map

```
backend/app/
  core/          money.py (integer paise), config.py (all rates), ids.py, versioning.py
  domain/        enums.py, sources.py, canonical.py, reconciliation.py, audit.py, ai.py, rules.py
  models/        SQLAlchemy entities (BigInteger paise, JSON evidence snapshots)
  schemas/       Pydantic API contracts
  repositories/  persistence + queries, exposure ranking
  db/            engine/session, schema creation, rule catalogue seeding
  services/
    ingestion/     generator.py (18 labelled anomaly classes), loader.py
    normalization/ text.py, dates.py, references.py, normalizer.py
    accounting/    fees.py, invariants.py
    reconciliation/
      engine.py        orchestrates the run
      indexes.py       every lookup, built once, O(n)
      confidence.py    fixed values bound to named rules
      classification.py status decision
      layers/          identifiers · bank_matching · aggregation · netting
    audit/         ledger.py (append-only)
    metrics/       calculator.py (all formulas)
    forecasting/   interfaces.py (committed position now, prediction later)
    ai/            interfaces.py, llm_arbitrator.py (stub), copilot.py (grounded retrieval)
  api/routes/    core_routes · record_routes · ops_routes
```

## Data flow for one run

1. `runner.execute_run` loads a dataset from disk into typed records.
2. `build_index` makes one pass over every source, producing the payment,
   settlement, bank-key, prefix, amount and invoice indexes.
3. `resolve_netting` turns every refund adjustment and chargeback debit into an
   `AdjustmentRecord` with evidence, before any matching happens.
4. Orders are processed in sorted id order. Each one runs the five layers and
   produces exactly one `ReconciliationResult`.
5. Bank credits nobody claimed are swept into their own exception records.
6. `compute_run_metrics` measures the run.
7. `save_run` persists run, records and audit events in one transaction.

Sorted iteration is not cosmetic: bank credits are claimed at most once, so a
non-deterministic iteration order would make the assignment of an ambiguous
credit vary between runs.

## Technology and why

| Choice | Reason |
|---|---|
| Python + FastAPI + Pydantic | the engine is arithmetic and rules; typed contracts at the boundary |
| SQLAlchemy 2.0 | portable schema; SQLite for zero-config, PostgreSQL for production |
| SQLite default | the whole system must run end-to-end with nothing installed |
| React + TypeScript + Vite | typed API contracts mirrored on the client |
| Tailwind | the UI is dense and tabular; utility classes keep the hairline system consistent |
| Recharts | one time-series chart; everything else is a table, because tables are what finance operators read |

### PostgreSQL

The schema uses only portable column types (`BigInteger`, `JSON`, `String`,
`DateTime`). To run on PostgreSQL, set one variable and change nothing else:

```
RECONGUARD_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/reconguard
```

## Performance

Matching is index-driven; there is no nested scan over a second collection.
Measured on the seed dataset:

| Orders | Reconciliation records | Source rows | Time | Throughput |
|---:|---:|---:|---:|---:|
| 500 | 504 | 1,989 | 58 ms | ~8,600/s |
| 1,000 | 1,008 | 3,978 | 114 ms | ~8,900/s |
| 10,000 | 10,080 | 39,780 | 1,498 ms | ~6,700/s |

20× the records costs ~26× the time. Quadratic matching would have cost ~400×.
`tests/test_ground_truth.py::test_engine_scales_without_quadratic_blowup`
asserts this bound so a future change cannot silently reintroduce an O(n²) scan.

The N:M matching algorithm is isolated in
`services/reconciliation/layers/aggregation.py` so it can be optimised or
replaced independently of classification and accounting.

---

**Next:** [🗃️ Data model](data-model.md) · **Up:** [📘 README](../README.md)
