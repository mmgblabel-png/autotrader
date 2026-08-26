"""Analytics and optimization-proposal agent."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class AnalyticsAgent(BaseAgent):
    name = "AnalyticsAgent"
    objective = (
        "Analyze pseudonymous campaign events, report uncertainty, and propose reversible "
        "experiments for human approval without inventing causality."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        metrics = context.get("metrics", {})
        clicks = int(metrics.get("clicks", 0))
        conversions = int(metrics.get("conversions", 0))
        views = int(metrics.get("views", 0))
        if not views and not clicks:
            finding = (
                "Er is nog onvoldoende trackingdata. Controleer eerst de publieke basis-URL, "
                "trackinglinks en eventintegratie voordat contentprestaties worden beoordeeld."
            )
            hypothesis = "Valideer de meetketen met testevents voordat een inhoudelijk experiment start."
        elif clicks and not conversions:
            finding = (
                "Er zijn klikken maar nog geen geregistreerde conversies. Dit kan aan de "
                "propositie, landingspagina, meetkoppeling of kleine steekproef liggen."
            )
            hypothesis = (
                "Test één duidelijker waarde-eerst CTA-variant en verifieer tegelijk de "
                "conversiewebhook; verander geen andere variabele."
            )
        else:
            finding = (
                f"De geregistreerde dataset bevat {views} views, {clicks} klikken en "
                f"{conversions} conversies. Interpreteer percentages alleen samen met de "
                "steekproefgrootte en kanaalverdeling."
            )
            hypothesis = (
                "Vergelijk per kanaal één CTA-variant met een vooraf gekozen meetperiode en "
                "stopcriterium; behoud de huidige versie als controle."
            )
        data = {
            "metrics": metrics,
            "finding": finding,
            "optimization_hypothesis": hypothesis,
            "guardrails": [
                "Wijzig maximaal één hoofdvariabele per experiment.",
                "Gebruik geen gevoelige persoonssegmentatie.",
                "Stop een variant bij beleidsproblemen of duidelijke kwaliteitsdaling.",
                "Publiceer wijzigingen pas na menselijke goedkeuring.",
            ],
        }
        return {
            "summary": finding,
            "confidence": 0.45 if clicks < 20 else 0.7,
            "assumptions": ["Trackingevents zijn correct en niet dubbel geregistreerd."],
            "sources_needed": [
                "Gevalideerde conversiecallback of periodieke export",
                "Kanaalspecifieke impressie- en klikdata",
                "Vooraf bepaalde experimentduur en minimaal bruikbare steekproef",
            ],
            "deliverables": [
                {
                    "kind": "analytics_report",
                    "channel": "analytics",
                    "title": f"Analytics en optimalisatie – {campaign['name']}",
                    "content": f"{finding}\n\nVoorgesteld experiment: {hypothesis}",
                    "data_json": json.dumps(data, ensure_ascii=False),
                }
            ],
        }
