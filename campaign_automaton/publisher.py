"""Read-only public rendering for owner-approved campaign artifacts."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from campaign_automaton.config import Settings
from campaign_automaton.links import AffiliateLinkBuilder
from campaign_automaton.store import SQLiteStore

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_ORDERED = re.compile(r"^\d+\.\s+(.+)$")
_TRACKING_VALUE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$", re.IGNORECASE)
_ALLOWED_SOURCES = {
    "direct", "organic", "google", "social", "facebook", "instagram", "linkedin",
    "email", "newsletter", "website", "amazon", "paypro",
}
_ALLOWED_MEDIA = {"affiliate", "social", "email", "organic", "referral", "paid", "display"}

_CREATIVE_VARIANTS: dict[str, tuple[dict[str, str], ...]] = {
    "owala-freesip-24oz": (
        {
            "id": "daily-carry-social",
            "source": "instagram",
            "medium": "social",
            "content": "daily-carry-social",
            "eyebrow": "Product research · Daily carry",
            "headline": "Check the daily-use details before choosing a reusable bottle.",
            "lede": "A practical review prompt for capacity, lid design, cleaning, carrying, and cupholder fit.",
            "cta": "View current product details on Amazon",
        },
        {
            "id": "commute-comparison",
            "source": "organic",
            "medium": "organic",
            "content": "commute-comparison",
            "eyebrow": "Product research · Commuting",
            "headline": "A reusable bottle should work with the way you actually travel.",
            "lede": "Compare size, opening, locking, cleaning, and compatibility with the places you use it.",
            "cta": "View current product details on Amazon",
        },
    ),
}


def safe_tracking_value(value: str, *, allowed: set[str], fallback: str) -> str:
    """Keep public URL attribution aggregate, bounded, and free of arbitrary query text."""
    normalized = value.strip().lower()
    return normalized if normalized in allowed else fallback


def safe_content_id(value: str, fallback: str = "hero-cta") -> str:
    """Return a bounded content tag so personal or arbitrary query text is never stored."""
    normalized = value.strip().lower()
    return normalized if _TRACKING_VALUE.fullmatch(normalized) else fallback


@dataclass(frozen=True, slots=True)
class PublishedArtifact:
    """A validated public view of one approved artifact."""

    id: str
    artifact_type: str
    title: str
    content: str
    created_at: str
    reviewed_at: str | None


def _safe_url(value: str) -> str:
    """Return an escaped absolute HTTP(S) URL, or an empty string for unsafe input."""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return html.escape(value, quote=True)


def _inline(text: str) -> str:
    """Escape plain text and permit only Markdown HTTP(S) links."""
    position = 0
    parts: list[str] = []
    for match in _LINK.finditer(text):
        parts.append(html.escape(text[position : match.start()]))
        label = html.escape(match.group(1))
        href = _safe_url(match.group(2))
        parts.append(
            f'<a href="{href}" rel="nofollow sponsored noopener" target="_blank">{label}</a>'
            if href
            else label
        )
        position = match.end()
    parts.append(html.escape(text[position:]))
    return "".join(parts)


def render_markdown(content: str) -> str:
    """Render a conservative subset of Markdown after escaping all source text."""
    rendered: list[str] = []
    list_kind: str | None = None
    paragraph: list[str] = []

    def close_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            rendered.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            rendered.append(f"</{list_kind}>")
            list_kind = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            close_paragraph()
            close_list()
            continue
        if line.startswith("## "):
            close_paragraph()
            close_list()
            rendered.append(f"<h2>{_inline(line[3:])}</h2>")
            continue
        if line.startswith("### "):
            close_paragraph()
            close_list()
            rendered.append(f"<h3>{_inline(line[4:])}</h3>")
            continue
        if line.startswith("# "):
            close_paragraph()
            close_list()
            rendered.append(f"<h2>{_inline(line[2:])}</h2>")
            continue
        if line.startswith("- "):
            close_paragraph()
            if list_kind != "ul":
                close_list()
                list_kind = "ul"
                rendered.append("<ul>")
            rendered.append(f"<li>{_inline(line[2:])}</li>")
            continue
        ordered = _ORDERED.match(line)
        if ordered:
            close_paragraph()
            if list_kind != "ol":
                close_list()
                list_kind = "ol"
                rendered.append("<ol>")
            rendered.append(f"<li>{_inline(ordered.group(1))}</li>")
            continue
        close_list()
        paragraph.append(line)

    close_paragraph()
    close_list()
    return "\n".join(rendered)


class PublicPublisher:
    """Render public pages from the latest approved campaign artifacts."""

    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings = settings
        self.store = store
        self.links = AffiliateLinkBuilder(settings)

    def enabled(self) -> bool:
        return self.settings.website_enabled

    def _cta(self, campaign: dict[str, Any], *, source: str, medium: str, content_id: str) -> str:
        if self.settings.direct_affiliate_links_only:
            destination = self.links.content_link(campaign, source, content_id, medium)
            if not destination:
                return (
                    '<p class="notice"><strong>Draft-only configuration.</strong> The owner has not yet '
                    'configured an Amazon Associates Special Link, so no purchase link is displayed.</p>'
                )
            return (
                f'<p class="notice"><strong>Disclosure.</strong> {html.escape(self.settings.affiliate_disclosure)}</p>'
                f'<a class="cta" href="{_safe_url(destination)}" rel="nofollow sponsored noopener" '
                'target="_blank">View current product details on Amazon</a>'
            )
        href = f"/r/{html.escape(campaign['slug'])}?src={html.escape(source, quote=True)}&medium={html.escape(medium, quote=True)}&content={html.escape(content_id, quote=True)}"
        return f'<a class="cta" href="{href}">View product information</a>'

    def creative(self, campaign_slug: str, creative_id: str) -> str | None:
        """Render a pre-approved factual creative route with a distinct content identifier."""
        variant = next(
            (item for item in _CREATIVE_VARIANTS.get(campaign_slug, ()) if item["id"] == creative_id),
            None,
        )
        if variant is None or "landing_page_copy" not in self.latest_by_type(campaign_slug):
            return None
        campaign = self.store.get_campaign(campaign_slug)
        cta = self._cta(
            campaign,
            source=variant["source"],
            medium=variant["medium"],
            content_id=variant["content"],
        )
        body = f"""
