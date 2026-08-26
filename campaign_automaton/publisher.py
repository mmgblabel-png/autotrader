"""Safe self-hosted publisher for approved campaign artifacts.

The publisher is intentionally read-only. It never generates content, changes approval
status, or contacts third-party publishing services. Public rendering is possible only
when the owner explicitly enables it, and it exposes only artifacts that are both
owner-approved and policy-cleared.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from campaign_automaton.config import Settings
from campaign_automaton.store import SQLiteStore

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_ORDERED = re.compile(r"^\d+\.\s+(.+)$")


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

    def enabled(self) -> bool:
        return self.settings.website_enabled

    def status(self, campaign_slug: str) -> dict[str, Any]:
        campaign = self.store.get_campaign(campaign_slug)
        artifacts = self._approved(campaign["id"])
        return {
            "enabled": self.enabled(),
            "campaign_slug": campaign_slug,
            "approved_artifact_count": len(artifacts),
            "published_artifact_types": sorted({item.artifact_type for item in artifacts}),
            "visibility_rule": "owner-approved and policy-cleared artifacts only",
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

    def page(self, campaign_slug: str, body: str, *, title: str, description: str) -> str:
        safe_title = html.escape(title)
        safe_description = html.escape(description, quote=True)
        current_year = "2026"
        return f"""<!doctype html>
