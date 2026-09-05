"""Runtime configuration.

Every accounting parameter (fees, GST, TDS) and every reconciliation tolerance
is configurable here. Nothing financial is hardcoded at a call site.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw if raw not in (None, "") else default


@dataclass(frozen=True)
class AccountingConfig:
    """Deterministic accounting parameters, all in basis points (100 bps = 1%)."""

    gateway_fee_bps: int = 200      # 2.00%
    gst_on_fee_bps: int = 1800      # 18.00% levied on the gateway fee
    tds_bps: int = 10               # 0.10% on gross (s.194-O), configurable per merchant
    config_id: str = "ACC-CFG-001"

    def describe(self) -> dict:
        return {
            "config_id": self.config_id,
            "gateway_fee_pct": self.gateway_fee_bps / 100,
            "gst_on_fee_pct": self.gst_on_fee_bps / 100,
            "tds_pct": self.tds_bps / 100,
        }


@dataclass(frozen=True)
class ReconciliationConfig:
    """Tolerances used by the deterministic matching layers."""

    rounding_tolerance_paisa: int = 1          # Rs.0.01
    settlement_date_tolerance_days: int = 3    # Layer 3 date window
    expected_settlement_lag_days: int = 2      # T+2 payout cycle
    delayed_settlement_flag_days: int = 5      # beyond this we flag DELAYED_SETTLEMENT
    engine_version: str = "recon-engine/1.0.0"


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    app_name: str = "ReconGuard"
    system_version: str = "reconguard/0.1.0"
    api_prefix: str = "/api"
    database_url: str = field(
        default_factory=lambda: _env_str(
            "RECONGUARD_DATABASE_URL", f"sqlite:///{(DATA_DIR / 'reconguard.db').as_posix()}"
        )
    )
    ai_provider: str = field(default_factory=lambda: _env_str("RECONGUARD_AI_PROVIDER", "none"))
    llm_provider: str = field(default_factory=lambda: _env_str("LLM_PROVIDER", _env_str("RECONGUARD_AI_PROVIDER", "none")))
    llm_model: str = field(default_factory=lambda: _env_str("LLM_MODEL", ""))
    llm_api_key: str = field(default_factory=lambda: _env_str("LLM_API_KEY", ""))
    auto_resolve_threshold: float = field(default_factory=lambda: _env_float("AUTO_RESOLVE_THRESHOLD", 0.95))
    human_review_threshold: float = field(default_factory=lambda: _env_float("HUMAN_REVIEW_THRESHOLD", 0.70))
    accounting: AccountingConfig = field(default_factory=AccountingConfig)
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)

    @property
    def ai_enabled(self) -> bool:
        """The deterministic system NEVER depends on this being True."""
        return self.ai_provider not in ("", "none", "disabled") or self.llm_provider not in ("", "none", "disabled")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    accounting = AccountingConfig(
        gateway_fee_bps=_env_int("RECONGUARD_GATEWAY_FEE_BPS", 200),
        gst_on_fee_bps=_env_int("RECONGUARD_GST_ON_FEE_BPS", 1800),
        tds_bps=_env_int("RECONGUARD_TDS_BPS", 10),
    )
    recon = ReconciliationConfig(
        rounding_tolerance_paisa=_env_int("RECONGUARD_ROUNDING_TOLERANCE_PAISA", 1),
        settlement_date_tolerance_days=_env_int("RECONGUARD_SETTLEMENT_DATE_TOLERANCE_DAYS", 3),
        expected_settlement_lag_days=_env_int("RECONGUARD_EXPECTED_SETTLEMENT_LAG_DAYS", 2),
    )
    return Settings(
        accounting=accounting,
        reconciliation=recon,
        auto_resolve_threshold=_env_float("AUTO_RESOLVE_THRESHOLD", 0.95),
        human_review_threshold=_env_float("HUMAN_REVIEW_THRESHOLD", 0.70),
    )
