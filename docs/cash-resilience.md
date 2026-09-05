# 🛡️ Cash Resilience Controller — 13-Week Forecast & Payroll Safeguard

> **Financial Resilience = Deterministic Proven Pipeline + Empirical Decile Bands (P10/P50/P90) + Payroll Coverage Analysis + Actionable Interventions.**

---

## 📌 Executive Summary

ReconGuard's **Cash Resilience Controller** transforms reconciled multi-source financial datasets into a **13-week rolling cash flow projection**. Built upon integer-paise accounting arithmetic, it evaluates future liquidity, detects upcoming payroll stress, and suggests actionable operational interventions separating deterministic facts from AI recommendations.

---

## 🏗️ Core Architecture & Decile Bands

### 1. Integer Paisa Arithmetic
All monetary values in the Cash Resilience Controller are stored, computed, and aggregated as integer paise (`int`), completely eliminating floating-point rounding errors.

### 2. Four Cash Categories
1. **`CONFIRMED`** (Proven): Settled bank credits and verified payments with proved reconciliation trails.
2. **`EXPECTED`** (Projected Inflow): Unmatched orders or in-flight settlements expected to land within their standard `T+n` SLA window.
3. **`AT_RISK`** (Unreconciled / Exception): Delayed payouts, open exception records, or fee variances that may stall liquidity.
4. **`UNRESOLVED`** (Pending Arbitration): Residual items requiring human or AI arbitrator review before settlement.

### 3. P10 / P50 / P90 Decile Bands
The 13-week forecast models revenue volatility using empirical daily inflow distributions:
* **P10 (Conservative / Downside)**: Lower 10th percentile daily inflow estimate.
* **P50 (Base / Expected)**: 50th percentile median expected daily inflow.
* **P90 (Optimistic / Upside)**: 90th percentile upper inflow estimate.

---

## 💼 Deterministic Payroll Risk Analysis

Payroll stress is evaluated deterministically by comparing total confirmed + expected liquidity against scheduled payroll obligations.

```python
Net Liquidity = Confirmed Cash + Expected Inflow - Pending Obligations
Payroll Buffer = Net Liquidity - Payroll Requirement
```

* **Payroll Risk Score**: Integer scale `0` (Zero Risk / Well Funded) to `100` (Critical Insolvency Risk).
* **Deficit Week**: Identifies the exact upcoming week (e.g. Week 4) where projected cash balance drops below required payroll obligations.

---

## 🎯 Operational Interventions

Interventions provide structured recommendations for finance teams, cleanly categorizing output into **FACT** and **RECOMMENDATION**:

* **Fact**: "Payroll requirement of ₹15,00,000 due on Week 4. Confirmed cash reserves: ₹8,20,000."
* **Recommendation**: "Accelerate settlement collection for ₹4,50,000 delayed payouts or request short-term credit facility of ₹2,30,000 prior to Week 3."

---

## 🔌 API Reference

### `GET /api/cash-position/resilience`
Returns 13-week forecast points, payroll risk metrics, risk indicators, and operational interventions.

```json
{
  "horizon_weeks": 13,
  "start_date": "2026-09-07",
  "confirmed_cash_paisa": 82000000,
  "expected_cash_paisa": 45000000,
  "at_risk_cash_paisa": 12000000,
  "unresolved_cash_paisa": 3000000,
  "p10_total_paisa": 110000000,
  "p50_total_paisa": 127000000,
  "p90_total_paisa": 145000000,
  "payroll_analysis": {
    "weekly_payroll_requirement_paisa": 15000000,
    "payroll_risk_score": 15,
    "payroll_risk_level": "LOW",
    "payroll_deficit_week": null,
    "can_meet_payroll": true
  },
  "interventions": [
    {
      "priority": "HIGH",
      "category": "PAYROLL_PROTECTION",
      "fact": "Payroll of ₹15.00L is fully covered by Week 1 confirmed reserves of ₹82.00L.",
      "recommendation": "Maintain minimum liquid cash buffer of ₹20.00L in primary bank account."
    }
  ]
}
```
