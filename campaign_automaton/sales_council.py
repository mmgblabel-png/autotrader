"""Deterministic, aggregate-only advisors for the hourly sales-readiness report.

Each advisor returns a factual, bounded finding. The council does not invoke models,
access external services, expose sensitive data, create content, or take campaign action.
"""

from __future__ import annotations

from typing import Any

MINIMUM_OBSERVED_VIEWS = 100
MINIMUM_OBSERVED_CLICKS = 20


class SalesReadinessCouncil:
    """Run ten advisory checks in dependency order and return one private recommendation."""

    def evaluate(self, context: dict[str, Any]) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        findings.append(self._measurement_integrity(context))
        findings.append(self._funnel_stage(context, findings))
        findings.append(self._attribution_integrity(context, findings))
        findings.append(self._offer_facts(context, findings))
        findings.append(self._audience_definition(context, findings))
        findings.append(self._content_readiness(context, findings))
        findings.append(self._landing_page_readiness(context, findings))
        findings.append(self._consent_and_claims(context, findings))
        findings.append(self._acquisition_handoff(context, findings))
        findings.append(self._experiment_guardrail(context, findings))
        return {
            "version": 1,
            "findings": findings,
            "final_recommendation": findings[-1]["recommendation"],
        }

    @staticmethod
    def _finding(
        agent: str,
        status: str,
        summary: str,
        evidence: dict[str, Any],
        dependencies: list[str],
        recommendation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "agent": agent,
            "status": status,
            "summary": summary,
            "evidence": evidence,
            "depends_on": dependencies,
            "external_action": False,
        }
        if recommendation is not None:
            result["recommendation"] = recommendation
        return result

    def _measurement_integrity(self, context: dict[str, Any]) -> dict[str, Any]:
        quality = context["data_quality"]
        labels = {
            "no_events": "No campaign events have been observed yet.",
            "verification_only": "Only technical verification events exist; they are not customer demand.",
            "observed_events": "Observed campaign events are available for limited funnel review.",
        }
        return self._finding(
            "measurement_integrity",
            quality,
            labels[quality],
            {"data_quality": quality, "observed": context["observed"]},
            [],
        )

    def _funnel_stage(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        observed = context["observed"]
        if observed["views"] == 0:
            stage, summary = "traffic_unproven", "No observed visits exist to evaluate the funnel."
        elif observed["clicks"] == 0:
            stage, summary = "click_unproven", "Observed visits exist, but no observed click has been recorded."
        elif observed["signups"] == 0:
            stage, summary = "signup_unproven", "Observed clicks exist, but no signup event has been recorded."
        elif observed["conversions"] == 0:
            stage, summary = "conversion_unproven", "Observed earlier funnel events exist, but no verified conversion has been recorded."
        else:
            stage, summary = "conversion_observed", "A conversion event is present; attribution still requires review."
        return self._finding(
            "funnel_stage",
            stage,
            summary,
            {"observed": observed},
            [findings[0]["agent"]],
        )

    def _attribution_integrity(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        verified = context["verified_paypro_conversions"]
        status = "verified_conversion_present" if verified else "owner_check_required"
        summary = (
            "A verified PayPro conversion record exists; retain its attribution evidence for owner review."
            if verified
            else "Affiliate destination and attribution format require owner confirmation before commission claims."
        )
        return self._finding(
            "attribution_integrity",
            status,
            summary,
            {
                "verified_paypro_conversions": verified,
                "owner_confirmation_required": True,
            },
            [findings[0]["agent"], findings[1]["agent"]],
        )

    def _offer_facts(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        fact_count = context["product_fact_count"]
        status = "ready" if fact_count >= 2 else "needs_fact_review"
        summary = (
            "At least two campaign product facts are available for a conservative review."
            if status == "ready"
            else "Too few verified product facts are available for a strong offer recommendation."
        )
        return self._finding(
            "offer_facts",
            status,
            summary,
            {"verified_product_fact_count": fact_count},
            [],
        )

    def _audience_definition(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        ready = context["has_audience"] and context["goal_count"] > 0
        return self._finding(
            "audience_definition",
            "ready" if ready else "needs_owner_review",
            (
                "The campaign has a defined audience and at least one goal."
                if ready
                else "Audience or goal definition is incomplete; review it before changing distribution."
            ),
            {"has_audience": context["has_audience"], "goal_count": context["goal_count"]},
            [findings[3]["agent"]],
        )

    def _content_readiness(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        content = context["content"]
        if content["approved"] == 0:
            status, summary = "no_approved_content", "No approved artifact exists for an owner-reviewed handoff."
        elif content["policy_blocked"] > 0:
            status, summary = "review_blocked_content", "Approved content exists, but blocked drafts require separate correction."
        else:
            status, summary = "approved_content_available", "At least one approved, policy-cleared artifact is available."
        return self._finding(
            "content_readiness",
            status,
            summary,
            content,
            [findings[3]["agent"], findings[4]["agent"]],
        )

    def _landing_page_readiness(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        ready = "landing_page" in context["approved_artifact_types"]
        return self._finding(
            "landing_page_readiness",
            "ready" if ready else "needs_owner_review",
            (
                "An approved landing-page artifact is available for review."
                if ready
                else "No approved landing-page artifact is available for a first-channel handoff."
            ),
            {"approved_artifact_types": context["approved_artifact_types"]},
            [findings[5]["agent"]],
        )

    def _consent_and_claims(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        content = context["content"]
        status = "policy_review_required" if content["policy_blocked"] else "owner_review_required"
        return self._finding(
            "consent_and_claims",
            status,
            (
                "Policy-blocked artifacts must remain blocked and cannot be used."
                if content["policy_blocked"]
                else "Any external content still requires owner approval, consent checks, and clear disclosure."
            ),
            {
                "policy_blocked_artifacts": content["policy_blocked"],
                "owner_approval_required": True,
            },
            [findings[5]["agent"]],
        )

    def _acquisition_handoff(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        blockers = [
            finding["agent"]
            for finding in (findings[2], findings[5], findings[6], findings[7])
            if finding["status"]
            not in {
                "ready",
                "approved_content_available",
                "owner_review_required",
                "owner_check_required",
            }
        ]
        if blockers:
            status = "not_ready"
            summary = "Resolve the listed readiness blockers before preparing a distribution handoff."
        elif context["data_quality"] == "observed_events":
            status = "evidence_collected"
            summary = "Observed traffic exists; preserve the current handoff as control while review continues."
        else:
            status = "owner_handoff_available"
            summary = "A single manual, owner-approved, consent-respecting handoff can be prepared; it is not executed."
        return self._finding(
            "acquisition_handoff",
            status,
            summary,
            {"blockers": blockers, "owner_approval_required": True},
            [finding["agent"] for finding in findings[:8]],
        )

    def _experiment_guardrail(self, context: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        observed = context["observed"]
        ready = (
            observed["views"] >= MINIMUM_OBSERVED_VIEWS
            and observed["clicks"] >= MINIMUM_OBSERVED_CLICKS
            and findings[8]["status"] in {"owner_handoff_available", "evidence_collected"}
        )
        if ready and context["verified_paypro_conversions"] == 0:
            action = "Prepare one reversible, owner-reviewed experiment for a single approved channel."
            rationale = "Observed evidence meets the minimum review threshold, but no verified conversion exists."
            status = "proposal_allowed"
        elif context["verified_paypro_conversions"] > 0:
            action = "Review verified conversion attribution and preserve the current asset as the control."
            rationale = "A verified conversion exists; any change needs an explicit measurement plan."
            status = "review_existing_evidence"
        elif findings[8]["status"] == "owner_handoff_available":
            action = "Prepare one owner-approved, consent-respecting distribution handoff."
            rationale = "Observed customer evidence is not yet available; technical verification is not demand evidence."
            status = "collect_evidence_first"
        else:
            action = "Resolve the listed readiness blockers before considering distribution or an experiment."
            rationale = "The council found unmet attribution, content, landing-page, or policy prerequisites."
            status = "blocked_by_readiness"
        recommendation = {
            "action": action,
            "rationale": rationale,
            "owner_approval_required": True,
            "external_action": False,
            "claims_sale": False,
            "allowed_change": "proposal_only" if status == "proposal_allowed" else "none",
        }
        return self._finding(
            "experiment_guardrail",
            status,
            rationale,
            {
                "minimum_observed_views": MINIMUM_OBSERVED_VIEWS,
                "minimum_observed_clicks": MINIMUM_OBSERVED_CLICKS,
                "observed": observed,
            },
            [finding["agent"] for finding in findings[:9]],
            recommendation,
        )
