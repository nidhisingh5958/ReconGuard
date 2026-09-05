"""Chart of accounts.

Small on purpose. These are the accounts a payments reconciliation actually
touches, and every proposed journal entry must name two of them. An arbitrator
cannot invent an account: :func:`resolve` rejects anything not in this table,
which is one of the gates that stops a model from writing arbitrary bookkeeping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


@dataclass(frozen=True, slots=True)
class Account:
    code: str
    name: str
    account_type: AccountType
    description: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "code": self.code,
            "name": self.name,
            "account_type": self.account_type.value,
            "description": self.description,
        }


#: Debit increases an ASSET or EXPENSE; credit increases a LIABILITY or INCOME.
DEBIT_POSITIVE = (AccountType.ASSET, AccountType.EXPENSE)

BANK = "1000"
SETTLEMENT_RECEIVABLE = "1100"
SUSPENSE = "1200"
ACCOUNTS_RECEIVABLE = "1300"
GST_INPUT_CREDIT = "1400"
TDS_RECEIVABLE = "1500"
MERCHANT_PAYABLE = "2000"
REVENUE = "4000"
GATEWAY_FEE_EXPENSE = "5000"
CHARGEBACK_LOSS = "5300"
REFUND_CONTRA_REVENUE = "5400"
RECONCILIATION_VARIANCE = "9000"

ACCOUNTS: Dict[str, Account] = {
    a.code: a
    for a in (
        Account(BANK, "Bank Account", AccountType.ASSET,
                "Cash actually confirmed on the bank statement."),
        Account(SETTLEMENT_RECEIVABLE, "Settlement Receivable", AccountType.ASSET,
                "Payouts the gateway owes but has not yet remitted."),
        Account(SUSPENSE, "Suspense Account", AccountType.ASSET,
                "Cash received that cannot yet be attributed to an order."),
        Account(ACCOUNTS_RECEIVABLE, "Accounts Receivable", AccountType.ASSET,
                "Customer obligations captured at the gateway."),
        Account(GST_INPUT_CREDIT, "GST Input Credit", AccountType.ASSET,
                "Recoverable GST charged on gateway fees."),
        Account(TDS_RECEIVABLE, "TDS Receivable", AccountType.ASSET,
                "Tax withheld at source, recoverable against liability."),
        Account(MERCHANT_PAYABLE, "Merchant Payable", AccountType.LIABILITY,
                "Amounts potentially repayable, including duplicate receipts."),
        Account(REVENUE, "Revenue", AccountType.INCOME,
                "Recognised sales value."),
        Account(GATEWAY_FEE_EXPENSE, "Gateway Fee Expense", AccountType.EXPENSE,
                "Payment processing fees."),
        Account(CHARGEBACK_LOSS, "Chargeback Loss", AccountType.EXPENSE,
                "Settled payouts subsequently reversed."),
        Account(REFUND_CONTRA_REVENUE, "Refunds", AccountType.EXPENSE,
                "Refunds issued against recognised revenue."),
        Account(RECONCILIATION_VARIANCE, "Reconciliation Variance", AccountType.EXPENSE,
                "Quantified, attributed differences pending a human decision."),
    )
}


def resolve(code: str) -> Optional[Account]:
    """Look up an account. Returns None for anything not in the chart."""
    return ACCOUNTS.get(str(code).strip())


def is_known(code: str) -> bool:
    return str(code).strip() in ACCOUNTS


def all_accounts() -> list:
    return [ACCOUNTS[code].to_dict() for code in sorted(ACCOUNTS)]
