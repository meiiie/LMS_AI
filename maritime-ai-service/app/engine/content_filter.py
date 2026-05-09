"""
Content Filter — SOTA Vietnamese Content Moderation

Sprint 76: Multi-layer content filter with:
- Text normalization (diacritics, leetspeak, teencode, repeats)
- 120+ profanity entries organized by 5 severity levels
- Domain-aware allowlists (maritime/traffic terms)
- Word-boundary matching for short ambiguous words

Architecture:
    User Message → TextNormalizer.normalize()
                 → ContentFilter.check(original, normalized, domain_id)
                 → FilterResult(severity, action, matched_terms)
"""

import re
import logging
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# =============================================================================
# SEVERITY LEVELS
# =============================================================================

class Severity(IntEnum):
    ALLOW = 1
    FLAG = 2
    WARN = 3
    BLOCK = 4
    HARD_BLOCK = 5


SEVERITY_TO_ACTION = {
    Severity.ALLOW: "ALLOW",
    Severity.FLAG: "FLAG",
    Severity.WARN: "WARN",
    Severity.BLOCK: "BLOCK",
    Severity.HARD_BLOCK: "HARD_BLOCK",
}


# =============================================================================
# MATCH TYPES
# =============================================================================

class MatchType(IntEnum):
    SUBSTRING = 1
    WORD_BOUNDARY = 2
    EXACT = 3


# =============================================================================
# FILTER RESULT
# =============================================================================

@dataclass
class FilterResult:
    """Result of content filtering."""
    severity: int = Severity.ALLOW
    action: str = "ALLOW"
    matched_terms: List[str] = field(default_factory=list)
    normalized_text: str = ""
    domain_override: bool = False


# =============================================================================
# TEXT NORMALIZER
# =============================================================================

class TextNormalizer:
    """
    Normalize Vietnamese text for content matching.

    Pipeline: lowercase → strip diacritics → decode leetspeak
              → expand teencode → collapse repeats
    """

    # Leetspeak mappings
    _LEETSPEAK: Dict[str, str] = {
        "@": "a",
        "4": "a",
        "3": "e",
        "0": "o",
        "1": "i",
        "$": "s",
        "7": "t",
        "!": "i",
    }

    # Vietnamese teencode → full word (normalized, no diacritics)
    _TEENCODE: Dict[str, str] = {
        "ko": "khong",
        "k": "khong",
        "dc": "duoc",
        "dk": "duoc",
        "đc": "duoc",
        "ntn": "nhu the nao",
        "ns": "noi",
        "bt": "binh thuong",
        "bn": "bao nhieu",
        "bh": "bao gio",
        "mn": "moi nguoi",
        "mk": "minh",
        "m": "may",
        "t": "tao",
        "j": "gi",
        "gj": "gi",
        "r": "roi",
        "oy": "roi",
        "ak": "a",
        "nha": "nhe",
        "tks": "thanks",
        "pls": "please",
        "plz": "please",
        "wtf": "what the fuck",
        "omg": "oh my god",
        "lmao": "laughing",
        "vcl": "vai ca lon",
        "vl": "vai lon",
        "vkl": "vai ca lon",
        "dmm": "dit me may",
        "dcm": "dit con me",
        "clm": "con lon me",
        "cc": "con cac",
        "ml": "mat lon",
        "cmm": "con me may",
        "đmm": "dit me may",
        "đcm": "dit con me",
        "dkm": "dit con me",
    }

    # Teencode patterns that should only match as whole words
    _TEENCODE_WHOLE_WORD = {"k", "m", "t", "j", "r"}

    @staticmethod
    def strip_diacritics(text: str) -> str:
        """Strip Vietnamese diacritics. Reuses pattern from router.py."""
        text = text.replace("đ", "d").replace("Đ", "D")
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    @classmethod
    def decode_leetspeak(cls, text: str) -> str:
        """Decode leetspeak characters: @→a, 3→e, 0→o, etc."""
        result = []
        for ch in text:
            result.append(cls._LEETSPEAK.get(ch, ch))
        return "".join(result)

    @classmethod
    def expand_teencode(cls, text: str) -> str:
        """Expand Vietnamese teencode abbreviations."""
        words = text.split()
        result = []
        for word in words:
            lower_word = word.lower()
            if lower_word in cls._TEENCODE:
                if lower_word in cls._TEENCODE_WHOLE_WORD:
                    result.append(cls._TEENCODE[lower_word])
                else:
                    result.append(cls._TEENCODE[lower_word])
            else:
                result.append(word)
        return " ".join(result)

    @staticmethod
    def collapse_repeats(text: str) -> str:
        """Collapse repeated characters: nguuuu→nguu, fuckkkk→fuckk."""
        return re.sub(r"(.)\1{2,}", r"\1\1", text)

    @classmethod
    def normalize(cls, text: str) -> str:
        """
        Full normalization pipeline.

        Order matters:
        1. lowercase + strip whitespace
        2. strip diacritics (đéo → deo)
        3. decode leetspeak (@ss → ass)
        4. expand teencode (ko → khong)
        5. collapse repeats (nguuuu → nguu)
        """
        text = text.lower().strip()
        text = cls.strip_diacritics(text)
        text = cls.decode_leetspeak(text)
        text = cls.expand_teencode(text)
        text = cls.collapse_repeats(text)
        return text


