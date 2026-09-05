# ReconGuard — handoff

**Status: both phases complete and verified.** Nothing from the previous
handoff is outstanding.

Start with [`README.md`](README.md), then [`docs/architecture.md`](docs/architecture.md).

---

## ✅ Verified state

| | Result |
|---|---|
| Backend tests | **180 passing** |
| Frontend tests | **18 passing** |
| TypeScript | clean (`tsc -b --noEmit`) |
| Production build | clean |
| Doc links | no broken links across 9 docs + 3 root files |
| UI pages | all 8 render, zero console errors |
| Cold-start loop | verified end to end over HTTP |

### Measured — seed dataset, 500 orders, seed 42

```
BEFORE self-healing   463/510 matched · 90.78% · 35 residuals
  arbitration          47 examined · 47 accepted · 0 rejected
                       RESOLVE 12 · PROBABLE 35 · 47 journal entries
                       RULE-DYN-001 induced: PGWX\s+99(\d{5}) from 6 pairings
  validation           IMPROVES · 463→469 (+6) · 0 regressions · +2.27pp
  promotion            APPROVED → ACTIVE (nidhi@finance)
AFTER self-healing    469/504 matched · 93.06% · 29 residuals
                      −₹61,592.62 unexplained

Ground truth          102 expected / 102 detected · 100% precision / 100% recall
Clean-mode control    100.00% match rate, 0 residuals
Throughput            ~9,700 records/sec
```

---

## 🗺️ What exists

### Phase 1 — deterministic engine
Money core (integer paise), accounting invariants, five matching layers, N:M
aggregation, refund netting, honest exceptions, append-only audit trail, run
metrics and comparison, 19-class synthetic generator.

### Phase 2 — intelligence layer

| Module | File |
|---|---|
| Chart of accounts (12) | `app/services/accounting/chart_of_accounts.py` |
| Journal building + verification | `app/services/accounting/journal.py` |
| Approve / reject / post + trial balance | `app/services/accounting/posting.py` |
| Candidate retrieval | `app/services/ai/candidates.py` |
| Arbitrator interfaces + degradation ladder | `app/services/ai/interfaces.py` |
| **Deterministic arbitrator (default)** | `app/services/ai/deterministic_arbitrator.py` |
| LLM arbitrator (Anthropic / OpenAI) | `app/services/ai/llm_arbitrator.py` |
| Provider adapters + `ScriptedProvider` | `app/services/ai/providers.py` |
| **The verification gate** | `app/services/ai/verification.py` |
| Orchestration + rule induction | `app/services/ai/arbitration_service.py` |
| Grounded copilot (8 intents) | `app/services/ai/copilot_qa.py` |
| Dynamic rules + safety validation | `app/services/rules/dynamic.py` |
| Pattern induction | `app/services/rules/proposal.py` |
| Replay validation | `app/services/rules/validator.py` |
| Lifecycle + promotion gates | `app/services/rules/registry.py` |
| Backtested forecasting | `app/services/forecasting/forecaster.py` |
| 12 new endpoints | `app/api/routes/intelligence_routes.py` |

UI: `Journal.tsx`, `Rules.tsx`, `CashPosition.tsx`, `Copilot.tsx` — all routed
and reachable; the `PREVIEW` "next" badge set in `Layout.tsx` is now empty.

---

## 🧠 Design decisions worth not re-litigating

- **The deterministic arbitrator is the default, not a placeholder.** Most
  residuals need bookkeeping policy, not judgement.
- **The amount is always the engine's.** A model may pick which policy applies;
  it never supplies a number.
- **Model confidence is capped at 0.90.** `1.00` means an identifier matched or
  an invariant closed.
- **Rule validation is automatic; promotion is not.** Measuring is safe;
  changing what the engine matches is not.
- **A dynamic rule can only ADD matches.** It runs only where no built-in key
  resolves.
- **Regressions are disqualifying**, not subtracted. A rule that fixes six and
  breaks one is not a good trade.
- **Forecast band is p10–p90, not IQR**, and its confidence is backtested on
  held-out history.
- **No language model in the copilot.** Retrieval already guarantees the answer
  cannot be wrong.

---

## ⚠️ Gotchas

1. **The `UNRECOGNISED_REFERENCE_FORMAT` narration is load-bearing.**
   `ACH CR//PGWX/99{key}/MERCHANT ACCT` defeats both built-in paths on purpose.
   If you change `UNRECOGNISED_REFERENCE_TEMPLATE`, verify it still does — a
   marker containing `RZP` would be caught by the amount+date fallback and the
   self-healing demo would silently stop having a gap to close.

2. **Large heredocs through the Bash tool truncate silently** and fail with
   `unexpected EOF while looking for matching quote`. Anything over ~6–8 KB
   should be written with the Write tool. This bit three times.

3. **Demo reset.** If the DB already holds a promoted `RULE-DYN-001`, delete
   `data/reconguard.db*` to see the before/after contrast again.

4. **Journals and arbitration are per-run.** After a new reconciliation run,
   re-run arbitration for that run or its Journal page will be empty.

5. **`npx playwright install chromium`** is needed before screenshots;
   playwright itself is intentionally not in `package.json`.

---

## 🚀 Run it

```bash
cd backend  && uv run uvicorn app.main:app --reload   # :8000, docs at /docs
cd frontend && npm run dev                               # :5173
```

Verify:

```bash
cd backend  && uv run pytest && uv run python -m scripts.benchmark
cd frontend && npm test && npx tsc -b --noEmit && npm run build
```

Self-healing demo: see [`docs/self-healing-rules.md`](docs/self-healing-rules.md#-api).

---

## 🔭 Next phase

See [`docs/future-ai-layer.md`](docs/future-ai-layer.md) for what is shipped,
what is deliberately absent, and what a next phase would need. The security gaps
that must close before real financial data are listed in
[`SECURITY.md`](SECURITY.md#-known-gaps) — the headline one is that there is no
authentication, so the `actor` field gives attribution, not identity.
