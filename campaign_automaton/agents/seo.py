from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class SEOAgent(BaseAgent):
    name = "SEOAgent"
    objective = (
        "Turn research insights into helpful search-intent clusters, editorial plans, and "
        "on-page recommendations without keyword stuffing or unsupported claims."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        product_name = str(campaign["product_name"])
        clusters = [
            {
                "pillar": "Streaming device compatibility",
                "intent": "informational",
                "supporting_topics": [
                    "How to check whether a TV has the right HDMI connection",
                    "What to verify about television resolution before choosing an HD streaming device",
                    "Streaming-device connection and placement checklist",
                ],
            },
            {
                "pillar": f"{product_name} product research",
                "intent": "commercial investigation",
                "supporting_topics": [
                    "Which product details should be checked in the current listing",
                    "Questions to ask before choosing an HD streaming device",
                    "When an HD device may be less suitable than a 4K alternative",
                ],
            },
            {
                "pillar": "Practical setup planning",
                "intent": "informational",
                "supporting_topics": [
                    "Where a TV-stick device connects and receives power",
                    "Why current network and service requirements should be verified",
                    "How to compare device alternatives without relying on temporary offers",
                ],
            },
        ]
        calendar = [
            {"week": 1, "asset": "pillar_blog", "topic": "Streaming-device compatibility checklist"},
            {"week": 2, "asset": "checklist", "topic": "Questions to verify before choosing an HD streaming stick"},
            {"week": 3, "asset": "faq", "topic": "HD, 4K, connection, and current listing details"},
            {"week": 4, "asset": "comparison_guide", "topic": "Choosing a streaming-device form factor for your TV"},
        ]
        data = {
            "topic_clusters": clusters,
            "editorial_calendar": calendar,
            "on_page_rules": [
                "Use one primary search intent per page and answer it before introducing a product.",
                "Write for the reader; use terms naturally and do not repeat trademarks unnecessarily.",
                "Separate stable specifications from variable price, offers, stock, delivery, and service availability.",
                "Place the Associate disclosure close to any permitted direct Special Link.",
                "Do not reuse customer reviews, star ratings, marketplace badges, or ranking claims without approved data rights.",
                "Add structured FAQ data only when the questions and answers are visibly present and independently verified.",
            ],
            "internal_linking": [
                "Link informational pages to a compatibility checklist on the operator's site.",
                "Link product-research pages only to a direct, owner-supplied Amazon Special Link when it is permitted and disclosed.",
                "Do not route paid-search traffic directly or indirectly through a redirect to Amazon.",
            ],
        }
        return {
            "summary": f"Prepared a conservative SEO plan for {product_name} with three research-first topic clusters.",
            "confidence": 0.6,
            "assumptions": [
                "Search volume, ranking difficulty, and audience demand remain unvalidated.",
                "Each listed topic will be checked against current manufacturer and Amazon information before publication.",
            ],
            "sources_needed": [
                "Owner-authorized Search Console or keyword-platform data",
                "Manufacturer compatibility and setup documentation",
                "Current product detail-page information for the exact selected variant",
                "Existing website inventory for any internal-link plan",
            ],
            "deliverables": [
                {
                    "kind": "seo_plan",
                    "channel": "seo",
                    "title": f"SEO content plan — {campaign['name']}",
                    "content": (
                        "Build useful product-research content around compatibility, connection, resolution, and setup questions. "
                        "Answer the practical question first, distinguish fixed specifications from variable listing details, "
                        "and use a transparent direct Special Link only after verifying the exact product and disclosure. "
                        "Do not optimize for Amazon trademark keywords in paid search or rely on ranking/review claims."
                    ),
                    "data_json": json.dumps(data, ensure_ascii=False),
                }
            ],
        }
