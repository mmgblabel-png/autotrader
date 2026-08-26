"""Research agent for audience, intent, keyword, and community hypotheses."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    name = "ResearchAgent"
    objective = (
        "Develop evidence-seeking audience, keyword, community, and competitor research "
        "briefs without fabricating facts or collecting personal data."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        segments = [
            {
                "segment": "Gezond en duurzaam willen afvallen",
                "need": "Een haalbare aanpak die past in het dagelijks leven.",
                "message_angle": "Kleine, realistische stappen en een persoonlijk vertrekpunt.",
            },
            {
                "segment": "Opnieuw structuur zoeken",
                "need": "Duidelijkheid na eerdere pogingen zonder harde beloften.",
                "message_angle": "Focus op routine, reflectie en verantwoorde verwachtingen.",
            },
            {
                "segment": "Digitale begeleiding verkiezen",
                "need": "Een laagdrempelige app-ervaring en een plan dat bij de levensfase past.",
                "message_angle": "Start met de drie-minutenquiz en ontdek of de aanpak aansluit.",
            },
        ]
        keyword_themes = [
            "gezond afvallen",
            "duurzaam afvallen",
            "persoonlijk afslankplan",
            "afvallen app",
            "afvallen zonder crashdieet",
            "gezonde gewoontes afvallen",
            "afslankplan op leeftijd",
        ]
        community_plan = [
            "Bestudeer openbaar vindbare vragen in relevante Nederlandse gezondheids- en leefstijlcommunities zonder profielen of contactgegevens te verzamelen.",
            "Noteer terugkerende vragen op onderwerpniveau en link naar de openbare bron voor handmatige verificatie.",
            "Reageer alleen waardevol en transparant wanneer de community zelfpromotie en affiliatelinks toestaat.",
        ]
        data = {
            "segments": segments,
            "keyword_themes": keyword_themes,
            "community_plan": community_plan,
            "competitor_review_fields": [
                "positionering",
                "bewijsvoering",
                "prijs en voorwaarden",
                "privacy en toestemming",
                "claims",
                "contentgaten",
            ],
            "verified_facts": campaign.get("product_facts", []),
        }
        return {
            "summary": "Een hypothese-gedreven onderzoeksbrief met veilige segmenten en zoekthema's.",
            "confidence": 0.62,
            "assumptions": [
                "De doelgroep bevindt zich primair in Nederland.",
                "De quiz en app zijn relevante onderdelen van de huidige klantreis.",
            ],
            "sources_needed": [
                "Actuele productvoorwaarden en prijs van het Bronze Plan",
                "Gevalideerde productfuncties en inclusies",
                "Toegestane promotierichtlijnen per gekozen community",
                "Geanonimiseerde Search Console- of advertentiezoektermdata",
            ],
            "deliverables": [
                {
                    "kind": "research_brief",
                    "channel": "research",
                    "title": f"Onderzoeksbrief – {campaign['name']}",
                    "content": (
                        "Onderzoek eerst de vragen, barrières en taal van mensen die gezond en "
                        "duurzaam willen afvallen. Gebruik openbare bronnen uitsluitend op "
                        "geaggregeerd onderwerpniveau. Prioriteer vragen over haalbaarheid, "
                        "routine, persoonlijke aansluiting en verantwoorde verwachtingen. "
                        "Verifieer productfuncties en voorwaarden voordat ze in verkoopcopy komen."
                    ),
                    "data_json": json.dumps(data, ensure_ascii=False),
                }
            ],
        }
