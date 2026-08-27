from pathlib import Path

import pytest

from campaign_automaton.config import Settings
from campaign_automaton.runtime import build_runtime


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parents[1]
    return Settings(
        app_name="Test Amazon Associate Campaign Automaton",
        app_env="test",
        data_dir=tmp_path,
        database_path=tmp_path / "test.db",
        campaign_config_path=root / "config" / "campaign.yaml",
        public_base_url="http://testserver",
        affiliate_provider="amazon",
        amazon_product_url="https://www.amazon.com/dp/B0BZYCJK89",
        amazon_associate_url="https://www.amazon.com/dp/B0BZYCJK89?tag=spmg00-20",
        paypro_product_url="https://www.paypro.nl/producten/WegMetDieKilos_Bronze_Plan/114766/183297",
        paypro_affiliate_id="affiliate-123",
        paypro_affiliate_url_template="{product_url}",
        affiliate_disclosure=(
            "Disclosure: As an Amazon Associate I earn from qualifying purchases. (paid link)"
        ),
        control_token="test-control-token",
        webhook_token="test-webhook-token",
        paypro_webhook_secret="test-paypro-webhook-secret",
        cors_origins=("http://testserver",),
        llm_provider="deterministic",
        llm_model="gpt-5-mini",
        llm_fallback_model="gpt-5-nano",
        llm_max_output_tokens=3500,
        llm_timeout_seconds=10.0,
        llm_max_requests_per_run=6,
        llm_max_requests_per_hour=30,
        llm_max_requests_per_day=150,
        heartbeat_enabled=False,
        heartbeat_interval_seconds=30.0,
        auto_run_due_campaigns=False,
        schedule_timezone="Europe/Amsterdam",
        draft_only=True,
        website_enabled=False,
        log_level="WARNING",
    )


@pytest.fixture()
def runtime(settings: Settings):
    return build_runtime(settings)
