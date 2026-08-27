"""Campaign workflow orchestration inspired by Automaton's think-act-observe loop."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from campaign_automaton.agents import (
    AnalyticsAgent,
    AttributionIntegrityAgent,
    ComplianceAgent,
    DistributionAgent,
    EditorialQualityAgent,
    MarketingAgent,
    OperationsReliabilityAgent,
    ResearchAgent,
    SEOAgent,
)
from campaign_automaton.config import Settings
from campaign_automaton.links import AffiliateLinkBuilder
from campaign_automaton.llm import LLMClient
from campaign_automaton.models import RunRequest, RunStatus
from campaign_automaton.policy import PolicyEngine
from campaign_automaton.store import SQLiteStore

log = logging.getLogger(__name__)


class CampaignOrchestrator:
    """Run a bounded, approval-gated nine-agent campaign workflow."""

    def __init__(
        self,
        settings: Settings,
        store: SQLiteStore,
        llm: LLMClient,
        policy: PolicyEngine,
        links: AffiliateLinkBuilder,
    ) -> None:
        self.settings = settings
        self.store = store
        self.llm = llm
        self.policy = policy
        self.links = links
        self.research = ResearchAgent(llm)
        self.compliance = ComplianceAgent(llm)
        self.seo = SEOAgent(llm)
        self.editorial = EditorialQualityAgent(llm)
        self.marketing = MarketingAgent(llm)
        self.distribution = DistributionAgent(llm)
        self.attribution = AttributionIntegrityAgent(llm)
        self.analytics = AnalyticsAgent(llm)
        self.operations = OperationsReliabilityAgent(llm)

    def queue_run(
        self,
        campaign_slug: str,
        request: RunRequest,
        idempotency_key: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        campaign = self.store.get_campaign(campaign_slug)
        channels = [str(channel) for channel in (request.channels or campaign["channels"])]
        if idempotency_key is None:
            window = datetime.now(UTC).strftime("%Y-%m-%d")
            seed = f"{campaign['id']}:{request.workflow}:{','.join(channels)}:{window}"
            if request.force:
                seed += f":{uuid.uuid4()}"
            idempotency_key = hashlib.sha256(seed.encode()).hexdigest()
        return self.store.create_run(
            campaign["id"], request.workflow, channels, idempotency_key
        )

    def run_now(
        self,
        campaign_slug: str,
        request: RunRequest,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        run, created = self.queue_run(campaign_slug, request, idempotency_key)
        if not created and run["status"] not in {RunStatus.QUEUED, RunStatus.FAILED}:
            return run
        return self.execute_run(run["id"])

    def queue_daily_tiktok_review(
        self, now: datetime | None = None
    ) -> tuple[dict[str, Any] | None, bool]:
        """Create one internal, policy-checked TikTok review draft per local day.

        This method never uploads media, calls TikTok, posts content, or approves an
        artifact. It reuses the existing run, policy, artifact, and audit controls so
        the owner has one reviewable candidate rather than an autonomous posting flow.
        """
        local_now = (now or datetime.now(UTC)).astimezone(
            ZoneInfo(self.settings.schedule_timezone)
        )
        configured_slugs = set(self.settings.daily_tiktok_review_campaigns)
        candidates = [
            campaign
            for campaign in self.store.list_campaigns()
            if campaign["status"] == "active" and campaign["slug"] in configured_slugs
        ]
        if not candidates:
            return None, False
        candidates.sort(key=lambda campaign: campaign["slug"])
        campaign = candidates[local_now.toordinal() % len(candidates)]
        date_bucket = local_now.date().isoformat()
        run, created = self.queue_run(
            campaign["slug"],
            RunRequest(workflow="tiktok_review", channels=["social"], force=False),
            idempotency_key=f"daily-tiktok-review:{date_bucket}",
        )
        if created:
            return self.execute_run(run["id"]), True
        return run, False

    def execute_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        campaign = self.store.get_campaign_by_id(run["campaign_id"])
        if not self.store.claim_run(run_id):
            return self.store.get_run(run_id)
        if run["workflow"] == "tiktok_review":
            return self._execute_tiktok_review(run, campaign)
        self.store.audit(
            campaign["id"], "system", "run.started", "run", run_id,
            {"workflow": run["workflow"], "channels": run["requested_channels"]},
        )
        context: dict[str, Any] = {
            "memories": self.store.recall(campaign["id"], limit=12),
            "requested_channels": run["requested_channels"],
            "metrics": self.store.campaign_metrics(campaign["id"]),
            "attribution": self.store.campaign_attribution(campaign["id"]),
            "affiliate_status": self.links.affiliate_status(),
            "tracking_urls": {
                channel: self.links.tracking_url(campaign["slug"], channel)
                for channel in run["requested_channels"]
            },
        }
        results: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        try:
            agents = self._agents_for_workflow(run["workflow"])
            for agent in agents:
                agent_context = {
                    **context,
                    "prior_agent_results": [
                        {
                            "agent": result["agent"],
                            "summary": result["summary"],
                            "deliverables": [
                                {
                                    "kind": item["kind"],
                                    "title": item["title"],
                                    "data": item["data"],
                                }
                                for item in result["deliverables"]
                            ],
                        }
                        for result in results
                    ],
                }
                result = agent.run(campaign=campaign, run_id=run_id, context=agent_context)
                results.append(result)
                for item in result["deliverables"]:
                    sales_intent = agent.name == "MarketingAgent"
                    evaluated = self.policy.evaluate_content(
                        item["content"],
                        channel=item["channel"],
                        sales_intent=sales_intent,
                        add_disclosure=sales_intent,
                    )
                    artifact = self.store.create_artifact(
                        campaign_id=campaign["id"],
                        run_id=run_id,
                        agent=agent.name,
                        artifact_type=item["kind"],
                        channel=item["channel"],
                        title=item["title"],
                        content=evaluated.content,
                        metadata={
                            "agent_confidence": result["confidence"],
                            "assumptions": result["assumptions"],
                            "sources_needed": result["sources_needed"],
                            "model": result["model"],
                            "deterministic": result["deterministic"],
                            "data": item["data"],
                        },
                        policy=evaluated.result.model_dump(),
                    )
                    self.store.record_policy_decision(
                        campaign["id"],
                        run_id,
                        artifact["id"],
                        evaluated.result.allowed,
                        [finding.model_dump() for finding in evaluated.result.findings],
                    )
                    artifacts.append(artifact)
                self.store.remember(
                    campaign["id"],
                    "episodic",
                    agent.name,
                    result["summary"],
                    importance=0.65,
                    metadata={"run_id": run_id, "model": result["model"]},
                )
            self._save_optimization_proposal(campaign, run_id, results)
            summary = {
                "agents": [result["agent"] for result in results],
                "artifact_ids": [artifact["id"] for artifact in artifacts],
                "artifacts_created": len(artifacts),
                "blocked_artifacts": sum(
                    1 for artifact in artifacts if not artifact["policy"].get("allowed", False)
                ),
                "llm_mode": self.llm.mode,
                "affiliate": self.links.affiliate_status(),
            }
            final_status = RunStatus.AWAITING_APPROVAL if artifacts else RunStatus.COMPLETED
            final = self.store.update_run(run_id, final_status, summary=summary)
            self.store.audit(
                campaign["id"], "system", "run.finished", "run", run_id, summary
            )
            return final
        except Exception as exc:
            log.exception("Campaign run %s failed", run_id)
            self.store.audit(
                campaign["id"], "system", "run.failed", "run", run_id,
                {"error": str(exc)},
            )
            return self.store.update_run(
                run_id, RunStatus.FAILED, error=str(exc),
                summary={"agents_completed": [result["agent"] for result in results]},
            )
        finally:
            self.llm.clear_run_budget(run_id)

    def _execute_tiktok_review(
        self, run: dict[str, Any], campaign: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist a single reviewable TikTok concept without platform interaction."""
        run_id = run["id"]
        try:
            date_bucket = str(run["created_at"])[:10]
            content_id = f"{campaign['slug']}-tiktok-review-{date_bucket}"
            tracking_url = self.links.tracking_url(
                campaign["slug"],
                source="tiktok",
                content_id=content_id,
                medium="organic",
            )
            facts = [
                str(item).strip()
                for item in campaign.get("product_facts", [])
                if str(item).strip()
            ]
            fact_lines = "\n".join(f"- {fact}" for fact in facts[:3]) or (
                "- Controleer de actuele productinformatie en voorwaarden van de aanbieder."
            )
            content = f"""# Interne TikTok-reviewkandidaat — {campaign['product_name']}

**Status: concept voor eigenaarreview. Niet uploaden of posten.**

## Inhoudshoek

Een korte, oorspronkelijke video kan één neutrale vergelijkingsvraag behandelen voordat iemand een productpagina bezoekt. Gebruik geen testimonials, urgentie, gezondheids-, inkomen-, prestatie- of resultaatclaims.

## Feiten die vóór een publicatie opnieuw moeten worden gecontroleerd

{fact_lines}

## Captionconcept — bewerkbaar vóór een eventuele post

“Voordat je een online aanbod vergelijkt: controleer eerst de inhoud, voorwaarden en wat voor jouw situatie relevant is. Ik heb een korte keuzehulp voorbereid. **Advertentie / affiliatevermelding:** bij een aankoop via een toekomstige affiliatelink kan ik een commissie ontvangen. Bekijk eerst de actuele aanbiederinformatie.”

## Voorgestelde, nog niet gebruikte meetroute

{tracking_url}

## Vereiste eigenaarcontrole vóór een eventuele externe actie

1. Bevestig dat het kanaal en de merchantvoorwaarden deze plaatsing toestaan.
2. Controleer de actuele productgegevens en de eerste-party route.
3. Beoordeel de definitieve video, caption, zichtbaarheid en commerciële disclosure.
4. Geef uitdrukkelijk toestemming voor precies deze upload of post.

Deze reviewkandidaat voert geen externe actie uit en creëert geen TikTok-upload."""
            evaluated = self.policy.evaluate_content(
                content,
                channel="social",
                sales_intent=True,
                add_disclosure=True,
            )
            artifact = self.store.create_artifact(
                campaign_id=campaign["id"],
                run_id=run_id,
                agent="DailyTikTokReviewQueue",
                artifact_type="tiktok_review_candidate",
                channel="social",
                title=f"TikTok-reviewconcept: {campaign['product_name']} ({date_bucket})",
                content=evaluated.content,
                metadata={
                    "platform": "tiktok",
                    "cadence": "one_candidate_per_day",
                    "content_id": content_id,
                    "tracking_url": tracking_url,
                    "external_action": False,
                    "upload_attempted": False,
                    "post_attempted": False,
                    "owner_confirmation_required": True,
                    "merchant_channel_check_required": True,
                    "commercial_disclosure_required": True,
                },
                policy=evaluated.result.model_dump(),
            )
            self.store.record_policy_decision(
                campaign["id"],
                run_id,
                artifact["id"],
                evaluated.result.allowed,
                [finding.model_dump() for finding in evaluated.result.findings],
            )
            summary = {
                "workflow": "tiktok_review",
                "artifact_ids": [artifact["id"]],
                "artifacts_created": 1,
                "blocked_artifacts": int(
                    not artifact["policy"].get("allowed", False)
                ),
                "external_action": False,
                "owner_confirmation_required": True,
                "upload_attempted": False,
                "post_attempted": False,
            }
            final = self.store.update_run(
                run_id, RunStatus.AWAITING_APPROVAL, summary=summary
            )
            self.store.audit(
                campaign["id"],
                "daily_tiktok_review_queue",
                "tiktok_review.created",
                "artifact",
                artifact["id"],
                {
                    "date_bucket": date_bucket,
                    "policy_allowed": evaluated.result.allowed,
                    "external_action": False,
                    "owner_confirmation_required": True,
                },
            )
            return final
        except Exception as exc:
            log.exception("Daily TikTok review run %s failed", run_id)
            self.store.audit(
                campaign["id"],
                "daily_tiktok_review_queue",
                "tiktok_review.failed",
                "run",
                run_id,
                {"error": str(exc), "external_action": False},
            )
            return self.store.update_run(
                run_id,
                RunStatus.FAILED,
                error=str(exc),
                summary={"workflow": "tiktok_review", "external_action": False},
            )

    def _agents_for_workflow(self, workflow: str) -> list[Any]:
        workflows = {
            "full_campaign": [
                self.research,
                self.compliance,
                self.seo,
                self.editorial,
                self.marketing,
                self.distribution,
                self.attribution,
                self.analytics,
                self.operations,
            ],
            "research": [self.research, self.compliance],
            "seo": [self.research, self.compliance, self.seo, self.editorial],
            "content": [
                self.research,
                self.compliance,
                self.seo,
                self.editorial,
                self.marketing,
                self.distribution,
            ],
            "analytics": [self.attribution, self.analytics, self.operations],
        }
        if workflow not in workflows:
            raise ValueError(f"unknown workflow: {workflow}")
        return workflows[workflow]

    def _save_optimization_proposal(
        self,
        campaign: dict[str, Any],
        run_id: str,
        results: list[dict[str, Any]],
    ) -> None:
        for result in results:
            if result["agent"] != "AnalyticsAgent":
                continue
            for item in result["deliverables"]:
                hypothesis = item["data"].get("optimization_hypothesis")
                if hypothesis:
                    self.store.create_optimization_proposal(
                        campaign["id"],
                        run_id,
                        hypothesis,
                        {"metrics": item["data"].get("metrics", {})},
                    )
                    return
