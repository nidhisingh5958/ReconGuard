# 🤖 Evidence-Grounded Finance Copilot — Architecture & Verification Gate

> **Core Axiom: LLM is strictly an interpretation and natural language generation layer. It is NEVER the source of financial truth.**

---

## 📌 Architectural Overview

ReconGuard's **Evidence-Grounded Finance Copilot** enables finance teams to query reconciliation runs, cash position, settlement variances, payroll risks, and rule self-healing using natural language.

```
                    ┌────────────────────────────┐
                    │      User Question         │
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │ 1. Deterministic Classifier │  (Keyword Rules)
                    └─────────────┬──────────────┘
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │ 2. Deterministic Handler    │  (SQL / Repository Query)
                    └─────────────┬──────────────┘
                                  │  Retrieved Facts & Evidence
                                  ▼
                    ┌────────────────────────────┐
                    │ 3. LLM Interpretation Layer │  (Formulates Natural Answer)
                    └─────────────┬──────────────┘
                                  │  Draft Answer + Citations
                                  ▼
                    ┌────────────────────────────┐
                    │ 4. Evidence Verification    │  (Grounding Verification Gate)
                    │           Gate             │
                    └─────────────┬──────────────┘
                                  │
                          Passed Verification
                                  │
                                  ▼
                    ┌────────────────────────────┐
                    │   Verified Copilot Answer  │
                    └────────────────────────────┘
```

---

## 🔒 16+ Supported Financial Intents

The copilot handles 16 specialized financial intents with 100% deterministic data retrieval:

| Intent Key | Description | Example Query |
|---|---|---|
| `PAYROLL_RISK` | Payroll coverage & insolvency risk | *"Will we meet payroll next Friday?"* |
| `SETTLEMENT_VARIANCE` | Sudden settlement dips or drops | *"Why did settlement dip on Tuesday?"* |
| `CASH_POSITION` | 13-week rolling cash position | *"What cash is at risk in our forecast?"* |
| `DELAYED_SETTLEMENTS` | In-flight or lagging gateway payouts | *"Which settlements are delayed beyond 3 days?"* |
| `REFUND_EXPOSURE` | Net settlement refund adjustments | *"Show refund exposure across gateways"* |
| `CHARGEBACK_EXPOSURE` | Disputes and reversal reserves | *"What chargeback disputes exist?"* |
| `RULE_IMPACT` | Self-healing rule efficiency & lift | *"What is the impact of promoted rule R-001?"* |
| `RUN_COMPARISON` | Variance between two reconciliation runs | *"What changed since the baseline run?"* |
| `JOURNAL` | Double-entry posting verification | *"Show accounting journal entries for run R-12"* |
| `ARBITRATION` | AI residual queue proposals | *"What proposals are in the arbitration queue?"* |
| `COUNTERPARTY` | Merchant/customer volume breakdown | *"Which counterparty has the largest variance?"* |
| `UNEXPLAINED` | Unresolved financial exposure | *"Explain unexplained settlement value"* |
| `EXCEPTIONS` | Top un-reconciled exceptions | *"What are the biggest exception records?"* |
| `REASON` | Breakdown of anomaly reason codes | *"Why are settlements failing reconciliation?"* |
| `METRICS` | Match rate and throughput metrics | *"What was the match rate for run R-10?"* |
| `EXPLAIN` | Detailed single-record audit trace | *"Why was transaction REC-00001 matched?"* |

---

## 🛡️ Evidence Verification Gate

Before any answer is returned to the UI or API caller, it passes through the **`EvidenceVerifier`**:

1. **Record ID Existence**: Verifies that every cited record ID (e.g. `REC-00012`, `SET-10291`) exists in the underlying database run.
2. **Monetary Figure Grounding**: Checks that monetary amounts mentioned in the text match integer-paise query results within 0.1% tolerance.
3. **Rejection Safeguard**: If any hallucinated ID or invalid figure is detected, the gate rejects the draft answer and falls back to a purely deterministic fact table response.

---

## 🔌 API Endpoint

### `POST /api/copilot/ask`
Submits a question to the copilot and returns a structured, verified `CopilotAnswer`.

```json
{
  "question": "Will we meet payroll next Friday?",
  "run_id": "RUN-20260905-001"
}
```

**Response**:
```json
{
  "question": "Will we meet payroll next Friday?",
  "intent": "PAYROLL_RISK",
  "answer": "Yes. Confirmed cash reserves of ₹82.00L cover next Friday's payroll requirement of ₹15.00L by 5.46x.",
  "why": "Confirmed bank receipts and T+1 expected gateway payouts provide ₹1.27Cr net liquidity against ₹15.00L obligations.",
  "financial_impact": "Zero payroll shortfall detected for Week 1.",
  "risk": "LOW (Payroll Risk Score: 15/100).",
  "evidence": [
    "Confirmed Cash: ₹82,00,000",
    "Expected Inflow: ₹45,00,000",
    "Weekly Payroll Obligation: ₹15,00,000"
  ],
  "recommended_action": "Maintain liquid reserves in primary settlement account.",
  "citations": [
    { "record_id": "REC-00001", "type": "record", "label": "Settlement SET-1002" }
  ],
  "confidence": 1.0,
  "confidence_method": "DETERMINISTIC_GARD_VERIFIED",
  "grounded": true
}
```
