"""Ethical owned-and-earned distribution planning agent."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class DistributionAgent(BaseAgent):
    """Plan measurable organic distribution without automatically contacting anyone."""

    name = "DistributionAgent"
    objective = (
        "Create a measured, ethical, free owned-media distribution plan with UTM creative names; "
        "never auto-post, cold-message, spam, buy reach, or evade channel rules."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        channels = set(context.get("requested_channels", campaign.get("channels", [])))
        creative_base = campaign["slug"].replace("-", "_")
        plan = [
            {
                "surface": "owned_website",
                "action": "Publiceer alleen een eigenaar-goedgekeurde informatieve pagina.",
                "utm_content": f"{creative_base}_guide",
            },
            {
                "surface": "opt_in_email",
                "action": "Maak een concept voor bestaande, expliciet ingeschreven ontvangers.",
                "utm_content": f"{creative_base}_email_value",
            },
            {
                "surface": "owned_social",
                "action": "Maak een concept met nuttige context; plaats alleen handmatig na review.",
                "utm_content": f"{creative_base}_social_tip",
            },
        ]
        data = {
            "plan": plan,
            "requested_channels": sorted(channels),
            "forbidden_tactics": [
                "ongevraagde e-mail of DM",
                "linkdrops in groepen die niet door de eigenaar worden beheerd",
                "gekochte volgers of bereik",
                "verborgen affiliatelinks of misleidende urgentie",
            ],
            "owner_review_required": True,
        }
        return {
            "summary": "Organisch distributieplan opgesteld; alle externe stappen blijven handmatig en review-gated.",
            "confidence": 0.68,
            "assumptions": ["De eigenaar gebruikt alleen eigen kanalen of toegestane opt-in kanalen."],
            "sources_needed": ["Actuele regels van elk gekozen eigen kanaal."],
            "deliverables": [{
                "kind": "distribution_plan",
                "channel": "distribution",
                "title": f"Organisch distributieplan – {campaign['name']}",
                "content": "\n".join(
                    f"- {item['surface']}: {item['action']} ({item['utm_content']})" for item in plan
                ),
                "data_json": json.dumps(data, ensure_ascii=False),
            }],
        }
