"""Affiliate-link construction and safe campaign attribution."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from campaign_automaton.config import Settings


def _with_query(url: str, values: dict[str, str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update({key: value for key, value in values.items() if value})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


class AffiliateLinkBuilder:
    """Create one canonical target and one first-party tracking URL.

    PayPro affiliate parameter formats are account-specific. The runtime therefore never
    guesses a query parameter. Operators can paste the exact URL into PAYPRO_PRODUCT_URL or
    set PAYPRO_AFFILIATE_URL_TEMPLATE with `{product_url}` and/or `{affiliate_id}`.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def destination(
        self, campaign: dict, source: str, content_id: str = "", medium: str = "affiliate"
    ) -> str:
        product_url = campaign.get("product_url") or self.settings.paypro_product_url
        template = self.settings.paypro_affiliate_url_template
        target = template.format(
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

    def tracking_url(
        self, campaign_slug: str, source: str, content_id: str = "", medium: str = "affiliate"
    ) -> str:
        path = f"{self.settings.public_base_url}/r/{campaign_slug}"
        return _with_query(path, {"src": source, "medium": medium, "content": content_id})

    def affiliate_status(self) -> dict[str, str | bool]:
        template_uses_id = "{affiliate_id}" in self.settings.paypro_affiliate_url_template
        return {
            "affiliate_id_configured": bool(self.settings.paypro_affiliate_id),
            "template_uses_affiliate_id": template_uses_id,
            "product_url_configured": bool(self.settings.paypro_product_url),
            "ready": bool(self.settings.paypro_product_url)
            and (not template_uses_id or bool(self.settings.paypro_affiliate_id)),
        }
