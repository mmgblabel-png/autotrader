"""Attribution integrity agent for privacy-safe campaign measurement."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class AttributionIntegrityAgent(BaseAgent):
    """Audit UTM and conversion measurement hygiene without inferring personal identity."""

    name = "AttributionIntegrityAgent"
    objective = (
        "Audit aggregate UTM, redirect, and signed conversion measurement so recommendations "
        "remain attributable, privacy-safe, and distinct from individual-level profiling."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        metrics = context.get("metrics", {})
        attribution = context.get("attribution", [])
        checks = [
            "Elke creatieve route gebruikt bron, medium, campagne en content in de UTM-taxonomie.",
            "Alleen geaggregeerde brondata is zichtbaar in Event Farm.",
            "Een conversie telt alleen na een geldige, tijdige en niet-herhaalde PayPro-signatuur.",
            "Onbekende of ontbrekende attributie blijft een meetprobleem, geen prestatieconclusie.",
        ]
        data = {
            "metrics": metrics,
            "attribution_rows": len(attribution),
            "checks": checks,
            "measurement_state": "insufficient" if int(metrics.get("clicks", 0)) < 20 else "ready_for_review",
        }
        return {
            "summary": "Attributie-audit voltooid; conclusies blijven begrensd door geaggregeerde meetkwaliteit.",
            "confidence": 0.5 if int(metrics.get("clicks", 0)) < 20 else 0.75,
            "assumptions": ["UTM-waarden zijn afkomstig van toegestane, eigenaar-gecontroleerde creatieve routes."],
            "sources_needed": ["Ondertekende PayPro-conversiecallback voor omzetvalidatie."],
            "deliverables": [{
                "kind": "attribution_audit",
                "channel": "analytics",
                "title": f"Attributie-audit – {campaign['name']}",
                "content": "\n".join(f"- {check}" for check in checks),
                "data_json": json.dumps(data, ensure_ascii=False),
            }],
        }
