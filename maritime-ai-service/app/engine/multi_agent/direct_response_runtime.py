"""Response policy helpers for the direct execution lane."""

from __future__ import annotations

import re

from app.engine.multi_agent.lane_timeout_policy import (
    resolve_direct_fallback_provider_allowlist_impl,
    resolve_direct_lane_timeout_policy_impl,
)


def _flatten_message_content(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append(text)
                continue
            if not isinstance(item, dict):
                continue
            text = str(
                item.get("text")
                or item.get("content")
                or item.get("thinking")
                or ""
            ).strip()
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return str(value or "").strip()


def _message_role(message) -> str:
    if isinstance(message, dict):
        role = message.get("role") or message.get("type") or ""
    else:
        role = (
            getattr(message, "role", None)
            or getattr(message, "type", None)
            or message.__class__.__name__
        )
    normalized = str(role or "").strip().lower()
    if normalized in {"human", "humanmessage"}:
        return "user"
    if normalized in {"ai", "aimessage", "assistant"}:
        return "assistant"
    if normalized in {"tool", "toolmessage"}:
        return "tool"
    return normalized


def _extract_last_query(messages: list) -> str:
    for message in reversed(messages or []):
        if _message_role(message) != "user":
            continue
        if isinstance(message, dict):
            content = _flatten_message_content(message.get("content", ""))
        else:
            content = _flatten_message_content(getattr(message, "content", ""))
        if content:
            return content

    for message in reversed(messages or []):
        if isinstance(message, dict):
            content = _flatten_message_content(message.get("content", ""))
        else:
            content = _flatten_message_content(getattr(message, "content", ""))
        if content:
            return content
    return ""


def _derive_selfhood_thinking_from_answer(*, query: str, answer: str) -> str:
    from app.engine.multi_agent.direct_intent import _looks_identity_selfhood_turn

    normalized_query = query.lower()
    is_lore_followup = "bông" in normalized_query or "bong" in normalized_query

    if not _looks_identity_selfhood_turn(query) and not is_lore_followup:
        return ""

    clean = str(answer or "").strip()
    if len(clean) < 60:
        return ""

    paragraphs = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    head = paragraphs[0] if paragraphs else clean
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[\.\!\?…])\s+", head)
        if part.strip()
    ]
    if not sentences:
        return ""

    candidate_parts: list[str] = []
    for sentence in sentences[:3]:
        if sentence.endswith("?"):
            break
        candidate_parts.append(sentence)
        joined = " ".join(candidate_parts).strip()
        if len(joined) >= 220:
            break

    candidate = " ".join(candidate_parts).strip()
    if not candidate:
        return ""

    lowered = candidate.lower()
    lore_markers = (
        "wiii",
        "the wiii lab",
        "bong",
        "ra doi",
        "sinh ra",
        "nguon goc",
        "dem",
        "minh",
        "toi",
    )
    if not any(marker in lowered for marker in lore_markers):
        return ""

    if is_lore_followup and not any(
        marker in lowered
        for marker in (
            "the wiii lab",
            "bong",
            "ra doi",
            "dem",
            "meo",
        )
    ):
        return ""

    return candidate[:420].strip()


def _derive_analytical_thinking_from_answer(
    *,
    query: str,
    answer: str,
    tools_used_names: set[str] | None = None,
) -> str:
    from app.engine.multi_agent.direct_intent import _looks_identity_selfhood_turn

    normalized_query = str(query or "").strip().lower()
    clean = str(answer or "").strip()
    if len(clean) < 120 or _looks_identity_selfhood_turn(query):
        return ""

    analytical_markers = (
        "phân tích",
        "phan tich",
        "giải thích",
        "giai thich",
        "vì sao",
        "vi sao",
        "so sánh",
        "so sanh",
        "hôm nay",
        "hom nay",
        "compact resolvent",
        "hilbert",
        "self adjoint",
        "toán tử",
        "toan tu",
        "spectral theorem",
        "functional calculus",
        "giá dầu",
        "gia dau",
        "thị trường",
        "thi truong",
        "3 lực chính",
        "3 luc chinh",
        "jwt",
        "xac thuc",
        "authentication",
        "class diagram",
        "database",
        "schema",
        "migration",
        "repository",
        "controller",
        "filter",
        "service",
        "entity",
        "codebase",
        "source",
        "bang",
    )
    tool_markers = {
        "tool_web_search",
        "tool_news_search",
        "tool_generate_chart",
        "tool_generate_visual",
        "tool_search_google_shopping",
        "tool_search_all_web",
        "tool_dealer_search",
        "tool_international_search",
        "tool_search_websosanh",
    }
    used_tools = {str(name or "").strip() for name in (tools_used_names or set()) if str(name or "").strip()}
    if not any(marker in normalized_query for marker in analytical_markers) and not used_tools.intersection(tool_markers):
        return ""

    codebase_markers = (
        "jwt",
        "xac thuc",
        "authentication",
        "class diagram",
        "database",
        "schema",
        "migration",
        "repository",
        "controller",
        "filter",
        "service",
        "entity",
        "codebase",
        "source",
        "bang",
    )
    if any(marker in normalized_query for marker in codebase_markers):
        beats = [
            "Minh dang coi day la mot cau hoi source-backed, nen can tach phan nao la claim cua user va phan nao phai doi chieu voi file/schema that."
        ]
        if any(marker in normalized_query for marker in ("database", "schema", "class diagram", "migration", "bang")):
            beats.append(
                "Voi phan bang/schema, cau tra loi nen kiem ke hoac phan nhom: entity nghiep vu chinh, junction table, infrastructure table, va bang them qua migration."
            )
        if any(marker in normalized_query for marker in ("jwt", "xac thuc", "authentication")):
            beats.append(
                "Voi phan JWT/auth, can truy vet lifecycle tu login tao token sang Bearer request, filter verify, load user/role/enabled tu database, roi moi den authorization va refresh."
            )
        beats.append(
            "Neu source chua du trong context, phai noi ro muc do chac thay vi viet nhu da doc het codebase."
        )
        return " ".join(beats)[:520].strip()

    first_block = re.split(r"\n{2,}", clean, maxsplit=1)[0].strip()
    first_block = re.sub(r"^#{1,6}\s+", "", first_block).strip()
    first_block = re.sub(r"^\s*[-*]\s+", "", first_block).strip()
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[\.\!\?…])\s+", first_block)
        if part.strip()
    ]
    if not sentences:
        return ""

    thought_sentences: list[str] = []
    for sentence in sentences[:4]:
        if sentence.endswith("?"):
            break
        lowered = sentence.lower()
        if any(
            marker in lowered
            for marker in (
                "bạn có muốn",
                "ban co muon",
                "nếu bạn cần",
                "neu ban can",
                "mình có thể",
                "minh co the",
            )
        ):
            break
        thought_sentences.append(sentence)
        if len(" ".join(thought_sentences)) >= 360:
            break

    candidate = " ".join(thought_sentences).strip()
    if len(candidate) < 80:
        return ""
    return candidate[:420].strip()


