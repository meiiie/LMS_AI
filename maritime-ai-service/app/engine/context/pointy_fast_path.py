"""Fast local Pointy intent matching for host UI guidance.

This is intentionally conservative. It exists to emit safe UI guidance before
the slower model/router path decides whether to call a host action tool.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

from app.engine.context.pointy_actions import POINTY_ACTION_CLICK, POINTY_ACTION_HIGHLIGHT

POINTY_FAST_PATH_SOURCE = "pointy_fast_path"

_LOCATE_TERMS = (
    "o dau",
    "where",
    "chi cho",
    "chi vao",
    "chi lai",
    "chi giup",
    "chi den",
    "chi toi",
    "tro toi",
    "tro vao",
    "tro den",
    "highlight",
    "show me",
    "point to",
    "nut",
    "button",
)
_CLICK_TERMS = (
    "mo",
    "bam",
    "click",
    "nhan vao",
    "vao khoa hoc",
    "vao trang",
    "vao muc",
    "vao tab",
    "di toi",
    "chuyen toi",
    "open",
)
_UNSAFE_CLICK_TERMS = (
    "submit",
    "nop bai",
    "quiz",
    "checkout",
    "payment",
    "thanh toan",
    "enroll",
    "dang ky",
    "logout",
    "dang xuat",
    "delete",
    "xoa",
    "mark complete",
    "hoan thanh",
)
_VISUAL_DELIVERY_TERMS = (
    "mo phong",
    "simulate",
    "simulation",
    "simulator",
    "canvas",
    "code studio",
    "tao visual",
    "tao hinh",
    "ve bieu do",
    "draw chart",
    "create chart",
    "mermaid",
    "html app",
)
_EXPLICIT_POINTY_OPERATOR_TERMS = (
    "pointy",
    "chi cho",
    "chi vao",
    "chi lai",
    "chi giup",
    "chi den",
    "chi toi",
    "tro toi",
    "tro vao",
    "tro den",
    "highlight",
    "show me where",
    "point to",
    "o dau",
    "where",
    "nut",
    "button",
    "bam",
    "click",
)

_TARGET_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("chat-send-button", "send-message", "send-button", "gui-tin-nhan"),
        ("gui tin nhan", "nut gui tin nhan", "nut gui", "send message", "send button"),
    ),
    (
        ("browse-courses", "browse-courses-link", "browse-courses-button"),
        ("kham pha khoa hoc", "kham pha", "browse courses", "browse"),
    ),
    (
        ("continue-learn", "continue-lesson", "continue-course"),
        ("tiep tuc hoc", "tiep tuc", "continue learning", "continue"),
    ),
    (
        ("my-courses", "my-courses-link"),
        ("khoa hoc cua toi", "khoa hoc dang hoc", "my courses"),
    ),
    (
        ("profile-link", "profile-card"),
        ("ho so", "profile"),
    ),
)


def normalize_pointy_text(value: str) -> str:
    normalized = (value or "").replace("đ", "d").replace("Đ", "d")
    normalized = unicodedata.normalize("NFD", normalized)
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    normalized = normalized.replace("đ", "d").replace("Đ", "d").lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _has_term(prompt: str, term: str) -> bool:
    normalized_term = normalize_pointy_text(term)
    if not normalized_term:
        return False
    return re.search(rf"(?<!\w){re.escape(normalized_term)}(?!\w)", prompt) is not None


def _has_any_term(prompt: str, terms: tuple[str, ...]) -> bool:
    return any(_has_term(prompt, term) for term in terms)


def _pointy_fast_path_already_ran(context: dict[str, Any] | None) -> bool:
    feedback = (context or {}).get("host_action_feedback")
    if not isinstance(feedback, dict):
        return False
    last = feedback.get("last_action_result")
    if not isinstance(last, dict):
        return False
    params = last.get("params")
    return isinstance(params, dict) and params.get("source") == POINTY_FAST_PATH_SOURCE


def _coerce_target(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    target_id = str(value.get("id") or "").strip()
    selector = str(value.get("selector") or "").strip()
    if not target_id or not selector:
        return None
    return {
        "id": target_id,
        "selector": selector,
        "label": str(value.get("label") or "").strip() or None,
        "click_safe": value.get("click_safe") is True,
        "click_kind": str(value.get("click_kind") or "").strip() or None,
    }


def get_pointy_targets_from_context(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    ctx = context or {}
    host_context = ctx.get("host_context") if isinstance(ctx.get("host_context"), dict) else {}
    host_page = host_context.get("page") if isinstance(host_context.get("page"), dict) else {}
    host_metadata = host_page.get("metadata") if isinstance(host_page.get("metadata"), dict) else {}
    page_context = ctx.get("page_context") if isinstance(ctx.get("page_context"), dict) else {}
    raw_targets = host_metadata.get("available_targets")
    if raw_targets is None:
        raw_targets = page_context.get("available_targets")
    if not isinstance(raw_targets, list):
        return []
    return [target for item in raw_targets if (target := _coerce_target(item))]


def _alias_score(prompt: str, target: dict[str, Any]) -> int:
    target_id = normalize_pointy_text(str(target.get("id") or ""))
    for alias_ids, alias_terms in _TARGET_ALIASES:
        if not any(_has_term(prompt, term) for term in alias_terms):
            continue
        if any(_has_term(target_id, normalize_pointy_text(alias_id)) for alias_id in alias_ids):
            return 40
    return 0


def _target_score(prompt: str, target: dict[str, Any]) -> int:
    target_id = normalize_pointy_text(str(target.get("id") or ""))
    selector = normalize_pointy_text(str(target.get("selector") or ""))
    label = normalize_pointy_text(str(target.get("label") or ""))
    label_words = [word for word in label.split(" ") if len(word) >= 3]

    score = _alias_score(prompt, target)
    if label and _has_term(prompt, label):
        score += 35
    if target_id and _has_term(prompt, target_id):
        score += 24
    if selector and _has_term(prompt, selector):
        score += 12
    if label_words:
        matched = sum(1 for word in label_words if _has_term(prompt, word))
        score += matched * 6
        if matched == len(label_words):
            score += 12
    if target.get("click_safe"):
        score += 2
    return score


def _select_target(prompt: str, targets: list[dict[str, Any]]) -> dict[str, Any] | None:
    best_target: dict[str, Any] | None = None
    best_score = 0
    for target in targets:
        score = _target_score(prompt, target)
        if score > best_score:
            best_target = target
            best_score = score
    return best_target if best_score >= 12 else None


def _with_known_wiii_targets(
    prompt: str,
    context: dict[str, Any] | None,
    targets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ctx = context or {}
    host_context = ctx.get("host_context") if isinstance(ctx.get("host_context"), dict) else {}
    host_type = normalize_pointy_text(str(host_context.get("host_type") or ""))
    if host_type not in {"wiii desktop", "wiii web", "wiii-desktop", "wiii-web"}:
        return targets
    wants_send_button = any(
        _has_term(prompt, term)
        for term in ("gui tin nhan", "nut gui tin nhan", "nut gui", "send message", "send button")
    )
    if not wants_send_button:
        return targets
    if any(str(target.get("id") or "") == "chat-send-button" for target in targets):
        return targets
    return [
        *targets,
        {
            "id": "chat-send-button",
            "selector": '[data-wiii-id="chat-send-button"]',
            "label": "Gửi tin nhắn",
            "click_safe": False,
            "click_kind": "chat_send",
        },
    ]


def _is_unsafe_click_target(prompt: str, target: dict[str, Any]) -> bool:
    combined = normalize_pointy_text(
        f"{prompt} {target.get('id') or ''} {target.get('label') or ''} {target.get('click_kind') or ''}"
    )
    return _has_any_term(combined, _UNSAFE_CLICK_TERMS)


def build_pointy_fast_path_action(
    prompt: str,
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if _pointy_fast_path_already_ran(context):
        return None

    normalized_prompt = normalize_pointy_text(prompt)
    if _has_any_term(normalized_prompt, _VISUAL_DELIVERY_TERMS) and not _has_any_term(
        normalized_prompt,
        _EXPLICIT_POINTY_OPERATOR_TERMS,
    ):
        return None
    wants_locate = _has_any_term(normalized_prompt, _LOCATE_TERMS)
    wants_click = _has_any_term(normalized_prompt, _CLICK_TERMS)
    if not normalized_prompt or (not wants_locate and not wants_click):
        return None

    targets = _with_known_wiii_targets(
        normalized_prompt,
        context,
        get_pointy_targets_from_context(context),
    )
    target = _select_target(normalized_prompt, targets)
    if not target:
        return None

    label = str(target.get("label") or target["id"])
    if wants_click and target.get("click_safe") and not _is_unsafe_click_target(normalized_prompt, target):
        return {
            "request_id": f"pointy-fast-{uuid.uuid4()}",
            "action": POINTY_ACTION_CLICK,
            "params": {
                "selector": target["id"],
                "message": f"Wiii đang mở {label} cho bạn.",
                "source": POINTY_FAST_PATH_SOURCE,
            },
            "target": target,
            "reason": "click",
        }

    return {
        "request_id": f"pointy-fast-{uuid.uuid4()}",
        "action": POINTY_ACTION_HIGHLIGHT,
        "params": {
            "selector": target["id"],
            "message": f"Đây là {label}. Wiii trỏ vào để bạn thấy ngay.",
            "duration_ms": 5600 if wants_click else 5200,
            "source": POINTY_FAST_PATH_SOURCE,
        },
        "target": target,
        "reason": "unsafe_click_demoted" if wants_click else "locate",
    }


__all__ = [
    "POINTY_FAST_PATH_SOURCE",
    "build_pointy_fast_path_action",
    "get_pointy_targets_from_context",
    "normalize_pointy_text",
]
