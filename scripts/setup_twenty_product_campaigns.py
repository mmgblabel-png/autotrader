"""Seed 20 independent, draft-only Amazon campaigns from a private link sheet.

The catalog is versioned without affiliate links. This script reads the user-supplied
CSV at runtime, validates each exact Amazon Special Link, and stores it only in the
local campaign database. It never publishes or approves artifacts.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml

from campaign_automaton.config import is_amazon_special_link, load_settings
from campaign_automaton.models import CampaignCreate, Channel
from campaign_automaton.runtime import build_runtime


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed draft-only Amazon product campaigns.")
    parser.add_argument("--links-csv", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=Path("config/product_catalog.yaml"))
    return parser.parse_args()


def load_links(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    links = {
        row["product"].strip(): row["affiliate_special_link"].strip()
        for row in rows
        if row.get("priority", "").strip().isdigit() and row.get("affiliate_special_link", "").strip()
    }
    if len(links) != 20 or not all(is_amazon_special_link(value) for value in links.values()):
        raise ValueError("Expected exactly 20 valid owner-supplied Amazon Special Links in the CSV.")
    if len(set(links.values())) != 20:
        raise ValueError("Each product must have a distinct Amazon Special Link.")
    return links


def main() -> None:
    args = parse_arguments()
    with args.catalog.open(encoding="utf-8") as handle:
        catalog = yaml.safe_load(handle)["catalog"]
    links = load_links(args.links_csv)
    settings = load_settings()
    if not settings.draft_only:
        raise ValueError("DRAFT_ONLY must remain true when seeding product campaigns.")
    runtime = build_runtime(settings)
    seeded: list[str] = []
    for product in catalog["products"]:
        product_name = product["product"]
        link = links.get(product_name)
        if not link:
            raise ValueError(f"Missing Special Link for {product_name!r}.")
        request = CampaignCreate(
            name=f"{product_name} — Amazon Associate Draft Campaign",
            slug=product["slug"],
            product_name=product_name,
            product_url=link,
            audience=(
                "Adults located in the United States researching a practical product for a defined "
                "everyday task. Content must help visitors verify fit before selecting a live listing."
            ),
            market=catalog["market"],
            language=catalog["language"],
            channels=[Channel.BLOG, Channel.SOCIAL, Channel.LANDING_PAGE],
            goals=[
                "Prepare owner-reviewable, product-specific research and marketing drafts.",
                "Send voluntary, informed visitors to one unmodified Amazon Associates Special Link only after approval.",
                "Use Amazon Associates reporting as the source of record for any later performance review.",
            ],
            product_facts=[
                f"Campaign product: {product_name}.",
                f"Research focus: {product['angle']}.",
                f"Before a CTA is approved, the reader must verify: {product['verify']}.",
                "Price, promotions, stock, delivery eligibility, returns, reviews, rank, and commission rate are variable and excluded from public copy.",
            ],
            prohibited_claims=catalog["shared_prohibited_claims"],
            metadata={
                "priority": product["priority"],
                "category": product["category"],
                "mode": "draft_only",
                "direct_links_only": True,
                "source_checked_at": "2026-08-27",
                "link_activation_requirement": "Owner review is required before any artifact approval or external post.",
            },
        )
        runtime.store.seed_campaign(request, link)
        seeded.append(product["slug"])
    print(f"Seeded {len(seeded)} draft-only product campaigns.")
    print("No artifacts were published and no external actions were taken.")


if __name__ == "__main__":
    main()
