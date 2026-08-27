from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    name = "ResearchAgent"
    objective = (
        "Develop evidence-seeking audience, keyword, community, and competitor research "
        "briefs without fabricating facts or collecting personal data."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        product_name = str(campaign["product_name"])
        market = str(campaign["market"])
        segments = [
            {
                "segment": "Compatibility-first shoppers",
                "need": "Understand whether the product fits their existing device, space, and routine.",
                "message_angle": "Use a practical compatibility checklist before considering the current listing.",
            },
            {
                "segment": "Replacement or upgrade researchers",
                "need": "Compare a familiar device category without being pressured into unnecessary features.",
                "message_angle": "Explain what to verify, what can vary, and when an alternative may fit better.",
            },
            {
                "segment": "Value-conscious household buyers",
                "need": "Make an informed decision based on current product details and their own budget.",
                "message_angle": "Separate stable product facts from price, availability, delivery, and offer details that change.",
            },
        ]
        keyword_themes = [
            f"{product_name} compatibility",
            f"{product_name} setup requirements",
            f"{product_name} alternatives",
            "how to choose a streaming device",
            f"{product_name} features to verify",
            "HD streaming device compatibility checklist",
        ]
        community_plan = [
            "Study publicly visible, product-relevant questions at the topic level without collecting profiles or contact data.",
            "Record recurring compatibility and comparison questions with a public source URL for owner verification.",
            "Provide an answer only where a community permits the format and the response directly addresses a real question.",
            "Do not place Amazon Special Links in customer-content areas on Amazon, unsolicited messages, or channels that prohibit affiliate links.",
        ]
        data = {
            "segments": segments,
            "keyword_themes": keyword_themes,
            "community_plan": community_plan,
            "competitor_review_fields": [
                "device compatibility",
                "installation and setup requirements",
                "ongoing service requirements",
                "price and delivery variability",
                "return terms",
                "claims and disclosure placement",
                "content gaps",
            ],
            "verified_facts": campaign.get("product_facts", []),
        }
        return {
            "summary": (
                f"Prepared a hypothesis-led, {market}-focused research brief for {product_name} "
                "using only campaign-supplied facts."
            ),
            "confidence": 0.62,
            "assumptions": [
                "The campaign audience is able to use the target Amazon storefront.",
                "The owner will verify current compatibility, price, availability, delivery, and returns before approving copy.",
                "No conversion result can be inferred before a controlled test accumulates valid report data.",
            ],
            "sources_needed": [
                "Current manufacturer specifications and compatibility guidance",
                "Current Amazon detail-page information for the exact selected variant",
                "Permitted, aggregate search-demand data from an owner-approved source",
                "Promotion and disclosure rules for each external channel considered",
            ],
            "deliverables": [
                {
                    "kind": "research_brief",
                    "channel": "research",
                    "title": f"Research brief — {campaign['name']}",
                    "content": (
                        f"Start with the questions a {product_name} shopper must answer before deciding: "
                        "existing-device compatibility, physical connection or placement, network or service needs, "
                        "and the difference between stable specifications and details that change. Use public, "
                        "aggregate topic research only. Verify product facts, terms, and the destination before any "
                        "commercial draft is approved; do not infer conversion likelihood from bestseller rank alone."
                    ),
                    "data_json": json.dumps(data, ensure_ascii=False),
                }
            ],
        }
