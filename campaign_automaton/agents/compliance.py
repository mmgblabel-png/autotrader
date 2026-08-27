"""Compliance preflight agent for approval-gated campaign work."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class ComplianceAgent(BaseAgent):
    """Surface merchant-term and content-risk questions without granting approval."""

    name = "ComplianceAgent"
    objective = (
        "Create a factual merchant-term and claims preflight for owner review; never approve, "
        "enroll, publish, or override policy controls."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        facts = campaign.get("product_facts", [])
        prohibited = campaign.get("prohibited_claims", [])
        checks = [
            "Gebruik alleen geverifieerde productfeiten uit het campagneprofiel.",
            "Plaats een duidelijke affiliatevermelding naast iedere CTA.",
            "Controleer merchantvoorwaarden per kanaal voordat een concept wordt gebruikt.",
            "Laat een eigenaar elk extern zichtbaar item beoordelen en goedkeuren.",
        ]
        data = {
            "publication_recommendation": "owner_review_required",
            "verified_fact_count": len(facts),
            "prohibited_claims": prohibited,
            "checks": checks,
            "unresolved_questions": [
                "Zijn de actuele PayPro-promotievoorwaarden voor dit kanaal bevestigd?",
                "Is de gebruikte affiliatelink de account-uitgegeven bestemming?",
            ],
        }
        content = (
            f"Compliance-preflight voor {campaign['product_name']}\n\n"
            + "\n".join(f"- {check}" for check in checks)
            + "\n\nStatus: alleen concepten; eigenaarsoordeel blijft vereist."
        )
        return {
            "summary": "Compliance-preflight voltooid; geen publicatie- of inschrijvingsbevoegdheid.",
            "confidence": 0.72,
            "assumptions": ["De opgeslagen productfeiten zijn door de eigenaar geverifieerd."],
            "sources_needed": ["Actuele merchantvoorwaarden voor het gekozen distributiekanaal."],
            "deliverables": [{
                "kind": "compliance_review",
                "channel": "compliance",
                "title": f"Compliance-preflight – {campaign['name']}",
                "content": content,
                "data_json": json.dumps(data, ensure_ascii=False),
            }],
        }
