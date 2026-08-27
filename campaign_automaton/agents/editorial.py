"""Editorial quality agent for factual, readable campaign drafts."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class EditorialQualityAgent(BaseAgent):
    """Create a revision brief; it does not edit or publish owner-approved artifacts."""

    name = "EditorialQualityAgent"
    objective = (
        "Prepare a concise factual Dutch editorial review brief that improves clarity, disclosure, "
        "and useful structure without inventing evidence, testimonials, or outcomes."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        facts = campaign.get("product_facts", [])
        review_points = [
            "Open met wat het product feitelijk is, niet met een resultaatbelofte.",
            "Gebruik korte alinea's, concrete tussenkoppen en één heldere vervolgstap.",
            "Houd de affiliatevermelding zichtbaar bij de CTA.",
            "Verwijder gezondheids-, inkomens-, schaarste- en testimonialclaims zonder bron.",
        ]
        data = {
            "review_points": review_points,
            "fact_anchor": facts[:4],
            "owner_review_required": True,
        }
        return {
            "summary": "Redactioneel revisiebrief opgesteld op basis van geverifieerde productfeiten.",
            "confidence": 0.7,
            "assumptions": ["Concepten blijven voor publicatie door een eigenaar beoordeeld."],
            "sources_needed": [],
            "deliverables": [{
                "kind": "editorial_review",
                "channel": "editorial",
                "title": f"Redactioneel revisiebrief – {campaign['name']}",
                "content": "\n".join(f"- {point}" for point in review_points),
                "data_json": json.dumps(data, ensure_ascii=False),
            }],
        }