<html lang="nl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{safe_description}">
  <meta name="robots" content="index,follow">
  <title>{safe_title}</title>
  <link rel="preload" as="image" href="/static/images/hero-habit-planning.jpg">
  <style>
    :root {{ --ink:#1d2b23; --paper:#fbfaf6; --sage:#e4eee3; --green:#1e6a48; --gold:#c88a24; --line:#d8ddd4; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:var(--paper); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; line-height:1.65; }}
    a {{ color:var(--green); }} .shell {{ width:min(1120px,calc(100% - 40px)); margin:auto; }}
    header {{ position:sticky; top:0; z-index:10; background:rgba(251,250,246,.94); backdrop-filter:blur(10px); border-bottom:1px solid var(--line); }}
    .nav {{ min-height:66px; display:flex; align-items:center; justify-content:space-between; gap:20px; }} .brand {{ color:var(--ink); font-weight:800; text-decoration:none; letter-spacing:-.02em; }}
    .nav a:not(.brand) {{ font-size:.94rem; font-weight:700; text-decoration:none; }} main {{ padding:0 0 68px; }}
    .hero {{ min-height:470px; display:grid; align-items:center; color:#fff; background:linear-gradient(90deg,rgba(16,29,20,.94) 0%,rgba(16,29,20,.78) 43%,rgba(16,29,20,.08) 74%),url('/static/images/hero-habit-planning.jpg') center/cover; }}
    .hero-card {{ width:min(610px,100%); padding:70px 0; }} .eyebrow {{ margin:0 0 14px; text-transform:uppercase; letter-spacing:.13em; font-size:.76rem; font-weight:800; color:#cfe4cd; }}
    h1 {{ margin:0; max-width:690px; font-size:clamp(2.45rem,5vw,4.7rem); line-height:1.04; letter-spacing:-.05em; }} h2 {{ line-height:1.15; letter-spacing:-.025em; margin:36px 0 14px; font-size:clamp(1.55rem,3vw,2.25rem); }} h3 {{ margin:26px 0 10px; line-height:1.2; }}
    .lede {{ max-width:600px; margin:24px 0 30px; color:#eef7ed; font-size:1.13rem; }} .cta {{ display:inline-flex; padding:13px 18px; align-items:center; border-radius:999px; background:#fff; color:#154c35; text-decoration:none; font-weight:800; }} .cta:hover {{ background:#e9f5e8; }}
    .notice {{ border-left:4px solid var(--gold); background:#fff5de; padding:14px 17px; margin:28px 0; border-radius:0 12px 12px 0; }} .grid {{ display:grid; gap:20px; grid-template-columns:repeat(3,1fr); margin:38px 0; }}
    .card {{ padding:24px; border:1px solid var(--line); border-radius:16px; background:#fff; }} .card h2 {{ font-size:1.25rem; margin:0 0 8px; }} .content {{ width:min(780px,100%); margin:52px auto 0; }} .article-list {{ display:grid; gap:16px; margin-top:28px; }} .article-link {{ display:block; padding:20px; border:1px solid var(--line); border-radius:14px; background:#fff; color:var(--ink); text-decoration:none; }} .article-link:hover {{ border-color:var(--green); }}
    .affiliate {{ margin-top:40px; padding:20px; border-radius:15px; background:var(--sage); font-size:.93rem; }} footer {{ border-top:1px solid var(--line); padding:28px 0 46px; color:#526057; font-size:.9rem; }} ul,ol {{ padding-left:1.3rem; }}
    @media (max-width:760px) {{ .shell {{ width:min(100% - 28px,1120px); }} .grid {{ grid-template-columns:1fr; }} .hero {{ min-height:530px; background-position:68% center; }} .hero-card {{ padding:62px 0; }} .nav span {{ display:none; }} }}
  </style>
</head>
<body>
<header><nav class="nav shell"><a class="brand" href="/site/{html.escape(campaign_slug)}">Rustig vooruit</a><a href="#meer">Meer lezen <span>over een haalbare start</span></a></nav></header>
<main>{body}</main>
<footer><div class="shell">© {current_year} Rustig vooruit · Onafhankelijke leefstijlinformatie. Geen medisch advies.</div></footer>
</body>
</html>"""

    def _disclosure_if_needed(self, content: str) -> str:
        if self.settings.affiliate_disclosure in content:
            return ""
        return (
            '<div class="notice"><strong>Transparantie.</strong> '
            f"{html.escape(self.settings.affiliate_disclosure)}</div>"
        )

    def home(self, campaign_slug: str) -> str:
        latest = self.latest_by_type(campaign_slug)
        landing = latest.get("landing_page_copy")
        articles = [item for item in self._approved(self.store.get_campaign(campaign_slug)["id"]) if item.artifact_type == "blog_article"]
        cta = f"/r/{campaign_slug}?src=website-home&content=hero-cta"
        landing_content = landing.content if landing else ""
        landing_html = render_markdown(landing_content) if landing else (
            "<h2>In voorbereiding</h2><p>Er is nog geen eigenaar-goedgekeurde landingspagina beschikbaar.</p>"
        )
        disclosure_html = self._disclosure_if_needed(landing_content)
        article_html = "".join(
            f'<a class="article-link" href="/site/{html.escape(campaign_slug)}/articles/{html.escape(item.id)}"><strong>{html.escape(item.title)}</strong><br><span>Lees het artikel</span></a>'
            for item in articles[:6]
        ) or "<p>Nog geen eigenaar-goedgekeurde artikelen beschikbaar.</p>"
        body = f"""
<section class="hero"><div class="shell hero-card"><p class="eyebrow">Kleine stappen · In eigen tempo</p><h1>Een vertrekpunt dat bij je leven past.</h1><p class="lede">Verken rustig welke gewoonten jou kunnen helpen. Geen snelle belofte, wel praktische vragen voor een bewuste volgende stap.</p><a class="cta" href="{cta}">Bekijk de korte quiz</a></div></section>
<section class="content" id="meer">{landing_html}{disclosure_html}<div class="grid"><article class="card"><h2>Begin klein</h2><p>Kies een stap die op een gewone, drukke dag haalbaar blijft.</p></article><article class="card"><h2>Blijf kritisch</h2><p>Lees voorwaarden en privacy-informatie voordat je een keuze maakt.</p></article><article class="card"><h2>Vraag hulp wanneer nodig</h2><p>Bespreek medische vragen met een gekwalificeerde zorgprofessional.</p></article></div><h2>Verder lezen</h2><div class="article-list">{article_html}</div></section>"""
        return self.page(
            campaign_slug,
            body,
            title="Rustig vooruit | Een persoonlijk vertrekpunt",
            description="Praktische leefstijlinformatie en een bewuste stap richting de WegMetDieKilos-quiz.",
        )

    def article_page(self, campaign_slug: str, artifact: PublishedArtifact) -> str:
        body = f"""<section class="content"><p class="eyebrow" style="color:#1e6a48">Praktische leefstijlinformatie</p><h1 style="font-size:clamp(2.25rem,5vw,4rem)">{html.escape(artifact.title)}</h1>{render_markdown(artifact.content)}{self._disclosure_if_needed(artifact.content)}<p><a href="/site/{html.escape(campaign_slug)}">← Terug naar de startpagina</a></p></section>"""
        return self.page(
            campaign_slug,
            body,
            title=f"{artifact.title} | Rustig vooruit",
            description="Praktische leefstijlinformatie met een transparante affiliatevermelding.",
        )
