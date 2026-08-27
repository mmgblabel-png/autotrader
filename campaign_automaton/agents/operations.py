"""Operations reliability agent for heartbeat and budget visibility."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class OperationsReliabilityAgent(BaseAgent):
    """Report operational readiness; it cannot alter runtime state or secrets."""

    name = "OperationsReliabilityAgent"
    objective = (
        "Report scheduler, tracking, and budget health with explicit human escalation points; never "
        "modify secrets, settings, schedules, or publication state."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        affiliate = context.get("affiliate_status", {})
        metrics = context.get("metrics", {})
        checks = [
            "Controleer hartslag, queue en volgende geplande run.",
            "Controleer dat de eerste-partij redirect naar een gevalideerde PayPro-bestemming wijst.",
            "Controleer dat callback-signaturen actief en recent zijn voordat omzet wordt geïnterpreteerd.",
            "Escalleer beleidsblokkades, ontbrekende attributie en budgetlimieten naar de eigenaar.",
        ]
        data = {
            "affiliate_status": affiliate,
            "metrics": metrics,
            "checks": checks,
            "escalation_required": not bool(affiliate.get("configured", False)),
        }
        return {
            "summary": "Operationele controle opgesteld; de eigenaar behoudt alle runtime- en publicatiebevoegdheid.",
            "confidence": 0.65,
            "assumptions": ["De runtime publiceert actuele scheduler- en callbackstatus via de control API."],
            "sources_needed": ["Actuele heartbeat- en callbackstatus bij een echte productie-run."],
            "deliverables": [{
                "kind": "operations_report",
                "channel": "operations",
                "title": f"Operationele controle – {campaign['name']}",
                "content": "\n".join(f"- {check}" for check in checks),
                "data_json": json.dumps(data, ensure_ascii=False),
            }],
        }