def resolve_direct_answer_timeout_profile_impl(
    *,
    provider_name: str | None,
    query: str = "",
    state: object | None = None,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    use_house_voice_direct: bool,
    tools_bound: bool,
) -> str | None:
    """Choose a timeout profile for short/no-tool direct turns."""
    return resolve_direct_lane_timeout_policy_impl(
        provider_name=provider_name,
        query=query,
        state=state,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        tools_bound=tools_bound,
    ).timeout_profile


def resolve_direct_answer_primary_timeout_impl(
    *,
    provider_name: str | None,
    query: str = "",
    state: object | None = None,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    use_house_voice_direct: bool,
    tools_bound: bool,
) -> float | None:
    """Choose a first-token SLA override for short/no-tool direct turns."""
    return resolve_direct_lane_timeout_policy_impl(
        provider_name=provider_name,
        query=query,
        state=state,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        tools_bound=tools_bound,
    ).primary_timeout


def resolve_direct_fallback_provider_allowlist_impl_wrapper(
    *,
    provider_name: str | None,
    query: str = "",
    state: object | None = None,
    is_identity_turn: bool,
    is_short_house_chatter: bool,
    use_house_voice_direct: bool,
    tools_bound: bool,
) -> tuple[str, ...] | None:
    """Resolve lane-aware fallback provider restrictions for direct turns."""
    return resolve_direct_fallback_provider_allowlist_impl(
        provider_name=provider_name,
        query=query,
        state=state,
        is_identity_turn=is_identity_turn,
        is_short_house_chatter=is_short_house_chatter,
        use_house_voice_direct=use_house_voice_direct,
        tools_bound=tools_bound,
    )


def extract_direct_response_impl(llm_response, messages: list):
    """Extract response text, thinking content, and tool usage from a direct turn."""
    from app.services.output_processor import extract_thinking_from_response

    text_content, thinking_content = extract_thinking_from_response(llm_response.content)
    if not thinking_content:
        response_metadata = dict(getattr(llm_response, "response_metadata", None) or {})
        additional_kwargs = dict(getattr(llm_response, "additional_kwargs", None) or {})
        metadata_thinking = str(
            response_metadata.get("thinking_content")
            or response_metadata.get("thinking")
            or additional_kwargs.get("thinking")
            or ""
        ).strip()
        if metadata_thinking:
            thinking_content = metadata_thinking
    response = text_content.strip()
    tools_used_names = set()
    for message in messages:
        tool_calls = (
            message.get("tool_calls")
            if isinstance(message, dict)
            else getattr(message, "tool_calls", None)
        )
        if tool_calls:
            for tool_call in tool_calls:
                # Phase 35 — Google's OpenAI-compat returns ToolCall pydantic
                # objects, not dicts. NVIDIA returns dicts. Handle both.
                if isinstance(tool_call, dict):
                    name = tool_call.get("name", "unknown")
                else:
                    name = (
                        getattr(tool_call, "name", None)
                        or getattr(getattr(tool_call, "function", None), "name", None)
                        or "unknown"
                    )
                tools_used_names.add(str(name))

    if not thinking_content:
        thinking_content = _derive_selfhood_thinking_from_answer(
            query=_extract_last_query(messages),
            answer=response,
        )
    if not thinking_content:
        thinking_content = _derive_analytical_thinking_from_answer(
            query=_extract_last_query(messages),
            answer=response,
            tools_used_names=tools_used_names,
        )

    tools_used = [{"name": name} for name in sorted(tools_used_names)] if tools_used_names else []

    return response, thinking_content, tools_used
