"""Content and action policy engine for ethical affiliate marketing."""

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
    )
    SPAM_SIGNALS = (
        r"!!!+",
        r"\bkoop\s+nu\b.{0,20}\bkoop\s+nu\b",
        r"\bstuur\s+dit\s+naar\s+iedereen\b",
        r"\bgekochte\s+e-?maillijst\b",
        r"\bscrape\b.{0,30}\b(?:emails|profielen|leden)\b",
        r"\bongevraagd\b.{0,20}\b(?:mail|dm|bericht)\b",
    )
    PERSONAL_DATA_SIGNALS = (
        r"\b(?:bsn|rijksregisternummer|paspoortnummer)\b",
        r"\bmedisch\s+dossier\b",
        r"\bkoop\s+(?:leads|contactgegevens|e-?maillijst)\b",
    )
    AFFILIATE_DISCLOSURE_MARKERS = (
        "affiliate disclosure",
        "affiliate-link",
        "commissie ontvangen",
        "affiliate link",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _matches_unnegated(pattern: str, text: str) -> bool:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            prefix = text[max(0, match.start() - 20) : match.start()]
            if re.search(r"(?:geen|niet)\s+$", prefix, re.IGNORECASE):
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
                        code="unsupported_weight_loss_claim",
                        severity="block",
                        message="Content contains a guaranteed, medical, or implausible weight-loss claim.",
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
            marker in lowered for marker in ("opt-in", "uitschrijven", "afmelden")
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
        if "dokter" not in lowered and any(
            phrase in lowered for phrase in ("medisch", "medicatie", "diabetes", "zwanger")
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
        return PolicyResult(
            allowed=not any(finding.severity == "block" for finding in findings),
            findings=findings,
        )
