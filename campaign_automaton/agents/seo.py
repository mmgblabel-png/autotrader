"""SEO planning agent."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class SEOAgent(BaseAgent):
    name = "SEOAgent"
    objective = (
        "Turn research insights into helpful search-intent clusters, editorial plans, and "
        "on-page recommendations without keyword stuffing or unsupported claims."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        clusters = [
            {
                "pillar": "Gezond afvallen",
                "intent": "informatief",
                "supporting_topics": [
                    "Waarom kleine gewoontes beter vol te houden zijn",
                    "Hoe maak je een realistisch persoonlijk plan?",
                    "Veelgemaakte valkuilen bij een crashdieet",
                ],
            },
            {
                "pillar": "Persoonlijk afslankplan",
                "intent": "commercieel onderzoekend",
                "supporting_topics": [
                    "Welke vragen horen bij een verantwoord startplan?",
                    "Wat kun je verwachten van digitale begeleiding?",
                    "Checklist: past een afslankapp bij jou?",
                ],
            },
            {
                "pillar": "Afvallen per levensfase",
                "intent": "informatief",
                "supporting_topics": [
                    "Routine en herstel in verschillende levensfasen",
                    "Wanneer vraag je professioneel advies?",
                    "Zo evalueer je jouw voortgang zonder obsessie met de weegschaal",
                ],
            },
        ]
        calendar = [
            {"week": 1, "asset": "pillar_blog", "topic": "Gezond afvallen met haalbare stappen"},
            {"week": 2, "asset": "checklist", "topic": "Past een persoonlijk afslankplan bij jou?"},
            {"week": 3, "asset": "faq", "topic": "Verantwoord beginnen met een afslankapp"},
            {"week": 4, "asset": "comparison_guide", "topic": "Crashdieet versus duurzame gewoontes"},
        ]
        data = {
            "topic_clusters": clusters,
            "editorial_calendar": calendar,
            "on_page_rules": [
                "Gebruik één primaire zoekintentie per pagina.",
                "Schrijf eerst voor de lezer; verwerk termen natuurlijk.",
                "Markeer aannames en link naar betrouwbare gezondheidsinformatie waar passend.",
                "Plaats affiliatevermelding dicht bij de eerste commerciële link.",
                "Voeg FAQ-schema alleen toe als de vragen en antwoorden zichtbaar op de pagina staan.",
            ],
            "internal_linking": [
                "Link informatieve artikelen naar de centrale gids over gezond afvallen.",
                "Link commerciële gidsen naar de quiz via de interne trackinglink.",
                "Link medische context naar gezaghebbende publieke gezondheidsbronnen.",
            ],
        }
        return {
            "summary": "SEO-plan met drie clusters en een vierweekse waarde-eerst kalender.",
            "confidence": 0.6,
            "assumptions": ["Zoekvolumes en concurrentieniveaus zijn nog niet gevalideerd."],
            "sources_needed": [
                "Google Search Console-data van de eigen site",
                "Gevalideerde zoekvolumes uit een toegestaan SEO-platform",
                "Bestaande URL-inventaris voor het interne linkplan",
            ],
            "deliverables": [
                {
                    "kind": "seo_plan",
                    "channel": "seo",
                    "title": f"SEO-contentplan – {campaign['name']}",
                    "content": (
                        "Bouw eerst autoriteit met nuttige uitleg over gezond en duurzaam "
                        "afvallen. Verbind informatieve zoekintenties met transparante, rustige "
                        "CTA's naar de quiz. Valideer zoekvolume en concurrentie voordat de "
                        "redactionele prioriteit definitief wordt vastgesteld."
                    ),
                    "data_json": json.dumps(data, ensure_ascii=False),
                }
            ],
        }
