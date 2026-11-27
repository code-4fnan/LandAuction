"""Settings read from environment variables or Streamlit secrets.

Lookup order for every setting: environment variable -> ``.streamlit/secrets.toml``
(or the Secrets box on Streamlit Community Cloud) -> built-in default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "landauction.db"


def _setting(name: str, default: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    try:  # Streamlit is optional here so tests and scripts can import config.
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets file, or not running under Streamlit
        pass
    return default


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    timezone: str
    currency_symbol: str
    seed_demo_data: bool
    anti_snipe_seconds: int
    max_auction_days: int
    refresh_seconds: int


def load_settings() -> Settings:
    return Settings(
        database_url=_setting("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"),
        timezone=_setting("APP_TIMEZONE", "Asia/Kolkata"),
        currency_symbol=_setting("CURRENCY_SYMBOL", "₹"),
        seed_demo_data=_bool(_setting("SEED_DEMO_DATA", "true")),
        anti_snipe_seconds=int(_setting("ANTI_SNIPE_SECONDS", "120")),
        max_auction_days=int(_setting("MAX_AUCTION_DAYS", "60")),
        refresh_seconds=int(_setting("REFRESH_SECONDS", "3")),
    )


settings = load_settings()
