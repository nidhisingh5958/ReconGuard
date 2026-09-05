#!/usr/bin/env python3
"""Evaluation CLI script for Residual AI Arbitrator."""

import argparse
import sys
from pathlib import Path

# Ensure backend root is on sys.path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import SessionLocal
from app.services.ai.evaluation import evaluate_run_arbitration


def main():
    parser = argparse.ArgumentParser(description="Evaluate Residual AI Arbitrator against Ground Truth")
    parser.add_argument("--run-id", type=str, required=True, help="Reconciliation Run ID to evaluate")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        metrics = evaluate_run_arbitration(session, args.run_id)
        d = metrics.to_dict()
        print("=" * 60)
        print(f"RESIDUAL AI ARBITRATOR EVALUATION (Run: {d['run_id']})")
        print(f"Arbitrator:              {d['arbitrator']}")
        print(f"Total Residuals:         {d['total_residuals']}")
        print(f"AI Resolutions:          {d['ai_resolutions']}")
        print(f"  - Correct:             {d['correct_resolutions']}")
        print(f"  - Incorrect:           {d['incorrect_resolutions']}")
        print("-" * 60)
        print(f"Precision:               {d['precision'] * 100:.1f}%")
        print(f"Recall:                  {d['recall'] * 100:.1f}%")
        print(f"F1 Score:                {d['f1_score'] * 100:.1f}%")
        print(f"False Positive Rate:     {d['false_positive_rate'] * 100:.1f}%")
        print(f"False Negative Rate:     {d['false_negative_rate'] * 100:.1f}%")
        print("=" * 60)
    finally:
        session.close()


if __name__ == "__main__":
    main()
