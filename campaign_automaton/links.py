from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from campaign_automaton.config import Settings, is_amazon_special_link


def _with_query(url: str, values: dict[str, str]) -> str:
    """Add attribution only for providers that expressly support the configured format."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class AffiliateLinkBuilder:
    """Resolve an affiliate destination while preserving program-specific link requirements.

    Amazon Associates links are direct, owner-supplied Special Links. The application does not
    manufacture a tag, change URL parameters, wrap the URL, or route the click through `/r`.
    PayPro support is retained only for legacy branch compatibility.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _amazon_special_link(self, campaign: dict) -> str:
        campaign_link = str(campaign.get("product_url") or "").strip()
        if is_amazon_special_link(campaign_link):
            return campaign_link
        if is_amazon_special_link(self.settings.amazon_associate_url):
            return self.settings.amazon_associate_url
        return ""

    def destination(
        self, campaign: dict, source: str, content_id: str = "", medium: str = "affiliate"
    ) -> str:
        if self.settings.affiliate_provider == "amazon":
            # A special link must remain byte-for-byte as supplied by the owner/SiteStripe.
            return self._amazon_special_link(campaign)
        product_url = campaign.get("product_url") or self.settings.paypro_product_url
        target = self.settings.paypro_affiliate_url_template.format(
            product_url=product_url,
            affiliate_id=self.settings.paypro_affiliate_id,
        )
        return _with_query(
            target,
            {
                "utm_source": source,
                "utm_medium": medium,
                "utm_campaign": campaign["slug"],
                "utm_content": content_id,
            },
        )

    def content_link(
        self, campaign: dict, source: str, content_id: str = "", medium: str = "affiliate"
    ) -> str:
        """Return the link that is safe to include in generated owner-reviewable content."""
        if self.settings.affiliate_provider == "amazon":
            return self.destination(campaign, source, content_id, medium)
        return self.tracking_url(campaign, source, content_id, medium)

    def tracking_url(
        self, campaign: dict, source: str, content_id: str = "", medium: str = "affiliate"
    ) -> str:
        """Return a first-party redirect only for legacy non-Amazon providers."""
        if self.settings.direct_affiliate_links_only:
            return self.destination(campaign, source, content_id, medium)
        path = f"{self.settings.public_base_url}/r/{campaign['slug']}"
        return _with_query(path, {"src": source, "medium": medium, "content": content_id})

    def affiliate_status(self, campaign: dict | None = None) -> dict[str, str | bool]:
        if self.settings.affiliate_provider == "amazon":
            special_link = self._amazon_special_link(campaign or {})
            return {
                "provider": "amazon",
                "direct_links_only": True,
                "special_link_configured": bool(special_link),
                "ready": bool(special_link),
                "next_step": (
                    "Paste the exact Amazon Associates SiteStripe or Associates Central link into "
                    "AMAZON_ASSOCIATE_URL before approving any purchase CTA."
                    if not special_link
                    else "Use the direct Special Link unchanged and keep the disclosure adjacent to it."
                ),
            }
        template_uses_id = "{affiliate_id}" in self.settings.paypro_affiliate_url_template
        return {
            "provider": "paypro",
            "affiliate_id_configured": bool(self.settings.paypro_affiliate_id),
            "template_uses_affiliate_id": template_uses_id,
            "product_url_configured": bool(self.settings.paypro_product_url),
            "ready": bool(self.settings.paypro_product_url)
            and (not template_uses_id or bool(self.settings.paypro_affiliate_id)),
        }
