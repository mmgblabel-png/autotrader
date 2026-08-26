"""Application configuration loaded from environment variables.

The runtime intentionally keeps secrets in the environment. Public campaign facts can be
stored in YAML, but control tokens and model API keys must never be committed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PRODUCT_URL = (
    "https://www.paypro.nl/producten/WegMetDieKilos_Bronze_Plan/114766/183297"
)


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def _float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, float(raw))
    except ValueError:
        return default


def _csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(value.strip() for value in raw.split(",") if value.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    app_env: str
    data_dir: Path
    database_path: Path
    campaign_config_path: Path
    public_base_url: str
    paypro_product_url: str
    paypro_affiliate_id: str
    paypro_affiliate_url_template: str
    affiliate_disclosure: str
    control_token: str
    webhook_token: str
    cors_origins: tuple[str, ...]
    llm_provider: str
    llm_model: str
    llm_fallback_model: str
    llm_max_output_tokens: int
    llm_timeout_seconds: float
    llm_max_requests_per_run: int
    llm_max_requests_per_hour: int
    llm_max_requests_per_day: int
    heartbeat_enabled: bool
    heartbeat_interval_seconds: float
    auto_run_due_campaigns: bool
    draft_only: bool
    website_enabled: bool
    log_level: str

    @property
    def production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @property
    def llm_available(self) -> bool:
        if self.llm_provider == "deterministic":
            return False
        return bool(os.getenv("OPENAI_API_KEY"))

    def validate(self) -> None:
        for name, value in {
            "PAYPRO_PRODUCT_URL": self.paypro_product_url,
            "PUBLIC_BASE_URL": self.public_base_url,
        }.items():
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"{name} must be an absolute HTTP(S) URL")
        allowed_placeholders = ("{product_url}", "{affiliate_id}")
        if not any(value in self.paypro_affiliate_url_template for value in allowed_placeholders):
            raise ValueError(
                "PAYPRO_AFFILIATE_URL_TEMPLATE must contain {product_url} or {affiliate_id}"
            )
        if self.production and not self.control_token:
            raise ValueError("CONTROL_TOKEN is required in production")
        if self.production and not self.webhook_token:
            raise ValueError("WEBHOOK_TOKEN is required in production")
        if self.production and self.public_base_url.startswith("http://"):
            raise ValueError("PUBLIC_BASE_URL must use HTTPS in production")


def load_settings() -> Settings:
    data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser().resolve()
    database_default = data_dir / "campaign_automaton.db"
    settings = Settings(
        app_name=os.getenv("APP_NAME", "WegMetDieKilos Campaign Automaton"),
        app_env=os.getenv("APP_ENV", "development"),
        data_dir=data_dir,
        database_path=Path(os.getenv("DATABASE_PATH", str(database_default)))
        .expanduser()
        .resolve(),
        campaign_config_path=Path(
            os.getenv("CAMPAIGN_CONFIG_PATH", "config/campaign.yaml")
        )
        .expanduser()
        .resolve(),
        public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
        paypro_product_url=os.getenv("PAYPRO_PRODUCT_URL", DEFAULT_PRODUCT_URL),
        paypro_affiliate_id=os.getenv("PAYPRO_AFFILIATE_ID", "").strip(),
        paypro_affiliate_url_template=os.getenv(
            "PAYPRO_AFFILIATE_URL_TEMPLATE", "{product_url}"
        ),
        affiliate_disclosure=os.getenv(
            "AFFILIATE_DISCLOSURE",
            "Affiliate disclosure: als je via deze link bestelt, kan ik een commissie ontvangen. "
            "Jij betaalt hiervoor niet extra.",
        ),
        control_token=os.getenv("CONTROL_TOKEN", ""),
        webhook_token=os.getenv("WEBHOOK_TOKEN", ""),
        cors_origins=_csv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000"),
        llm_provider=os.getenv("LLM_PROVIDER", "auto").strip().lower(),
        llm_model=os.getenv("LLM_MODEL", "gpt-5-mini").strip(),
        llm_fallback_model=os.getenv("LLM_FALLBACK_MODEL", "gpt-5-nano").strip(),
        llm_max_output_tokens=_int("LLM_MAX_OUTPUT_TOKENS", 3500, 256),
        llm_timeout_seconds=_float("LLM_TIMEOUT_SECONDS", 90.0, 5.0),
        llm_max_requests_per_run=_int("LLM_MAX_REQUESTS_PER_RUN", 6, 1),
        llm_max_requests_per_hour=_int("LLM_MAX_REQUESTS_PER_HOUR", 30, 1),
        llm_max_requests_per_day=_int("LLM_MAX_REQUESTS_PER_DAY", 150, 1),
        heartbeat_enabled=_bool("HEARTBEAT_ENABLED", True),
        heartbeat_interval_seconds=_float("HEARTBEAT_INTERVAL_SECONDS", 30.0, 1.0),
        auto_run_due_campaigns=_bool("AUTO_RUN_DUE_CAMPAIGNS", False),
        draft_only=_bool("DRAFT_ONLY", True),
        website_enabled=_bool("WEBSITE_ENABLED", False),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.validate()
    return settings