<section class="hero"><div class="shell hero-card"><p class="eyebrow">{html.escape(variant['eyebrow'])}</p><h1>{html.escape(variant['headline'])}</h1><p class="lede">{html.escape(variant['lede'])}</p>{cta}</div></section>
<section class="content" id="more"><p>This page presents a factual product-research prompt. Check the live Amazon listing for variant, price, availability, delivery eligibility, and return terms before deciding.</p><p><a href="/site/{html.escape(campaign_slug)}">← Read the complete product research</a></p></section>"""
        return self.page(
            campaign_slug,
            body,
            title=f"{variant['headline']} | Product research",
            description=f"Independent product-research context for {campaign['product_name']}.",
        )

    def status(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self.store.get_campaign(campaign_slug)
        artifacts = self._approved(campaign["id"])
        return {
            "enabled": self.enabled(),
            "campaign_slug": campaign_slug,
            "approved_artifact_count": len(artifacts),
            "published_artifact_types": sorted({item.artifact_type for item in artifacts}),
            "visibility_rule": "owner-approved and policy-cleared artifacts only",
            "direct_links_only": self.settings.direct_affiliate_links_only,
            "affiliate": self.links.affiliate_status(campaign),
        }

    def _approved(self, campaign_id: str) -> list[PublishedArtifact]:
        candidates = self.store.list_artifacts(campaign_id, status="approved", limit=500)
        artifacts: list[PublishedArtifact] = []
        for item in candidates:
            if not item.get("policy", {}).get("allowed", False):
                continue
            artifacts.append(
                PublishedArtifact(
                    id=item["id"],
                    artifact_type=item["artifact_type"],
                    title=item["title"],
                    content=item["content"],
                    created_at=item["created_at"],
                    reviewed_at=item.get("reviewed_at"),
                )
            )
        return artifacts

    def latest_by_type(self, campaign_slug: str) -> dict[str, PublishedArtifact]:
        campaign = self.store.get_campaign(campaign_slug)
        latest: dict[str, PublishedArtifact] = {}
        for artifact in self._approved(campaign["id"]):
            latest.setdefault(artifact.artifact_type, artifact)
        return latest

    def article(self, campaign_slug: str, artifact_id: str) -> PublishedArtifact | None:
        campaign = self.store.get_campaign(campaign_slug)
        for artifact in self._approved(campaign["id"]):
            if artifact.id == artifact_id and artifact.artifact_type == "blog_article":
                return artifact
        return None

    def page(
        self, campaign_slug: str | None, body: str, *, title: str, description: str
    ) -> str:
        safe_title = html.escape(title)
        safe_description = html.escape(description, quote=True)
        home_href = "/site" if campaign_slug is None else f"/site/{html.escape(campaign_slug)}"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{safe_description}">
  <meta name="robots" content="index,follow">
  <title>{safe_title}</title>
  <style>
    :root {{ --ink:#132238; --paper:#f7f9fc; --navy:#173d63; --sky:#eaf4fb; --line:#cdd9e5; --accent:#b66222; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:var(--paper); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.65; }}
    a {{ color:var(--navy); }} .shell {{ width:min(1080px,calc(100% - 40px)); margin:auto; }}
    header {{ position:sticky; top:0; z-index:10; background:rgba(247,249,252,.96); backdrop-filter:blur(10px); border-bottom:1px solid var(--line); }}
    .nav {{ min-height:66px; display:flex; align-items:center; justify-content:space-between; gap:20px; }} .brand {{ color:var(--ink); font-weight:800; text-decoration:none; letter-spacing:-.02em; }} .nav a:not(.brand) {{ font-size:.94rem; font-weight:700; text-decoration:none; }} main {{ padding:0 0 68px; }}
    .hero {{ min-height:420px; display:grid; align-items:center; color:#fff; background:linear-gradient(120deg,#173d63 0%,#215d8f 55%,#4288b8 100%); }} .hero-card {{ width:min(700px,100%); padding:70px 0; }} .eyebrow {{ margin:0 0 14px; text-transform:uppercase; letter-spacing:.13em; font-size:.76rem; font-weight:800; color:#dceefa; }} h1 {{ margin:0; max-width:740px; font-size:clamp(2.35rem,5vw,4.4rem); line-height:1.06; letter-spacing:-.05em; }} h2 {{ line-height:1.15; letter-spacing:-.025em; margin:36px 0 14px; font-size:clamp(1.55rem,3vw,2.25rem); }} h3 {{ margin:26px 0 10px; line-height:1.2; }} .lede {{ max-width:640px; margin:24px 0 30px; color:#eff8ff; font-size:1.13rem; }}
    .cta {{ display:inline-flex; padding:13px 18px; align-items:center; border-radius:999px; background:#fff; color:#173d63; text-decoration:none; font-weight:800; }} .cta:hover {{ background:#e7f5ff; }} .notice {{ border-left:4px solid var(--accent); background:#fff4e7; padding:14px 17px; margin:22px 0; border-radius:0 12px 12px 0; color:var(--ink); }} .grid {{ display:grid; gap:20px; grid-template-columns:repeat(3,1fr); margin:38px 0; }} .card {{ padding:24px; border:1px solid var(--line); border-radius:16px; background:#fff; }} .card h2 {{ font-size:1.25rem; margin:0 0 8px; }} .content {{ width:min(780px,100%); margin:52px auto 0; }} .article-list {{ display:grid; gap:16px; margin-top:28px; }} .article-link {{ display:block; padding:20px; border:1px solid var(--line); border-radius:14px; background:#fff; color:var(--ink); text-decoration:none; }} .article-link:hover {{ border-color:var(--navy); }} .portfolio-grid {{ display:grid; gap:18px; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); margin-top:30px; }} .product-card {{ display:flex; min-height:220px; flex-direction:column; justify-content:space-between; padding:26px; border:1px solid var(--line); border-radius:16px; background:#fff; }} .product-card h2 {{ margin:0 0 10px; font-size:1.45rem; }} .product-card p {{ margin:0 0 20px; color:#52657a; }} footer {{ border-top:1px solid var(--line); padding:28px 0 46px; color:#52657a; font-size:.9rem; }} ul,ol {{ padding-left:1.3rem; }} @media (max-width:760px) {{ .shell {{ width:min(100% - 28px,1080px); }} .grid {{ grid-template-columns:1fr; }} .hero {{ min-height:500px; }} .hero-card {{ padding:62px 0; }} .nav span {{ display:none; }} }}
  </style>
</head>
<body>
<header><nav class="nav shell"><a class="brand" href="{home_href}">Practical product research</a><a href="#more">Read the details <span>before deciding</span></a></nav></header>
<main>{body}</main>
<footer><div class="shell">© 2026 Practical product research · Independent information. Verify live listing details before purchase.</div></footer>
</body>
</html>"""

    def _disclosure_if_needed(self, content: str) -> str:
        if self.settings.affiliate_disclosure in content:
            return ""
        return f'<div class="notice"><strong>Disclosure.</strong> {html.escape(self.settings.affiliate_disclosure)}</div>'

    def portfolio(self) -> str:
        """Render an index of active campaigns that are ready for public display."""
        cards: list[str] = []
        for campaign in self.store.list_campaigns():
            if campaign.get("status") != "active":
                continue
            latest = self.latest_by_type(campaign["slug"])
            if "landing_page_copy" not in latest:
                continue
            facts = campaign.get("product_facts") or []
            summary = str(facts[0]).strip() if facts else "Read the independent product-research context before deciding."
            cards.append(
                '<article class="product-card">'
                f'<div><p class="eyebrow" style="color:#173d63">Owner-approved research</p>'
                f'<h2>{html.escape(campaign["product_name"])}</h2>'
                f'<p>{html.escape(summary)}</p></div>'
                f'<a class="cta" href="/site/{html.escape(campaign["slug"])}">Read the product research</a>'
                "</article>"
            )
        products = "".join(cards) or "<p>No owner-approved product-research pages are currently available.</p>"
        body = f"""
<section class="hero"><div class="shell hero-card"><p class="eyebrow">Independent context · Transparent links</p><h1>Research the practical details before you choose.</h1><p class="lede">Only owner-approved information, clear affiliate disclosure, and no unsupported product promises.</p></div></section>
<section class="content" id="more"><h2>Owner-approved product research</h2><p>Each page separates stable product facts from details that can change, such as variant, price, availability, delivery, and return terms. Confirm those details in the live listing before buying.</p><div class="portfolio-grid">{products}</div></section>"""
        return self.page(
            None,
            body,
            title="Practical product research | Owner-approved pages",
            description="Independent product-research pages with transparent affiliate disclosure.",
        )

    def home(
        self,
        campaign_slug: str,
        source: str = "website",
        medium: str = "referral",
        content_id: str = "hero-cta",
    ) -> str:
        campaign = self.store.get_campaign(campaign_slug)
        latest = self.latest_by_type(campaign_slug)
        landing = latest.get("landing_page_copy")
        articles = [item for item in self._approved(campaign["id"]) if item.artifact_type == "blog_article"]
        cta = self._cta(campaign, source=source, medium=medium, content_id=content_id)
        landing_content = landing.content if landing else ""
        landing_html = render_markdown(landing_content) if landing else (
            "<h2>In preparation</h2><p>There is no owner-approved landing-page draft available yet.</p>"
        )
        disclosure_html = self._disclosure_if_needed(landing_content)
        article_html = "".join(
            f'<a class="article-link" href="/site/{html.escape(campaign_slug)}/articles/{html.escape(item.id)}"><strong>{html.escape(item.title)}</strong><br><span>Read the article</span></a>'
            for item in articles[:6]
        ) or "<p>No owner-approved articles are available yet.</p>"
        body = f"""
<section class="hero"><div class="shell hero-card"><p class="eyebrow">Practical product research</p><h1>Check the daily-use details before buying.</h1><p class="lede">Use this page to evaluate product fit, then confirm the live listing details yourself.</p>{cta}</div></section>
<section class="content" id="more">{landing_html}{disclosure_html}<div class="grid"><article class="card"><h2>Start with your routine</h2><p>Think about when, where, and how you will actually use the product.</p></article><article class="card"><h2>Verify variable details</h2><p>Price, availability, delivery eligibility, and returns can change. Confirm them in the live listing.</p></article><article class="card"><h2>Decide without pressure</h2><p>Compare alternatives and choose only what fits your needs and budget.</p></article></div><h2>Further reading</h2><div class="article-list">{article_html}</div></section>"""
        return self.page(
            campaign_slug,
            body,
            title=f"{campaign['product_name']} | Practical product research",
            description=f"Independent product-research context for {campaign['product_name']}.",
        )

    def article_page(self, campaign_slug: str, artifact: PublishedArtifact) -> str:
        body = f"""<section class="content"><p class="eyebrow" style="color:#173d63">Practical product research</p><h1 style="font-size:clamp(2.25rem,5vw,4rem)">{html.escape(artifact.title)}</h1>{render_markdown(artifact.content)}{self._disclosure_if_needed(artifact.content)}<p><a href="/site/{html.escape(campaign_slug)}">← Return to product research</a></p></section>"""
        return self.page(
            campaign_slug,
            body,
            title=f"{artifact.title} | Practical product research",
            description="Independent product-research information with transparent affiliate disclosure.",
        )