# =============================================================================
# WORD LISTS — organized by severity
# =============================================================================

# Each entry: (normalized_pattern, severity, match_type)
# All patterns are already in normalized form (no diacritics, lowercase)

_WORD_LIST: List[tuple] = [
    # ---- HARD_BLOCK (5): Threats, CSAM, terrorism ----
    ("khung bo", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("che tao bom", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("lam bom", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("thuoc no", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("child porn", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("cp link", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("tan cong truong hoc", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("xa sung", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("giet nguoi hang loat", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("cach giet nguoi", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("cach tu tu", Severity.HARD_BLOCK, MatchType.SUBSTRING),
    ("huong dan tu tu", Severity.HARD_BLOCK, MatchType.SUBSTRING),

    # ---- BLOCK (4): Heavy vulgar, sexual harassment ----
    # Sexual/vulgar
    ("dit me", Severity.BLOCK, MatchType.SUBSTRING),
    ("dit con me", Severity.BLOCK, MatchType.SUBSTRING),
    ("dit me may", Severity.BLOCK, MatchType.SUBSTRING),
    ("du me", Severity.BLOCK, MatchType.SUBSTRING),
    ("du ma", Severity.BLOCK, MatchType.SUBSTRING),
    ("dcm", Severity.BLOCK, MatchType.SUBSTRING),
    ("dmm", Severity.BLOCK, MatchType.SUBSTRING),
    ("dkm", Severity.BLOCK, MatchType.SUBSTRING),
    ("clm", Severity.BLOCK, MatchType.SUBSTRING),
    ("cmm", Severity.BLOCK, MatchType.SUBSTRING),
    ("con cac", Severity.BLOCK, MatchType.SUBSTRING),
    # Standalone "cac" is too ambiguous after diacritic stripping because
    # the normal Vietnamese plural marker "các" also normalizes to "cac".
    # Keep contextual vulgar phrases blocked, but do not hard-block the lone token.
    ("buoi", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    ("lon", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    ("vai ca lon", Severity.BLOCK, MatchType.SUBSTRING),
    ("vai lon", Severity.BLOCK, MatchType.SUBSTRING),
    ("vcl", Severity.BLOCK, MatchType.SUBSTRING),
    ("vkl", Severity.BLOCK, MatchType.SUBSTRING),
    ("vl", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    ("dit", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    ("deo", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    ("d.m", Severity.BLOCK, MatchType.SUBSTRING),
    ("con di", Severity.BLOCK, MatchType.SUBSTRING),
    ("thang cho", Severity.BLOCK, MatchType.SUBSTRING),
    ("con cho", Severity.BLOCK, MatchType.SUBSTRING),
    ("do cho de", Severity.BLOCK, MatchType.SUBSTRING),
    ("mat lon", Severity.BLOCK, MatchType.SUBSTRING),
    ("ml", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    # Family insults
    ("bo me may", Severity.BLOCK, MatchType.SUBSTRING),
    ("me may", Severity.BLOCK, MatchType.SUBSTRING),
    ("cha may", Severity.BLOCK, MatchType.SUBSTRING),
    ("ca nha may", Severity.BLOCK, MatchType.SUBSTRING),
    # English vulgar
    ("fuck", Severity.BLOCK, MatchType.SUBSTRING),
    ("motherfucker", Severity.BLOCK, MatchType.SUBSTRING),
    ("asshole", Severity.BLOCK, MatchType.SUBSTRING),
    ("bitch", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    ("nigger", Severity.BLOCK, MatchType.SUBSTRING),
    ("nigga", Severity.BLOCK, MatchType.SUBSTRING),
    # Violence
    ("chet di", Severity.BLOCK, MatchType.SUBSTRING),
    ("giet", Severity.BLOCK, MatchType.WORD_BOUNDARY),
    ("giet may", Severity.BLOCK, MatchType.SUBSTRING),
    ("dam chet", Severity.BLOCK, MatchType.SUBSTRING),
    ("che dau", Severity.BLOCK, MatchType.SUBSTRING),
    ("cat co", Severity.BLOCK, MatchType.SUBSTRING),
    # Prompt injection
    ("ignore previous instructions", Severity.BLOCK, MatchType.SUBSTRING),
    ("ignore all instructions", Severity.BLOCK, MatchType.SUBSTRING),
    ("ignore your instructions", Severity.BLOCK, MatchType.SUBSTRING),
    ("disregard previous", Severity.BLOCK, MatchType.SUBSTRING),
    ("system prompt", Severity.BLOCK, MatchType.SUBSTRING),
    ("reveal your prompt", Severity.BLOCK, MatchType.SUBSTRING),
    ("show me your instructions", Severity.BLOCK, MatchType.SUBSTRING),
    ("jailbreak", Severity.BLOCK, MatchType.SUBSTRING),
    ("malware", Severity.BLOCK, MatchType.SUBSTRING),

    # ---- WARN (3): Moderate profanity, insults ----
    ("ngu", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("do ngu", Severity.WARN, MatchType.SUBSTRING),
    ("thang ngu", Severity.WARN, MatchType.SUBSTRING),
    ("con ngu", Severity.WARN, MatchType.SUBSTRING),
    ("ngu lam", Severity.WARN, MatchType.SUBSTRING),
    ("ngu vai", Severity.WARN, MatchType.SUBSTRING),
    ("khon nan", Severity.WARN, MatchType.SUBSTRING),
    ("mat day", Severity.WARN, MatchType.SUBSTRING),
    ("vo hoc", Severity.WARN, MatchType.SUBSTRING),
    ("do dien", Severity.WARN, MatchType.SUBSTRING),
    ("thang dien", Severity.WARN, MatchType.SUBSTRING),
    ("con dien", Severity.WARN, MatchType.SUBSTRING),
    ("mat dat", Severity.WARN, MatchType.SUBSTRING),
    ("do ranh", Severity.WARN, MatchType.SUBSTRING),
    ("thang ranh", Severity.WARN, MatchType.SUBSTRING),
    ("do ngoc", Severity.WARN, MatchType.SUBSTRING),
    ("tu tu", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("tu sat", Severity.WARN, MatchType.SUBSTRING),
    ("shit", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("wtf", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("damn", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("shut up", Severity.WARN, MatchType.SUBSTRING),
    ("stupid", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("idiot", Severity.WARN, MatchType.WORD_BOUNDARY),
    # Weapons (standalone, not in maritime context)
    ("vu khi", Severity.WARN, MatchType.SUBSTRING),
    ("pha huy", Severity.WARN, MatchType.SUBSTRING),
    ("tan cong", Severity.WARN, MatchType.SUBSTRING),
    # Prompt injection (softer)
    ("hack", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("inject", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("exploit", Severity.WARN, MatchType.WORD_BOUNDARY),
    ("ignore previous", Severity.WARN, MatchType.SUBSTRING),

    # ---- FLAG (2): Aggressive pronouns, ambiguous ----
    ("tao", Severity.FLAG, MatchType.WORD_BOUNDARY),
    ("may", Severity.FLAG, MatchType.WORD_BOUNDARY),
]


# =============================================================================
# DOMAIN ALLOWLISTS
# =============================================================================

# Normalized terms that are safe in educational domain contexts.
# These override WARN/FLAG matches (but NOT BLOCK/HARD_BLOCK).

DOMAIN_ALLOWLISTS: Dict[str, Set[str]] = {
    "maritime": {
        "cuop bien", "hai tac", "piracy", "pirate",
        "va cham", "collision", "dam va",
        "tai nan", "accident", "grounding",
        "chim tau", "sinking", "capsizing",
        "pha nuoc", "man overboard",
        "tan cong hai tac", "pirate attack",
        "vu khi", "attack",
        "giet", "cat",
        "pha huy",
    },
    "traffic_law": {
        "tai nan", "accident",
        "va cham", "collision",
        "dam xe", "tong xe",
        "chet nguoi",
        "tan cong",
        "vu khi",
    },
}


# =============================================================================
# CONTENT FILTER
# =============================================================================

class ContentFilter:
    """
    Multi-layer Vietnamese content filter.

    Checks text against normalized word lists with severity levels.
    Supports domain-aware allowlists for educational contexts.
    """

    def __init__(self, domain_id: Optional[str] = None):
        self._domain_id = domain_id
        self._allowlist: Set[str] = set()
        if domain_id and domain_id in DOMAIN_ALLOWLISTS:
            self._allowlist = DOMAIN_ALLOWLISTS[domain_id]

    @staticmethod
    def _is_buoi_context_false_positive(original_text: str, normalized_text: str) -> bool:
        """Avoid conflating safe "buoi" contexts with the vulgar standalone token.

        Vietnamese users often write without diacritics. After normalization,
        "buổi" (session/meeting) and a vulgar token both collapse to "buoi".
        Keep blocking standalone abuse, but allow common educational/work
        contexts such as "buổi học" or "buổi báo cáo".
        """
        safe_contexts = (
            "buoi hoc",
            "buoi bao cao",
            "buoi thuyet trinh",
            "buoi trinh bay",
            "buoi hop",
            "buoi thi",
            "buoi sang",
            "buoi chieu",
            "buoi toi",
            "buoi trua",
            "buoi dao tao",
            "buoi huan luyen",
            "buoi thuc hanh",
            "buoi seminar",
            "buoi workshop",
            "buoi truc",
        )
        if any(context in normalized_text for context in safe_contexts):
            return True

        original = unicodedata.normalize("NFC", original_text.lower())
        tokens = re.findall(r"[\wÀ-ỹ]+", original, flags=re.UNICODE)
        buoi_like_tokens = [
            token for token in tokens if TextNormalizer.normalize(token) == "buoi"
        ]
        if not buoi_like_tokens:
            return False

        safe_original_forms = {"buổi", "bưởi"}
        return all(token in safe_original_forms for token in buoi_like_tokens)

    def check(self, text: str) -> FilterResult:
        """
        Check text for inappropriate content.

        Returns FilterResult with highest severity match.
        """
        if not text or not text.strip():
            return FilterResult(normalized_text="")

        normalized = TextNormalizer.normalize(text)

        matched_terms: List[str] = []
        max_severity = Severity.ALLOW
        domain_override = False

        for pattern, severity, match_type in _WORD_LIST:
            if self._matches(normalized, pattern, match_type):
                if pattern == "buoi" and self._is_buoi_context_false_positive(
                    text, normalized
                ):
                    domain_override = True
                    continue

                # Check domain allowlist for WARN/FLAG
                if severity <= Severity.WARN and self._is_allowed_in_domain(
                    normalized, pattern
                ):
                    domain_override = True
                    continue

                matched_terms.append(pattern)
                if severity > max_severity:
                    max_severity = severity

        action = SEVERITY_TO_ACTION.get(max_severity, "ALLOW")
        return FilterResult(
            severity=max_severity,
            action=action,
            matched_terms=matched_terms,
            normalized_text=normalized,
            domain_override=domain_override,
        )

    def _matches(self, text: str, pattern: str, match_type: MatchType) -> bool:
        """Check if pattern matches text using the specified match type."""
        if match_type == MatchType.EXACT:
            return text.strip() == pattern

        if match_type == MatchType.SUBSTRING:
            return pattern in text

        if match_type == MatchType.WORD_BOUNDARY:
            return self._word_boundary_match(text, pattern)

        return False

    @staticmethod
    def _word_boundary_match(text: str, word: str) -> bool:
        """
        Check if word appears at a word boundary in text.

        Uses regex \\b for proper boundary detection.
        """
        try:
            return bool(re.search(r"\b" + re.escape(word) + r"\b", text))
        except re.error:
            return word in text

    def _is_allowed_in_domain(self, text: str, pattern: str) -> bool:
        """Check if matched pattern is in domain allowlist context."""
        if not self._allowlist:
            return False
        # Check if any allowlist phrase containing the pattern is in the text
        for allowed in self._allowlist:
            if pattern in allowed and allowed in text:
                return True
            if pattern == allowed:
                return True
        return False


# =============================================================================
# MODULE-LEVEL CACHE
# =============================================================================

_filter_cache: Dict[Optional[str], ContentFilter] = {}


def get_content_filter(domain_id: Optional[str] = None) -> ContentFilter:
    """Get or create a ContentFilter for the given domain."""
    if domain_id not in _filter_cache:
        _filter_cache[domain_id] = ContentFilter(domain_id)
    return _filter_cache[domain_id]
