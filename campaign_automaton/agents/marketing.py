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
        requested_channels = context.get("requested_channels") or campaign.get("channels", [])
        affiliate = context.get("affiliate_status", {})
        provider = str(affiliate.get("provider") or "").lower()
        forbidden_amazon_channels = {"email", "sms", "mms", "offline", "community"}
        skipped_channels = (
            [str(channel) for channel in requested_channels if str(channel) in forbidden_amazon_channels]
            if provider == "amazon"
            else []
        )
        channels = [str(channel) for channel in requested_channels if str(channel) not in skipped_channels]
        tracking_urls = context.get("tracking_urls", {})
        product_name = str(campaign["product_name"])
        facts = self._facts(campaign)
        fact_list = "\n".join(f"- {fact}" for fact in facts[:5]) or (
            "- Check the current product page and terms before deciding."
        )
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
            call_to_action = cta(channel)
            if channel == "blog":
                title = f"What to check before choosing {product_name}"
                content = f"""# {title}

A product listing can make a device look straightforward, but the practical details decide whether it fits a real setup. Start with your current equipment, connection options, intended use, and the details you need to verify before making a purchase. This is independent product-research information, not a performance guarantee.

## Verified product details

{fact_list}

## Before deciding

1. Confirm the current selected variant, price, availability, delivery eligibility, and return terms on Amazon.
2. Check compatibility with the equipment, connections, network, services, and space you already use.
3. Compare alternatives if a different specification, form factor, or price point is more appropriate for your needs.
4. Make a purchase only if the current listing fits your personal requirements and budget.

{call_to_action}"""
                kind = "blog_article"
                data = {"primary_intent": "informed_product_research", "cta": "direct_special_link"}
            elif channel == "social":
                title = f"Social draft: practical checks for {product_name}"
                content = f"""Considering a device in this category? Start with the details that affect day-to-day use: compatibility, connection, setup requirements, form factor, and the options that matter for your equipment.

For {product_name}, we verified:
{fact_list}

Check the current Amazon listing for the exact selected variant, price, availability, delivery options, and return terms before deciding.

{call_to_action}"""
                kind = "social_post"
                data = {"format": "organic", "platform_adaptation_required": True}
            elif channel == "landing_page":
                title = f"Product research: {product_name}"
                content = f"""# {title}

This page helps you check whether the documented product details fit the equipment and routine you already have. It does not promise an entertainment, connectivity, speed, health, fitness, or performance outcome.

## Verified product details

{fact_list}

## Questions to consider

- Is the product compatible with the device, connection, and environment you will use?
- Do you understand any network, account, subscription, content-service, accessory, or power requirements?
- Does the form factor work for your available space and setup?
- Have you checked the live Amazon listing for the selected variant, current price, availability, delivery eligibility, and return terms?

{call_to_action}"""
                kind = "landing_page_copy"
                data = {"cta": "direct_special_link", "claims_level": "conservative"}
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
            "summary": (
                f"Generated {len(deliverables)} approval-gated product-research drafts for {product_name}."
                + (
                    " Skipped email and community direct-link drafts because Amazon Special Links require "
                    "separate channel-permission review and cannot be used in email/SMS/offline promotion."
                    if skipped_channels
                    else ""
                )
            ),
            "confidence": 0.7,
            "assumptions": [
                "The owner will paste an exact Amazon Associates Special Link before approving a purchase CTA.",
                "Every external publication remains subject to separate owner approval and channel-rule review.",
                "Email, SMS/MMS, offline materials, and unverified community channels are excluded from Amazon Special Link promotion.",
            ],
            "sources_needed": [
                "Current Amazon product listing for price, availability, delivery, and returns",
                "Current manufacturer specifications and compatibility guidance",
                "Amazon Associates operating agreement and participation requirements",
                "Applicable social-platform or website advertising rules",
            ],
            "deliverables": deliverables,
        }
