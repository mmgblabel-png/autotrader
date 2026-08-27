from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class MarketingAgent(BaseAgent):
    name = "MarketingAgent"
    objective = (
        "Create helpful, non-spammy product-research drafts grounded only in verified campaign "
        "facts, with direct affiliate links, conspicuous disclosure, and no outcome promises."
    )

    @staticmethod
    def _facts(campaign: dict[str, Any]) -> list[str]:
        facts = [str(item).strip() for item in campaign.get("product_facts", [])]
        return [fact for fact in facts if fact]

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        channels = context.get("requested_channels") or campaign.get("channels", [])
        tracking_urls = context.get("tracking_urls", {})
        product_name = str(campaign["product_name"])
        facts = self._facts(campaign)
        fact_list = "\n".join(f"- {fact}" for fact in facts[:5]) or (
            "- Check the current product page and terms before deciding."
        )
        affiliate = context.get("affiliate_status", {})
        direct_link_ready = bool(affiliate.get("ready"))

        def cta(channel: str) -> str:
            link = str(tracking_urls.get(channel) or "").strip()
            if direct_link_ready and link:
                return (
                    "Disclosure: As an Amazon Associate I earn from qualifying purchases. "
                    "(paid link)\n\n"
                    f"[View the current Amazon product details]({link})"
                )
            return (
                "DRAFT-ONLY: An exact Amazon Associates Special Link has not been configured. "
                "Do not publish this draft or add a purchase call-to-action until the owner has "
                "pasted the unmodified SiteStripe or Associates Central link."
            )

        deliverables: list[dict[str, str]] = []
        for channel in channels:
            call_to_action = cta(str(channel))
            if channel == "blog":
                title = f"What to check before choosing the {product_name}"
                content = f"""# {title}

A reusable water bottle is a small daily-use purchase, but the practical details still matter. Start with where you expect to use it, whether the size works for your routine, and whether the design suits how you drink and clean it. This is independent product-research information, not health or performance advice.

## Verified product details

{fact_list}

## Before deciding

1. Confirm the current product variant, price, availability, delivery eligibility, and return terms on Amazon.
2. Consider capacity, cleaning routine, bag space, and whether the bottle fits the cupholder you use.
3. Compare alternatives when a different lid type, size, or lower price is more important to you.
4. Make a purchase only if the current listing fits your own needs and budget.

{call_to_action}"""
                kind = "blog_article"
                data = {"primary_intent": "informed_product_research", "cta": "direct_special_link"}
            elif channel == "email":
                title = f"Email draft: practical checks for {product_name}"
                content = f"""Subject: A few practical checks before choosing a reusable water bottle

Hello {{first_name}},

If you are comparing reusable water bottles, it can help to focus on everyday fit rather than impulse. Here are the product details we have verified:

{fact_list}

Please confirm current price, delivery, and return information directly on Amazon before deciding.

{call_to_action}

This draft is only for recipients who opted in to receive relevant information. Include an unsubscribe route in every sent message."""
                kind = "email_sequence"
                data = {"sequence_step": 1, "audience": "opt-in only"}
            elif channel == "social":
                title = f"Social draft: a practical look at {product_name}"
                content = f"""Looking for a reusable insulated water bottle? Start with the details that change daily use: capacity, lid design, cleaning, carrying, and fit in the places you use it.

For the {product_name}, we verified:
{fact_list}

Always check the current Amazon listing for the exact variant, price, availability, and delivery options before buying.

{call_to_action}"""
                kind = "social_post"
                data = {"format": "organic", "platform_adaptation_required": True}
            elif channel == "landing_page":
                title = f"Product research: {product_name}"
                content = f"""# {title}

This page helps you check whether the product details match your daily routine. It does not promise a health, fitness, or performance outcome.

## Verified product details

{fact_list}

## Questions to consider

- Would the capacity and form factor work for commuting, campus, work, or exercise?
- Will the lid and cleaning requirements fit your regular routine?
- Does the cupholder note matter for the vehicles or equipment you use?
- Have you checked the live Amazon listing for the selected variant, price, availability, delivery eligibility, and return terms?

{call_to_action}"""
                kind = "landing_page_copy"
                data = {"cta": "direct_special_link", "claims_level": "conservative"}
            elif channel == "community":
                title = f"Community response template: {product_name}"
                content = (
                    "Answer the member's specific product-use question first. Mention the "
                    f"{product_name} only when it is directly relevant, the community rules permit it, "
                    "and the affiliate relationship is clearly disclosed beside a direct Amazon "
                    "Special Link. Never post identical replies across groups, and never send an "
                    "unsolicited direct message.\n\n"
                    f"{call_to_action}"
                )
                kind = "community_response_template"
                data = {"requires_rule_check": True, "requires_question_context": True}
            else:
                continue
            deliverables.append(
                {
                    "kind": kind,
                    "channel": channel,
                    "title": title,
                    "content": content,
                    "data_json": json.dumps(data, ensure_ascii=False),
                }
            )
        return {
            "summary": f"Generated {len(deliverables)} approval-gated product-research drafts for {product_name}.",
            "confidence": 0.7,
            "assumptions": [
                "The owner will paste an exact Amazon Associates Special Link before approving a purchase CTA.",
                "Every external publication remains subject to separate owner approval and channel-rule review.",
            ],
            "sources_needed": [
                "Current Amazon product listing for price, availability, delivery, and returns",
                "Amazon Associates operating agreement and participation requirements",
                "Applicable community or social-platform advertising rules",
            ],
            "deliverables": deliverables,
        }
