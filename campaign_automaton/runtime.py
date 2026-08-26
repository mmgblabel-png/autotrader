"""Application dependency container and deterministic bootstrap."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib.resources import files

import yaml

from campaign_automaton.config import Settings, load_settings
from campaign_automaton.links import AffiliateLinkBuilder
from campaign_automaton.llm import LLMClient
from campaign_automaton.models import CampaignCreate
from campaign_automaton.orchestrator import CampaignOrchestrator
from campaign_automaton.policy import PolicyEngine
from campaign_automaton.scheduler import HeartbeatScheduler
from campaign_automaton.store import SQLiteStore


@dataclass(slots=True)
class Runtime:
    settings: Settings
    store: SQLiteStore
    links: AffiliateLinkBuilder
    policy: PolicyEngine
    llm: LLMClient
    orchestrator: CampaignOrchestrator
    scheduler: HeartbeatScheduler


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _seed_default_campaign(settings: Settings, store: SQLiteStore) -> dict:
    if settings.campaign_config_path.exists():
        source = settings.campaign_config_path
    else:
        source = files("campaign_automaton").joinpath("defaults/campaign.yaml")
    with source.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    campaign_data = raw.get("campaign", raw)
    request = CampaignCreate.model_validate(campaign_data)
    product_url = str(request.product_url or settings.paypro_product_url)
    return store.seed_campaign(request, product_url)


def build_runtime(settings: Settings | None = None) -> Runtime:
    settings = settings or load_settings()
    configure_logging(settings.log_level)
    store = SQLiteStore(settings.database_path)
    store.initialize()
    _seed_default_campaign(settings, store)
    links = AffiliateLinkBuilder(settings)
    policy = PolicyEngine(settings)
    llm = LLMClient(settings, store)
    orchestrator = CampaignOrchestrator(settings, store, llm, policy, links)
    scheduler = HeartbeatScheduler(settings, store, orchestrator)
    return Runtime(settings, store, links, policy, llm, orchestrator, scheduler)
