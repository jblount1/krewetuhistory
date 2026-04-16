from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..config import AppConfig
from ..models import ModerationAssessment, StoryPackage
from ..utils import excerpt


class AIClient:
    def classify_submission(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def moderate_submission(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def draft_story_package(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def review_story_dossier(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def draft_carousel_copy(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class OpenAIClient(AIClient):
    """Minimal HTTP client that requests JSON objects from the chat completions API."""

    def __init__(self, config: AppConfig) -> None:
        if not config.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI client.")
        self.config = config

    def _request_json(self, model: str, system_prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
            ],
        }
        request = urllib.request.Request(
            url=f"{self.config.openai_base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc
        content = response_payload["choices"][0]["message"]["content"]
        return json.loads(content)

    def classify_submission(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json(self.config.openai_model_classify, prompt, payload)

    def moderate_submission(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json(self.config.openai_model_moderate, prompt, payload)

    def draft_story_package(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json(self.config.openai_model_draft, prompt, payload)

    def review_story_dossier(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json(self.config.openai_model_classify, prompt, payload)

    def draft_carousel_copy(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json(self.config.openai_model_draft, prompt, payload)


class HeuristicAIClient(AIClient):
    """Deterministic fallback so the workflow stays testable without network access."""

    COMMUNITY_KEYWORDS = {
        "Vietnamese": ["vietnamese", "viet", "saigon"],
        "Jewish": ["jewish", "synagogue", "federation", "hebrew"],
        "Black / African Diaspora": ["african", "black", "congo square", "diaspora"],
        "Indigenous": ["indigenous", "tribe", "nation", "native"],
        "Muslim": ["masjid", "muslim", "islamic", "rahim"],
        "Latine": ["latino", "latina", "latine", "hispanic", "mexican", "cuban"],
    }
    THEME_KEYWORDS = {
        "migration": ["migration", "immigrant", "refugee", "diaspora", "arrival"],
        "culture and tradition": ["festival", "tradition", "ritual", "celebration"],
        "education": ["school", "student", "education", "classroom", "university"],
        "neighborhood history": ["neighborhood", "ward", "street", "trem", "marigny", "uptown"],
        "labor and civic life": ["labor", "union", "worker", "civic", "organizing"],
        "music and arts": ["music", "jazz", "drummer", "artist", "art", "performance"],
        "language and identity": ["language", "identity", "translation", "dialect"],
        "foodways": ["food", "kitchen", "restaurant", "market", "cuisine"],
        "public memory": ["memorial", "memory", "commemoration", "archive"],
        "global exchange": ["global", "exchange", "international", "trade", "connection"],
    }
    RISK_KEYWORDS = {
        "hateful_or_discriminatory_content": ["hate", "racial slur", "inferior race"],
        "explicit_sexual_content": ["sexual", "explicit", "pornographic", "nudity"],
        "graphic_violence": ["graphic violence", "gore", "bloodied", "dismembered"],
        "personal_attacks": ["idiot", "stupid", "worthless"],
        "doxxing_or_private_information": ["social security", "ssn", "home address", "phone number", "@gmail.com"],
        "copyright_or_permissions_concern": ["copyright", "all rights reserved", "permission pending", "used without permission"],
        "defamatory_claims": ["criminal", "fraud", "embezzled", "lied about"],
        "historical_verification_needed": ["legend says", "rumor", "unverified", "possibly true"],
        "off_topic_or_spam": ["buy now", "free bitcoin", "subscribe", "promotion"],
    }
    NEW_ORLEANS_KEYWORDS = ["new orleans", "nola", "crescent city", "lower ninth", "orleans parish"]
    TULANE_KEYWORDS = ["tulane", "green wave", "uptown campus", "newcomb"]
    GLOBAL_KEYWORDS = [
        "global",
        "diaspora",
        "immigrant",
        "migration",
        "international",
        "transnational",
        "caribbean",
        "latin america",
        "africa",
        "asia",
        "europe",
        "world",
    ]

    def classify_submission(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        del prompt
        text = self._evidence_text(payload)
        media_types = payload.get("media_types") or []
        flags = payload.get("deterministic_flags") or []
        community = self._pick_keyword_label(text, self.COMMUNITY_KEYWORDS) or "unknown"
        theme = self._pick_keyword_label(text, self.THEME_KEYWORDS) or "public memory"
        relevance = "likely_relevant" if self._mentions_project_context(text) else "uncertain"
        geographic = "New Orleans" if self._mentions_new_orleans(text) else None
        if "tulane" in text:
            tulane_connection = "yes"
        elif any(token in text for token in ("campus", "student center", "university")):
            tulane_connection = "possible"
        else:
            tulane_connection = "unknown"
        if any(media in media_types for media in ("audio", "video")) and "interview" in text:
            story_type = "oral_history"
        elif "presentation" in media_types:
            story_type = "slide_deck"
        elif "image" in media_types and len(media_types) == 1:
            story_type = "photo_story"
        else:
            story_type = "written_story"
        completeness = self._completeness(payload)
        risk_level = self._risk_level_from_flags(flags)
        notes = []
        if not payload.get("contributor_name"):
            notes.append("Contributor metadata missing or incomplete.")
        if payload.get("extracted_text_length", 0) < 150:
            notes.append("Limited textual evidence was available for classification.")
        recommended_next_step = self._classification_recommendation(relevance, risk_level, completeness, flags)
        return {
            "project_relevance": relevance,
            "community_label": community,
            "geographic_label": geographic,
            "tulane_connection": tulane_connection,
            "story_theme": theme,
            "story_type": story_type,
            "media_types": media_types,
            "completeness_status": completeness,
            "public_display_risk_level": risk_level,
            "recommended_next_step": recommended_next_step,
            "notes_for_human_reviewer": notes,
        }

    def moderate_submission(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        del prompt
        text = self._evidence_text(payload)
        flags = set(payload.get("deterministic_flags") or [])
        for flag, keywords in self.RISK_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                flags.add(flag)
        if any(flag in flags for flag in ("hateful_or_discriminatory_content", "explicit_sexual_content", "graphic_violence", "doxxing_or_private_information")):
            risk_level = "high"
            next_step = "sensitive_content_review"
        elif flags:
            risk_level = "medium"
            next_step = "needs_more_information"
        else:
            risk_level = "low"
            next_step = "ready_for_human_review"
        rationale = "No major public-display risks were detected." if not flags else "Flags were raised based on deterministic checks or keyword evidence."
        return {
            "flags": sorted(flags),
            "risk_level": risk_level,
            "rationale": rationale,
            "recommended_next_step": next_step,
        }

    def draft_story_package(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        del prompt
        filenames = payload.get("original_filenames") or []
        text = self._evidence_text(payload)
        title_seed = payload.get("story_title") or filenames[0] if filenames else "Untitled story"
        headline = self._headline_from_text(title_seed, text)
        summary = self._summary(text, max_words=50)
        narrative = self._narrative(text, summary)
        media_assets = filenames or ["No media assets attached"]
        captions = [f"Caption placeholder for {name}" for name in media_assets[:5]]
        community_label = payload.get("community_label") or "Community not yet confirmed"
        credits = f"Draft credits: contributor information pending; community context currently labeled as {community_label}."
        questions = list(payload.get("notes_for_human_reviewer") or [])
        if payload.get("rights_or_permission_status") in (None, "unstated"):
            questions.append("Confirm photo, recording, and publication permissions before public use.")
        if not payload.get("story_summary"):
            questions.append("Verify key historical claims and add source citations for the final display package.")
        return {
            "headline": headline,
            "summary_50": summary,
            "narrative_120_180": narrative,
            "associated_media_assets": media_assets,
            "suggested_image_caption_placeholders": captions,
            "suggested_credits_line": credits,
            "questions_or_gaps": questions,
            "display_format_recommendation": "touchscreen_story_card",
            "themes": [payload.get("story_theme") or "public memory"],
            "community_labels": [community_label],
        }

    def review_story_dossier(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        del prompt
        text = self._dossier_text(payload)
        flags = set()
        for flag, keywords in self.RISK_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                flags.add(flag)

        mentions_new_orleans = any(keyword in text for keyword in self.NEW_ORLEANS_KEYWORDS)
        mentions_tulane = any(keyword in text for keyword in self.TULANE_KEYWORDS)
        mentions_global = any(keyword in text for keyword in self.GLOBAL_KEYWORDS)
        mission_fit = sum([mentions_new_orleans, mentions_tulane, mentions_global]) >= 2
        unsafe = any(
            flag in flags
            for flag in (
                "hateful_or_discriminatory_content",
                "explicit_sexual_content",
                "graphic_violence",
                "doxxing_or_private_information",
                "off_topic_or_spam",
            )
        )

        if not text.strip():
            decision = "reject"
            notes = (
                "AI review could not verify dossier content because the dossier text was unavailable or blank."
            )
        elif unsafe:
            decision = "reject"
            notes = (
                "AI review rejected this submission because the dossier appears unsafe or inappropriate for public display."
            )
        elif not mission_fit:
            decision = "reject"
            notes = (
                "AI review rejected this submission because the dossier does not clearly connect Tulane, New Orleans, and the broader global community."
            )
        else:
            decision = "pass"
            notes = (
                "AI review found the dossier safe for editorial review and aligned with the project's mission."
            )

        return {
            "decision": decision,
            "ai_notes": notes,
            "mission_fit": mission_fit,
            "unsafe_or_inappropriate": unsafe,
            "risk_flags": sorted(flags),
        }

    def draft_carousel_copy(self, prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        del prompt
        title = payload.get("story_title") or "This story"
        theme = payload.get("theme") or "community history"
        keywords = payload.get("keywords") or []
        summary = excerpt(payload.get("summary") or "", limit=180)
        narrative = excerpt(payload.get("narrative") or "", limit=320)
        context = excerpt(payload.get("context_connections") or "", limit=220)

        keyword_line = ""
        if keywords:
            keyword_line = f" Look for threads of {', '.join(keywords[:3])} throughout the story."

        opening = f"Did you know? {title} opens a lively window into {theme.lower()}."
        middle = first_non_empty(
            [
                summary,
                narrative,
                context,
                "The more you know: this story reveals how local memory and public history travel across communities.",
            ]
        )
        closing = first_non_empty(
            [
                context,
                narrative,
                "It is a reminder that New Orleans and Tulane have always been shaped by wider global connections.",
            ]
        )
        ai_copy = f"{opening} {middle}{keyword_line} The more you know: {closing}".strip()
        return {"ai_copy": ai_copy}

    def _evidence_text(self, payload: Dict[str, Any]) -> str:
        parts = [
            " ".join(payload.get("original_filenames") or []),
            payload.get("combined_text") or "",
            " ".join(payload.get("notes_for_human_reviewer") or []),
        ]
        return " ".join(parts).lower()

    def _dossier_text(self, payload: Dict[str, Any]) -> str:
        parts = [
            payload.get("story_title") or "",
            payload.get("theme") or "",
            " ".join(payload.get("keywords") or []),
            payload.get("summary") or "",
            payload.get("narrative") or "",
            payload.get("context_connections") or "",
            payload.get("references") or "",
            payload.get("dossier_text") or "",
        ]
        return " ".join(parts).lower()

    def _pick_keyword_label(self, text: str, keyword_map: Dict[str, List[str]]) -> Optional[str]:
        for label, keywords in keyword_map.items():
            if any(keyword in text for keyword in keywords):
                return label
        return None

    def _mentions_project_context(self, text: str) -> bool:
        keywords = ["new orleans", "tulane", "community", "history", "historical", "global", "neighborhood"]
        return sum(1 for keyword in keywords if keyword in text) >= 2

    def _mentions_new_orleans(self, text: str) -> bool:
        return any(token in text for token in ("new orleans", "nola", "trem", "uptown", "marigny", "orleans parish"))

    def _completeness(self, payload: Dict[str, Any]) -> str:
        text_length = payload.get("extracted_text_length", 0)
        media_count = len(payload.get("media_types") or [])
        if text_length >= 300 or media_count >= 2:
            return "complete"
        if text_length > 0 or media_count > 0:
            return "partial"
        return "incomplete"

    def _risk_level_from_flags(self, flags: List[str]) -> str:
        if any(flag in flags for flag in ("hateful_or_discriminatory_content", "explicit_sexual_content", "graphic_violence", "doxxing_or_private_information")):
            return "high"
        if flags:
            return "medium"
        return "low"

    def _classification_recommendation(self, relevance: str, risk_level: str, completeness: str, flags: List[str]) -> str:
        if "exact_duplicate_hash" in flags:
            return "possible_duplicate"
        if risk_level == "high":
            return "sensitive_content_review"
        if completeness == "incomplete":
            return "technical_processing_needed"
        if relevance == "uncertain":
            return "needs_more_information"
        return "ready_for_human_review"

    def _headline_from_text(self, title_seed: str, text: str) -> str:
        cleaned = re.sub(r"\.[a-z0-9]+$", "", title_seed, flags=re.IGNORECASE).replace("_", " ").replace("-", " ").strip()
        if cleaned:
            return cleaned.title()
        return excerpt(text, limit=80).title() or "Untitled Story Draft"

    def _summary(self, text: str, max_words: int) -> str:
        words = excerpt(text, limit=400).split()
        if not words:
            return "Submission received with limited readable text; human review is needed to verify the story, context, and public-display suitability."
        return " ".join(words[:max_words]).strip()

    def _narrative(self, text: str, summary: str) -> str:
        words = excerpt(text, limit=1200).split()
        if not words:
            return (
                "This submission appears to contain potentially relevant historical material, but the available evidence is too limited to draft a reliable public-facing narrative. "
                "A human editor should review the original files, verify historical claims, confirm permissions, and expand the story before it is considered for presentation."
            )
        body = " ".join(words[:150])
        if len(body.split()) < 120:
            body = (
                f"{summary} This draft narrative is intentionally conservative because the intake package may be incomplete. "
                f"It appears to relate to local history, community memory, or Tulane-linked public storytelling, but factual verification, permissions review, and editorial refinement are still required. "
                f"Human reviewers should confirm names, dates, locations, and the intended historical framing before anything moves into the final presentation template."
            )
        return body


def build_ai_client(config: AppConfig) -> AIClient:
    if config.openai_api_key:
        return OpenAIClient(config)
    return HeuristicAIClient()


def first_non_empty(values: List[str]) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""
