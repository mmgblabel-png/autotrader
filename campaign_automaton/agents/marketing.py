"""Responsible, product-specific campaign marketing drafts."""

from __future__ import annotations

import json
from typing import Any

from campaign_automaton.agents.base import BaseAgent


class MarketingAgent(BaseAgent):
    name = "MarketingAgent"
    objective = (
        "Create helpful, non-spammy Dutch content drafts that describe the current campaign's "
        "verified product facts, invite an informed next step, and never promise outcomes."
    )

    @staticmethod
    def _facts(campaign: dict[str, Any]) -> list[str]:
        facts = [str(item).strip() for item in campaign.get("product_facts", [])]
        return [fact for fact in facts if fact]

    def deterministic(
        self, campaign: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        channels = context.get("requested_channels") or campaign.get("channels", [])
        tracking_urls = context.get("tracking_urls", {})
        product_name = str(campaign["product_name"])
        facts = self._facts(campaign)
        fact_list = "\n".join(f"- {fact}" for fact in facts[:5]) or (
            "- Controleer de informatie, voorwaarden en privacyverklaring van de aanbieder."
        )
        safe_context = (
            "Deze informatie is bedoeld om rustig te vergelijken en is geen medisch, financieel "
            "of persoonlijk advies."
        )
        deliverables: list[dict[str, str]] = []
        for channel in channels:
            link = tracking_urls.get(channel, campaign["product_url"])
            if channel == "blog":
                title = f"{product_name}: eerst vergelijken, dan pas kiezen"
                content = f"""# {title}

Wie zich oriënteert op {product_name} hoeft niet meteen te beslissen. Begin met wat je zoekt, hoeveel tijd je realistisch wilt vrijmaken en welke informatie je nodig hebt om een bewuste keuze te maken. {safe_context}

## Wat we uit de aanbiederinformatie kunnen bevestigen

{fact_list}

## Een rustige manier om te beoordelen

1. Lees de productbeschrijving en voorwaarden volledig.
2. Vergelijk het aanbod met je eigen doel, budget en beschikbare tijd.
3. Controleer privacy-, annulerings- en restitutievoorwaarden voordat je beslist.
4. Vraag gekwalificeerd advies als je medische vragen of bijzondere omstandigheden hebt.

[Lees de productinformatie en voorwaarden]({link})

{safe_context}"""
                kind = "blog_article"
                data = {"primary_intent": "informed_product_research", "cta": "product_information"}
            elif channel == "email":
                title = f"E-maildraft: rustig kennismaken met {product_name}"
                content = f"""Onderwerp: Past {product_name} bij wat jij zoekt?

Hallo {{voornaam}},

Een goed aanbod hoeft niet voor iedereen de juiste keuze te zijn. Neem daarom eerst de tijd om de inhoud, voorwaarden en praktische verwachtingen van {product_name} te bekijken.

Wat je kunt controleren:
{fact_list}

Lees de informatie kritisch en besluit alleen als dit aansluit bij jouw situatie.

Bekijk de productinformatie: {link}

{safe_context}

Je ontvangt dit bericht alleen als je je hebt aangemeld voor relevante informatie. Afmelden kan via de uitschrijflink onderaan iedere e-mail."""
                kind = "email_sequence"
                data = {"sequence_step": 1, "audience": "opt-in only"}
            elif channel == "social":
                title = f"Social draft: rustig vergelijken met {product_name}"
                content = f"""Niet elk aanbod past bij iedereen. Als je {product_name} verkent, lees dan eerst de inhoud, voorwaarden en praktische verwachtingen.

Een paar feiten uit de aanbiederinformatie:
{fact_list}

Bekijk rustig of dit bij je past: {link}

{safe_context}"""
                kind = "social_post"
                data = {"format": "organic", "platform_adaptation_required": True}
            elif channel == "landing_page":
                title = f"Landingspagina: {product_name} rustig verkennen"
                content = f"""# {product_name} rustig verkennen

Geen wondermiddel en geen garantie op een bepaald resultaat. Wel een overzichtelijk vertrekpunt om de productinformatie, voorwaarden en praktische verwachtingen rustig te bekijken.

## Wat we uit de aanbiederinformatie kunnen bevestigen

{fact_list}

## Controleer dit voordat je kiest

- Past de inhoud bij wat je zoekt en bij de tijd die je beschikbaar hebt?
- Lees de voorwaarden, privacy-informatie en restitutiebeleid.
- Baseer je keuze niet op testimonials, haast of beloofde uitkomsten.
- Vraag professioneel advies bij medische vragen of bijzondere omstandigheden.

[Lees de productinformatie]({link})

{safe_context}"""
                kind = "landing_page_copy"
                data = {"cta": "product_information", "claims_level": "conservative"}
            elif channel == "community":
                title = f"Communitytemplate: relevante context voor {product_name}"
                content = (
                    "Begin met een inhoudelijk antwoord op de concrete vraag van het lid. "
                    f"Noem {product_name} alleen als het direct relevant is, de communityregels dit "
                    "toestaan en de affiliaterelatie duidelijk wordt vermeld. Plaats nooit dezelfde "
                    "reactie in meerdere groepen en stuur geen ongevraagde DM."
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
            "summary": f"{len(deliverables)} product-specifieke concepten gegenereerd voor {product_name}.",
            "confidence": 0.7,
            "assumptions": [
                "De opgegeven productfeiten en trackinglink zijn door de eigenaar gecontroleerd.",
                "Alle externe publicatie blijft onderworpen aan afzonderlijke eigenaarstoestemming.",
            ],
            "sources_needed": [
                "Actuele productvoorwaarden en restitutiebeleid van de aanbieder",
                "Merkrichtlijnen en goedgekeurde visuele assets",
            ],
            "deliverables": deliverables,
        }
