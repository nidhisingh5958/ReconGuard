# 📈 Forecasting & copilot

> **An obligation and a guess must never look the same on a screen.**

Nav: [Architecture](architecture.md) · [Data model](data-model.md) · [Engine](reconciliation-engine.md) · [Auditability](auditability.md) · [Demo data](demo-data.md) · [Arbitration](arbitration.md) · [Self-healing rules](self-healing-rules.md) · **Forecasting & copilot** · [Future AI layer](future-ai-layer.md)

---

# 💰 Part 1 — Cash forecasting

Two things are reported and they are kept rigorously apart.

## 🧾 Committed pipeline — *not* a forecast

Each line is a settlement whose arithmetic the engine **proved** and whose credit
has not been located. The amount is exact and the evidence is a real settlement
id. Only the *timing* is projected, from the configured `T+n` payout cycle.

```
Committed line
  amount        exact, from the proved settlement          ← fact
  evidence      SET-10291                                  ← fact
  landing date  value_date + expected_settlement_lag_days   ← projection
```

## 📊 Projected inflow — a forecast, stated as a band

The band is the **p10–p90** range of observed daily inflow.

> **Why deciles, not quartiles.** An interquartile band covers only about half
> the distribution by construction. A band you fall outside of every other day
> tells a treasurer nothing. p10–p90 targets roughly 80% coverage — and then the
> backtest reports whether that was actually achieved.

## 🎯 Confidence is backtested, not asserted

This is the part worth reading. The confidence attached to the band is **not a
number somebody chose**:

```
observed history  ────────────────────────────────────────────
                  │◀────── train (70%) ──────▶│◀── held out ──▶│
                            fit p10/p90              score it

confidence = fraction of held-out days that landed inside the band
```

So a low confidence here is *informative*. If the history is too short or too
erratic for the method to work, the number says so:

| Situation | Reported |
|---|---|
| Steady inflow, 90 days | `coverage 100%`, usable |
| Bounded but variable | `coverage ~93%`, usable |
| Regime change mid-series | `coverage 0%` — the method genuinely does not work here |
| Fewer than 8 days | `usable: false`, *"at least 8 are needed before a projection can be scored"* — only the committed pipeline is projected |

`test_an_erratic_series_produces_an_honestly_low_coverage` asserts the third row.
A forecasting module that cannot report its own failure is worse than none.

## 🔌 API

```http
GET /api/cash-position              committed position only, includes_prediction: false
GET /api/cash-position/forecast     ?run_id=&horizon_days=30
```

```jsonc
{
  "method": "EMPIRICAL_DAILY_DECILE_BAND",
  "committed_total_paisa": 4840714,   // exact
  "projected_total_paisa": 251096440, // banded
  "backtest": {
    "train_days": 63, "test_days": 28, "hits": 26,
    "coverage": 0.93,
    "note": "band fitted on 63 days, scored on 28 held-out days; 26 of 28 landed inside the band"
  },
  "points": [ { "value_date": "…", "low_paisa": …, "expected_inflow_paisa": …, "high_paisa": …, "committed_paisa": … } ]
}
```

The UI draws committed lines **solid** and the projected band **shaded**, with
the backtested coverage shown as a metric next to it rather than implied.

---

# 🧭 Part 2 — Finance copilot

## 📚 Grounded retrieval, no generation

**There is no language model in this module.** Intent routing is keyword rules
and every answer is assembled from retrieved records, which is why each response
reports `generated_by: "deterministic-retrieval"`.

That is a deliberate stopping point, not a missing piece. The hard part of a
finance copilot is being unable to state a wrong number, and retrieval gives
that for free.

> Figures come from the same repositories the dashboard reads, so an answer here
> and a number on the Overview page **cannot disagree**.
> `test_copilot_agrees_with_the_metrics_endpoint` asserts exactly that.

## 🗂️ Intents

| Intent | Example | Answers with |
|---|---|---|
| `EXPLAIN_RECORD` | *"Why was REC-00001 matched?"* | full derivation, evidence, audit events |
| `TOP_EXCEPTIONS` | *"What are the biggest exceptions?"* | ranked by exposure |
| `RUN_METRICS` | *"What is the match rate?"* | measured run metrics |
| `UNEXPLAINED_VALUE` | *"How much is unexplained?"* | at-stake vs unexplained split |
| `COUNTERPARTY_POSITION` | *"Which customer has the most at stake?"* | per-counterparty totals |
| `REASON_CODE_BREAKDOWN` | *"Give me the reason code breakdown"* | distribution |
| `ARBITRATION_STATUS` | *"What did the arbitrator propose?"* | decisions, rejections |
| `PROPOSED_JOURNALS` | *"What journal entries are pending?"* | by status, totals |
| `UNKNOWN` | *"What is the weather in Mumbai?"* | an honest decline |

### Routing order matters

`COUNTERPARTY_POSITION` is checked **before** the value intents, because
*"which customer has the most **at stake**"* is a counterparty question that
happens to contain a value word. This was a real bug caught in testing.

## 🙅 Declining is a correct answer

```
Q: What will our revenue be next year?

[UNKNOWN] I answer only from what this run actually proved, and I could not map
that question onto a stored fact. Rather than guess, here is what I can answer
precisely.
  • Explain a record      Why was REC-00001 matched?
  • Exceptions            What are the biggest exceptions?
  • Metrics               What is the match rate for this run?
  …
```

An honest decline still offers what it *can* answer.

## 🔌 API

```http
POST /api/copilot/ask    { question, run_id? }
```

```jsonc
{
  "intent": "RUN_METRICS",
  "answer": "Run RUN-00002 processed 504 reconciliation records from 1,989 source rows in 53 ms (9,591 records/sec). 469 matched deterministically, a match rate of 93.06%, leaving 29 residuals.",
  "facts": [ { "label": "Records processed", "value": "504" }, … ],
  "grounded": true,
  "generated_by": "deterministic-retrieval",
  "followups": ["What are the biggest exceptions?", …]
}
```

## 🔮 Where a language layer would go

**After** `answer_question()`, never instead of it — handed the retrieved facts
and forbidden from adding to them. The worst it could then do is make a correct
answer read more fluently.

---

**Back:** [🔧 Self-healing rules](self-healing-rules.md) · **Next:** [🔭 Future AI layer](future-ai-layer.md) · **Up:** [📘 README](../README.md)
