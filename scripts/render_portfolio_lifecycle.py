"""Render an ordered real-data portfolio event lifecycle chart for the slide presentation."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

SOURCE = Path("/tmp/portfolio-review-data.json")  # noqa: S108 - explicit local analysis input
OUTPUT = Path("/home/ubuntu/Downloads/paypromoney/automaton-paypro-kilos/docs/assets/portfolio_event_lifecycle.png")


def main() -> None:
    data = json.loads(SOURCE.read_text())
    totals = {"views": 0, "clicks": 0, "signups": 0, "conversions": 0}
    for campaign in data["campaigns"]:
        for key in totals:
            totals[key] += int(campaign["analytics"][key])

    stages = [
        ("Views", totals["views"], "#6D8FA6", "page impressions recorded"),
        ("Clicks", totals["clicks"], "#2E8B70", "tracked PayPro redirects"),
        ("Signups", totals["signups"], "#D9A441", "no verified events yet"),
        ("Conversions", totals["conversions"], "#C76C5B", "no verified events yet"),
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(16, 8), dpi=160)
    fig.patch.set_facecolor("#FBFAF6")
    ax.set_facecolor("#FBFAF6")
    ax.set_xlim(0, 16)
    ax.set_ylim(0, 8)
    ax.axis("off")

    ax.text(0.7, 7.2, "Portfolio event lifecycle", fontsize=27, weight="bold", color="#1D2B23")
    ax.text(
        0.7,
        6.65,
        "Actual recorded events across three active campaigns — verification traffic only",
        fontsize=13,
        color="#526057",
    )

    for index, (label, value, color, caption) in enumerate(stages):
        x = 0.8 + index * 3.8
        card = FancyBboxPatch(
            (x, 2.05),
            3.0,
            3.65,
            boxstyle="round,pad=0.05,rounding_size=0.18",
            linewidth=1.4,
            edgecolor="#D8DDD4",
            facecolor="#FFFFFF",
        )
        ax.add_patch(card)
        circle = plt.Circle((x + 1.5, 4.72), 0.47, color=color, alpha=0.96)
        ax.add_patch(circle)
        ax.text(x + 1.5, 4.72, str(index + 1), ha="center", va="center", fontsize=17, weight="bold", color="white")
        ax.text(x + 1.5, 3.95, label, ha="center", va="center", fontsize=17, weight="bold", color="#1D2B23")
        ax.text(x + 1.5, 3.12, str(value), ha="center", va="center", fontsize=40, weight="bold", color=color)
        ax.text(x + 1.5, 2.48, caption, ha="center", va="center", fontsize=10.5, color="#526057", wrap=True)
        if index < len(stages) - 1:
            ax.annotate(
                "",
                xy=(x + 3.63, 3.9),
                xytext=(x + 3.08, 3.9),
                arrowprops={"arrowstyle": "->", "lw": 2.2, "color": "#A7B4A9"},
            )

    ax.text(
        0.8,
        1.18,
        "Data quality guardrail: these counts are not a conversion funnel. They consist of labeled internal verification events, so no performance conclusion or experiment is justified yet.",
        fontsize=12.5,
        color="#7A4E15",
        bbox={"boxstyle": "round,pad=0.55", "facecolor": "#FFF5DE", "edgecolor": "#EBC57B"},
    )
    ax.text(
        0.8,
        0.45,
        "Decision threshold for the continuous worker: wait for at least 100 views and 20 clicks per campaign before considering a conversion experiment.",
        fontsize=11.5,
        color="#526057",
    )

    fig.savefig(OUTPUT, bbox_inches="tight", facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
