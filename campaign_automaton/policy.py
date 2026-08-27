from __future__ import annotations

import re
from dataclasses import dataclass

from campaign_automaton.config import Settings
from campaign_automaton.models import PolicyFinding, PolicyResult


@dataclass(slots=True)
class EvaluatedContent:
    content: str
    result: PolicyResult


class PolicyEngine:
    """Apply deterministic guardrails before an artifact can be saved or approved."""

    GUARANTEED_CLAIMS = (
        r"\bgegarandeerd\b",
        r"\b100\s*%\s*(?:resultaat|succes)\b",
        r"\bverlies\s+\d+\s*(?:kg|kilo)\s+(?:in|binnen)\b",
        r"\bzonder\s+(?:inspanning|moeite|dieet|bewegen)\b",
        r"\bwondermiddel\b",
        r"\bvet\s*(?:smelt|verdwijnt)\b",
        r"\bblijvend\s+resultaat\s+gegarandeerd\b",
        r"\bgeneest\b",
        r"\bbehandelt\s+(?:obesitas|diabetes|een\s+ziekte)\b",
        r"\bguaranteed\b",
        r"\b(?:cure|treat|prevent)\s+(?:disease|illness|acne|diabetes|obesity)\b",
        r"\b(?:guarantees?|will)\s+(?:improve|boost|increase)\s+(?:hydration|fitness|health|performance|productivity)\b",
    )
    SPAM_SIGNALS = (
        r"!!!+",
        r"\bkoop\s+nu\b.{0,20}\bkoop\s+nu\b",
        r"\bbuy\s+now\b.{0,20}\bbuy\s+now\b",
        r"\bstuur\s+dit\s+naar\s+iedereen\b",
        r"\bshare\s+(?:this|it)\s+with\s+everyone\b",
        r"\bgekochte\s+e-?maillijst\b",
        r"\bpurchased\s+(?:email\s+)?list\b",
        r"\bscrape\b.{0,30}\b(?:emails|profielen|leden|emails|profiles|members)\b",
        r"\bongevraagd\b.{0,20}\b(?:mail|dm|bericht)\b",
        r"\bunsolicited\b.{0,20}\b(?:email|dm|message)\b",
    )
    PERSONAL_DATA_SIGNALS = (
        r"\b(?:bsn|rijksregisternummer|paspoortnummer)\b",
        r"\bmedisch\s+dossier\b",
        r"\bkoop\s+(?:leads|contactgegevens|e-?maillijst)\b",
        r"\b(?:social security|passport)\s+number\b",
        r"\bbuy\s+(?:leads|contact\s+details|email\s+list)\b",
    )
    AFFILIATE_DISCLOSURE_MARKERS = (
        "affiliate disclosure",
        "affiliate-link",
        "commissie ontvangen",
        "affiliate link",
        "as an amazon associate i earn from qualifying purchases",
        "(paid link)",
    )
    AMAZON_REVIEW_OR_RATING_SIGNALS = (
        r"\b\d(?:\.\d)?\s*(?:out of|/)\s*5\s*(?:stars|sterren)\b",
        r"\b\d[\d,.]*\s*(?:customer\s+)?(?:reviews|ratings|beoordelingen)\b",
        r"\bcustomers\s+say\b",
        r"\bklanten\s+zeggen\b",
        r"\bamazon['’]?s\s+choice\b",
    )
    AMAZON_REDIRECT_SIGNALS = (
        r"https?://[^\s)]+/r/[a-z0-9-]+",
        r"\b(?:auto(?:matic)?\s+redirect|redirecting\s+page|link\s+cloaking|cloak(?:ed|ing)?)\b",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _matches_unnegated(pattern: str, text: str) -> bool:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            prefix = text[max(0, match.start() - 20) : match.start()]
            if re.search(r"(?:geen|niet|no|not)\s+$", prefix, re.IGNORECASE):
                continue
            return True
        return False

    def evaluate_content(
        self,
        content: str,
        *,
        channel: str,
        sales_intent: bool = True,
        add_disclosure: bool = True,
    ) -> EvaluatedContent:
        findings: list[PolicyFinding] = []
        lowered = content.lower()
        for pattern in self.GUARANTEED_CLAIMS:
            if self._matches_unnegated(pattern, lowered):
                findings.append(
                    PolicyFinding(
                        code="unsupported_outcome_claim",
                        severity="block",
                        message="Content contains a guaranteed, medical, or unsupported outcome claim.",
                    )
                )
                break
        for pattern in self.SPAM_SIGNALS:
            if re.search(pattern, lowered, re.IGNORECASE | re.DOTALL):
                findings.append(
                    PolicyFinding(
                        code="spam_pattern",
                        severity="block",
                        message="Content or instructions contain a prohibited spam pattern.",
                    )
                )
                break
        for pattern in self.PERSONAL_DATA_SIGNALS:
            if re.search(pattern, lowered, re.IGNORECASE | re.DOTALL):
                findings.append(
                    PolicyFinding(
                        code="personal_data_abuse",
                        severity="block",
                        message="Content requests sensitive data or non-consensual contact acquisition.",
                    )
                )
                break
        if channel == "email" and not any(
            marker in lowered for marker in ("opt-in", "unsubscribe", "uitschrijven", "afmelden")
        ):
            findings.append(
                PolicyFinding(
                    code="email_consent_reminder",
                    severity="warn",
                    message="Email drafts must only be sent to an opt-in list and need an unsubscribe route.",
                )
            )

        disclosure_added = False
        normalized = content.strip()
        if sales_intent and not any(marker in lowered for marker in self.AFFILIATE_DISCLOSURE_MARKERS):
            if add_disclosure:
                normalized = f"{normalized}\n\n{self.settings.affiliate_disclosure}"
                disclosure_added = True
            else:
                findings.append(
                    PolicyFinding(
                        code="affiliate_disclosure_missing",
                        severity="block",
                        message="Sales-oriented affiliate content must include a clear disclosure.",
                    )
                )

        if self.settings.affiliate_provider == "amazon" and sales_intent:
            if not self.settings.amazon_associate_url:
                findings.append(
                    PolicyFinding(
                        code="amazon_special_link_missing",
                        severity="block",
                        message="Amazon product CTAs remain draft-only until an owner supplies an exact Associates Special Link.",
                    )
                )
            for pattern in self.AMAZON_REVIEW_OR_RATING_SIGNALS:
                if re.search(pattern, normalized, re.IGNORECASE):
                    findings.append(
                        PolicyFinding(
                            code="amazon_review_or_rating_reuse",
                            severity="block",
                            message="Do not reuse Amazon customer reviews or star ratings without an approved Amazon data source.",
                        )
                    )
                    break
            for pattern in self.AMAZON_REDIRECT_SIGNALS:
                if re.search(pattern, normalized, re.IGNORECASE):
                    findings.append(
                        PolicyFinding(
                            code="amazon_redirect_or_cloaking_risk",
                            severity="block",
                            message="Amazon Special Links must be direct and must not be cloaked or routed through a redirect page.",
                        )
                    )
                    break

        if "doctor" not in lowered and "dokter" not in lowered and any(
            phrase in lowered
            for phrase in ("medical", "medication", "diabetes", "pregnant", "medisch", "medicatie", "zwanger")
        ):
            findings.append(
                PolicyFinding(
                    code="medical_context_warning",
                    severity="warn",
                    message="Medical-context content should advise consultation with a qualified professional.",
                )
            )
        allowed = not any(finding.severity == "block" for finding in findings)
        return EvaluatedContent(
            content=normalized,
            result=PolicyResult(
                allowed=allowed,
                findings=findings,
                disclosure_added=disclosure_added,
            ),
        )

    def evaluate_action(self, action: str, context: dict) -> PolicyResult:
        findings: list[PolicyFinding] = []
        if action in {"publish", "send_email", "send_dm", "post_social"}:
            if self.settings.draft_only:
                findings.append(
                    PolicyFinding(
                        code="draft_only_mode",
                        severity="block",
                        message="Outbound publishing is disabled; a human must approve and export drafts.",
                    )
                )
            if not context.get("human_confirmed"):
                findings.append(
                    PolicyFinding(
                        code="human_confirmation_required",
                        severity="block",
                        message="A human confirmation is required for outbound actions.",
                    )
                )
        if action in {"scrape_profiles", "buy_leads", "unsolicited_email", "unsolicited_dm"}:
            findings.append(
                PolicyFinding(
                    code="prohibited_acquisition_method",
                    severity="block",
                    message="Non-consensual acquisition and unsolicited outreach are prohibited.",
                )
            )
        if self.settings.affiliate_provider == "amazon" and action in {
            "cloak_link", "redirect_affiliate_link", "auto_redirect_to_amazon", "purchase_on_behalf"
        }:
            findings.append(
                PolicyFinding(
                    code="amazon_prohibited_action",
                    severity="block",
                    message="Amazon campaign links must be direct and customers must make their own transactions.",
                )
            )
        return PolicyResult(
            allowed=not any(finding.severity == "block" for finding in findings),
            findings=findings,
        )
