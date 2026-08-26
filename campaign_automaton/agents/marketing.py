"""Marketing content agent for approval-gated affiliate drafts."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class MarketingAgent(BaseAgent):
    name = "MarketingAgent"
    objective = (
        "Create helpful, non-spammy Dutch content drafts that invite an informed next step "
        "toward the WegMetDieKilos quiz without promising outcomes."
    )

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        channels = context.get("requested_channels") or campaign.get("channels", [])
        tracking_urls = context.get("tracking_urls", {})
        deliverables: list[dict[str, str]] = []
        for channel in channels:
            link = tracking_urls.get(channel, campaign["product_url"])
            if channel == "blog":
                title = "Gezond afvallen begint met een plan dat bij je leven past"
                content = f"""# {title}

Een nieuwe afslankpoging begint vaak met enthousiasme, maar wordt pas waardevol als de aanpak ook op drukke, gewone dagen uitvoerbaar blijft. Richt je daarom niet op snelle beloften. Kijk eerst naar je huidige routine, de momenten waarop keuzes lastig worden en één kleine gewoonte die je deze week kunt testen.

## Drie vragen voor een realistische start

1. Welk gedrag wil je verbeteren zonder je hele dag om te gooien?
2. Welke omgeving of afspraak helpt je om dat gedrag vol te houden?
3. Hoe beoordeel je voortgang breder dan alleen met het getal op de weegschaal?

Een persoonlijk vertrekpunt kan helpen om keuzes overzichtelijk te maken. WegMetDieKilos presenteert een korte quiz die rekening houdt met je leeftijd en je naar een persoonlijk plan leidt. Bekijk rustig of de aanpak bij je past en lees altijd de voorwaarden.

[Start de drie-minutenquiz]({link})

Dit is algemene leefstijlinformatie en geen medisch advies. Bespreek gezondheidsklachten, medicatie, zwangerschap of een eetstoornis met een gekwalificeerde zorgprofessional."""
                kind = "blog_article"
                data = {"primary_intent": "gezond afvallen", "cta": "quiz"}
            elif channel == "email":
                title = "E-maildraft: een haalbare eerste stap"
                content = f"""Onderwerp: Welke kleine stap past deze week bij jou?

Hallo {{voornaam}},

Gezonder leven hoeft niet te beginnen met een perfect schema. Kies één gewoonte die concreet, haalbaar en meetbaar is. Denk aan een vast moment voor een wandeling, een eenvoudige maaltijdvoorbereiding of eerder naar bed gaan.

Wil je eerst verkennen welk soort plan bij jouw levensfase kan passen? De WegMetDieKilos-quiz duurt volgens de aanbieders ongeveer drie minuten. Bekijk de uitkomst kritisch en controleer de voorwaarden voordat je beslist.

Bekijk de quiz: {link}

Je ontvangt dit bericht omdat je je hebt aangemeld voor leefstijltips. Afmelden kan via de uitschrijflink onderaan iedere e-mail."""
                kind = "email_sequence"
                data = {"sequence_step": 1, "audience": "opt-in only"}
            elif channel == "social":
                title = "Social post: kleine stap, persoonlijk vertrekpunt"
                content = f"""Gezond afvallen begint zelden met een extreme verandering. Welke kleine gewoonte zou jouw week al iets makkelijker maken?

Wie behoefte heeft aan meer structuur, kan de korte WegMetDieKilos-quiz bekijken en beoordelen of het voorgestelde plan aansluit. Geen snelle belofte, wel een bewust vertrekpunt.

{link}"""
                kind = "social_post"
                data = {"format": "organic", "platform_adaptation_required": True}
            elif channel == "landing_page":
                title = "Landingspagina: ontdek een persoonlijk vertrekpunt"
                content = f"""# Ontdek welk vertrekpunt bij jouw levensfase past

Geen wondermiddel en geen garantie op een bepaald resultaat. Wel een korte quiz die je helpt verkennen welk persoonlijk afslankplan mogelijk bij je situatie aansluit.

## Wat je vooraf kunt doen

- Bepaal welk doel voor jou realistisch en verantwoord voelt.
- Bekijk of de aanpak past bij je dagelijkse routine.
- Lees de voorwaarden, privacy-informatie en het restitutiebeleid.
- Vraag professioneel advies bij medische vragen of bijzondere omstandigheden.

[Doe de drie-minutenquiz]({link})"""
                kind = "landing_page_copy"
                data = {"cta": "quiz", "claims_level": "conservative"}
            elif channel == "community":
                title = "Communitybijdrage: waarde-eerst antwoord"
                content = (
                    "Begin met een inhoudelijk antwoord op de concrete vraag van het lid. "
                    "Noem een affiliatelink alleen als de communityregels dit toestaan, de link "
                    "direct relevant is en de affiliaterelatie duidelijk wordt vermeld. Plaats "
                    "nooit dezelfde reactie in meerdere groepen en stuur geen ongevraagde DM."
                )
                kind = "community_response_template"
                data = {"requires_rule_check": True, "requires_question_context": True}
            else:
                continue
            deliverables.append(
                {
                    "kind": kind,
                    "channel": channel,
                    "title": title,
                    "content": content,
                    "data_json": json.dumps(data, ensure_ascii=False),
                }
            )
        return {
            "summary": f"{len(deliverables)} kanaalspecifieke concepten gegenereerd.",
            "confidence": 0.7,
            "assumptions": [
                "De opgegeven product- en trackinglink is door de eigenaar gecontroleerd.",
                "De huidige quizpositionering blijft actief.",
            ],
            "sources_needed": [
                "Definitieve prijs en Bronze Plan-inhoud voor eventuele uitgebreidere productcopy",
                "Merkrichtlijnen en goedgekeurde visuele assets",
            ],
            "deliverables": deliverables,
        }
