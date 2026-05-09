"""
Memory Agent Node - Sprint 73: Retrieve-Extract-Decide-Respond

4-phase pipeline for personal memory management:
  Phase 1: RETRIEVE - Load existing user facts from semantic memory
  Phase 2: EXTRACT - Use FactExtractor with existing facts context
  Phase 3: DECIDE - MemoryUpdater classifies ADD/UPDATE/DELETE/NOOP
  Phase 4: RESPOND - LLM generates natural response referencing changes

Integrated with the agents/ framework for config and tracing.
"""

import logging
import re
import unicodedata
from typing import Optional

from app.engine.agents import MEMORY_AGENT_CONFIG
from app.engine.messages import Message
from app.engine.messages_adapters import to_openai_dict
from app.engine.multi_agent.public_thinking import (
    _resolve_public_thinking_content,
)
from app.engine.multi_agent.state import AgentState
from app.engine.reasoning import (
    capture_thinking_lifecycle_event,
    record_thinking_snapshot,
)
from app.engine.semantic_memory.memory_updater import MemoryAction, MemoryUpdater
from app.prompts.prompt_runtime_tail import get_thinking_instruction_from_shared_config

logger = logging.getLogger(__name__)

_SERVICE_IDENTITY_USER_IDS = {"api-client", "anonymous"}

_EXPLICIT_MEMORY_WRITE_MARKERS = (
    "ghi nho",
    "hay nho",
    "luu lai",
    "remember",
    "keep in mind",
)
_MEMORY_ACK_DIRECTIVE_MARKERS = (
    "tra loi ngan gon",
    "tra loi chi",
    "tra loi chi:",
    "tra loi dung",
    "answer only",
    "reply only",
    "respond only",
    "da luu",
    "da ghi nhan",
    "xac nhan",
)
_MEMORY_RECALL_QUERY_MARKERS = (
    "la gi",
    "nho gi",
    "ban nho",
    "vua nho",
    "hoi lai",
    "what",
    "remember",
)

_MEMORY_BEHAVIOR_RULES = (
    "- Dùng thông tin đã biết về user để trả lời tự nhiên bằng tiếng Việt\n"
    "- Nếu chưa có fact lâu dài nhưng vẫn có hội thoại gần đây, hãy dựa vào ngữ cảnh đó để đáp tự nhiên\n"
    "- Không nói là 'không biết gì' nếu vẫn đang nhớ đoạn hội thoại vừa trao đổi\n"
    "- Nếu user chia sẻ thông tin mới, xác nhận đã ghi nhớ CỤ THỂ\n"
    "- Nếu thông tin được CẬP NHẬT, đề cập thay đổi\n"
    "- Nếu user hỏi về thông tin đã lưu, trả lời chính xác và đầy đủ\n"
    "- KHÔNG bắt đầu bằng lời chào - đi thẳng vào nội dung\n"
    "- KHÔNG bao gồm quá trình suy nghĩ"
)


def _build_memory_response_prompt(response_language: str = "vi") -> str:
    """Build memory agent prompt from wiii_identity.yaml + behavior rules."""
    thinking_instruction = get_thinking_instruction_from_shared_config({})
    from app.engine.semantic_memory.memory_contract import (
        build_memory_contract_policy_prompt,
    )

    memory_contract = build_memory_contract_policy_prompt()
    try:
        from app.prompts.prompt_loader import get_prompt_loader
        from app.prompts.prompt_context_utils import build_response_language_instruction
        from app.engine.reasoning.thinking_enforcement import get_thinking_enforcement

        loader = get_prompt_loader()
        identity = loader.get_identity().get("identity", {})
        personality = identity.get("personality", {}).get("summary", "")
        emoji_usage = identity.get("voice", {}).get("emoji_usage", "")
        name = identity.get("name", "Wiii")
        thinking_instruction = str(loader.get_thinking_instruction() or "").strip() or thinking_instruction
        enforcement = get_thinking_enforcement()

        if personality:
            return "\n".join(
                part
                for part in (
                    enforcement,
                    f"Ban la {name} - {personality}\n- {emoji_usage}\n{_MEMORY_BEHAVIOR_RULES}",
                    memory_contract,
                    build_response_language_instruction(response_language),
                    thinking_instruction,
                )
                if part
            )
    except Exception as exc:
        logger.warning("[MEMORY_AGENT] Failed to load identity YAML: %s", exc)

    try:
        from app.engine.reasoning.thinking_enforcement import get_thinking_enforcement
        enforcement = get_thinking_enforcement()
    except Exception:
        enforcement = ""

    return "\n".join(
        part
        for part in (
            enforcement,
            "Ban la Wiii - dang yeu, thich tro chuyen, giai thich ro rang.\n"
            "- Dung emoji tu nhien nhu nhan tin voi ban than (⚓🌊📚✨💡🎯😄)\n"
            f"{_MEMORY_BEHAVIOR_RULES}",
            memory_contract,
            thinking_instruction,
        )
        if part
    )


def _thinking_provenance_from_source(source: str | None) -> str:
    normalized = str(source or "").strip().lower()
    if normalized == "gemini_native":
        return "provider_native"
    if normalized in {"text_tags", "visible_thinking_block"}:
        return "provider_summary"
    return "provider_native"


def _normalize_memory_query(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or "").lower())
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(stripped.replace("đ", "d").split())


def _should_use_template_for_explicit_memory_write(
    *,
    query: str,
    new_facts: list,
    changes_summary: str,
) -> bool:
    if not (new_facts or changes_summary):
        return False
    normalized = _normalize_memory_query(query)
    if not any(marker in normalized for marker in _EXPLICIT_MEMORY_WRITE_MARKERS):
        return False
    return "lau dai" in normalized or any(
        marker in normalized for marker in _MEMORY_ACK_DIRECTIVE_MARKERS
    )


def _explicit_memory_ack_response(query: str) -> str:
    normalized = _normalize_memory_query(query)
    if not any(marker in normalized for marker in _EXPLICIT_MEMORY_WRITE_MARKERS):
        return ""
    if "tra loi chi" in normalized:
        marker_match = re.search(
            r"(?:trả\s+lời\s+chỉ|tra\s+loi\s+chi|answer\s+only|reply\s+only|respond\s+only)\s*[:：]\s*([^\.\n]+)",
            str(query or ""),
            flags=re.IGNORECASE,
        )
        if marker_match:
            requested = marker_match.group(1).strip(" \"'“”‘’.,。")
            if requested:
                return requested[:80]
        if "da ghi nhan" in normalized:
            return "Đã ghi nhận."
    if "da luu" in normalized or "tra loi ngan gon" in normalized:
        return "Đã lưu."
    if "xac nhan" in normalized:
        return "Đã xác nhận."
    return ""


def _memory_query_tokens(text: str) -> set[str]:
    stopwords = {
        "cua",
        "minh",
        "ban",
        "wiii",
        "wii",
        "vua",
        "nho",
        "ghi",
        "la",
        "gi",
        "tra",
        "loi",
        "dung",
        "mot",
        "cau",
        "cho",
        "toi",
        "em",
        "anh",
        "the",
        "what",
        "did",
        "you",
        "remember",
    }
    return {
        token
        for token in _normalize_memory_query(text).replace("?", " ").split()
        if len(token) >= 3 and token not in stopwords
    }


def _fact_content_text(fact: dict) -> str:
    return str(fact.get("content") or fact.get("value") or "").strip()


def _extract_named_memory_value_from_facts(query: str, existing_facts: list) -> str:
    normalized_query = _normalize_memory_query(query)
    if not any(marker in normalized_query for marker in _MEMORY_RECALL_QUERY_MARKERS):
        return ""
    query_tokens = _memory_query_tokens(query)
    if not query_tokens:
        return ""

    best_value = ""
    best_score = 0
    for fact in existing_facts or []:
        if not isinstance(fact, dict):
            continue
        content = _fact_content_text(fact)
        if not content:
            continue
        normalized_content = _normalize_memory_query(content)
        score = len(query_tokens.intersection(set(normalized_content.split())))
        if score < 2 and not query_tokens.issubset(set(normalized_content.split())):
            continue
        marker_index = normalized_content.find(" la ")
        if marker_index < 0:
            continue
        value = content[marker_index + 4 :].strip(" .。:;!?")
        if value and score >= best_score:
            best_value = value
            best_score = score
    return best_value


def _build_memory_recall_template_response(query: str, existing_facts: list) -> str:
    value = _extract_named_memory_value_from_facts(query, existing_facts)
    if not value:
        return ""
    normalized = _normalize_memory_query(query)
    if "dung 1 cau" in normalized or "tra loi dung 1 cau" in normalized:
        return value
    return f"Mã semantic test cuối của cậu là **{value}** nha (˶˃ ᵕ ˂˶)"


def _build_memory_public_thinking(
    *,
    query: str,
    existing_facts: list,
    new_facts: list,
    changes_summary: str,
) -> str:
    if new_facts or changes_summary:
        return (
            "Mình đang giữ lại điều cậu vừa gửi như một mảnh nhớ có thể dùng lại sau này, nên phần quan trọng nhất là lưu đúng chứ không nói hay. "
            "Nếu sau này cậu hỏi lại, Wiii phải nhắc được nguyên ý này một cách gọn và chắc."
        )
    if existing_facts:
        return (
            "Mình đang dựa vào điều đã lưu về cậu, không đoán mò từ nhịp trò chuyện. "
            "Việc cần làm là nhắc lại đúng phần chắc chắn, càng gọn càng tốt."
        )
    if query:
        return (
            "Mình có cảm giác câu này đang chạm tới trí nhớ, nhưng chưa có mảnh nào đủ chắc để lưu hay nhắc lại. "
            "Tốt hơn là nói thật phần mình biết, thay vì làm như đã nhớ."
        )
    return ""


class MemoryAgentNode:
    """
    Memory Agent - Retrieve-Extract-Decide-Respond pipeline.

    Phase 1: Retrieve existing user facts from semantic memory
    Phase 2: Extract new facts with existing facts context
    Phase 3: Classify via MemoryUpdater -> ADD/UPDATE/DELETE/NOOP
    Phase 4: Generate natural LLM response referencing specific changes
    """

    def __init__(self, semantic_memory=None):
        self._semantic_memory = semantic_memory
        self._config = MEMORY_AGENT_CONFIG
        self._updater = MemoryUpdater()
        logger.info("MemoryAgentNode initialized (Sprint 73: Retrieve-Extract-Decide-Respond)")

    @staticmethod
    def _is_service_identity(user_id: str) -> bool:
        return str(user_id or "").strip().lower() in _SERVICE_IDENTITY_USER_IDS

    async def process(self, state: AgentState, llm=None) -> AgentState:
        """Execute the 4-phase memory pipeline."""
        user_id = state.get("user_id", "")
        query = state.get("query", "")
        state["allow_authored_thinking_fallback"] = False

        event_queue = None
        bus_id = state.get("_event_bus_id")
        if bus_id:
            from app.engine.multi_agent.graph_event_bus import _get_event_queue

            event_queue = _get_event_queue(bus_id)

        async def _push(event: dict):
            capture_thinking_lifecycle_event(state, event)
            if event_queue:
                try:
                    event_queue.put_nowait(event)
                except Exception:
                    pass

        try:
            if self._is_service_identity(user_id):
                logger.info(
                    "[MEMORY_AGENT] Skipping long-term facts for service identity %s",
                    user_id,
                )
                existing_facts_list = []
                existing_facts_dict = {}
                new_facts, decisions = [], []
            else:
                existing_facts_list = await self._retrieve_facts(user_id)
                existing_facts_dict = {fact["type"]: fact["content"] for fact in existing_facts_list}

                new_facts, decisions = await self._extract_and_store_facts(
                    user_id,
                    query,
                    existing_facts_dict,
                )
            actionable_decisions = [
                decision for decision in decisions if decision.action != MemoryAction.NOOP
            ]
            action_counts = {}
            for decision in actionable_decisions:
                action_counts[decision.action.value] = action_counts.get(decision.action.value, 0) + 1
            changes_summary = self._updater.summarize_changes(actionable_decisions)

            response = await self._generate_response(
                llm,
                query,
                existing_facts_list,
                new_facts,
                changes_summary,
                state,
            )
            native_thinking = str(state.pop("_memory_native_thinking", "") or "").strip()
            thinking_source = str(state.pop("_memory_thinking_source", "") or "").strip()
            if native_thinking:
                provenance = _thinking_provenance_from_source(thinking_source)
                details = {"phase": "post_tool", "provenance": provenance}
                state["thinking_provenance"] = provenance
                await _push(
                    {
                        "type": "thinking_start",
                        "content": "",
                        "node": "memory_agent",
                        "details": details,
                        "provenance": provenance,
                    }
                )
                await _push(
                    {
                        "type": "thinking_delta",
                        "content": native_thinking,
                        "node": "memory_agent",
                        "details": details,
                        "provenance": provenance,
                    }
                )
                await _push(
                    {
                        "type": "thinking_end",
                        "content": "",
                        "node": "memory_agent",
                        "details": details,
                        "provenance": provenance,
                    }
                )
                state["thinking"] = native_thinking
                record_thinking_snapshot(
                    state,
                    native_thinking,
                    node="memory_agent",
                    provenance=provenance,
                )
            else:
                public_thinking = _build_memory_public_thinking(
                    query=query,
                    existing_facts=existing_facts_list,
                    new_facts=new_facts,
                    changes_summary=changes_summary,
                )
                if public_thinking:
                    provenance = "authored_public_summary"
                    details = {"phase": "memory_public_summary", "provenance": provenance}
                    state["thinking"] = public_thinking
                    state["thinking_provenance"] = provenance
                    await _push(
                        {
                            "type": "thinking_start",
                            "content": "",
                            "node": "memory_agent",
                            "details": details,
                            "provenance": provenance,
                        }
                    )
                    await _push(
                        {
                            "type": "thinking_delta",
                            "content": public_thinking,
                            "node": "memory_agent",
                            "details": details,
                            "provenance": provenance,
                        }
                    )
                    await _push(
                        {
                            "type": "thinking_end",
                            "content": "",
                            "node": "memory_agent",
                            "details": details,
                            "provenance": provenance,
                        }
                    )
                    record_thinking_snapshot(
                        state,
                        public_thinking,
                        node="memory_agent",
                        provenance=provenance,
                    )
                else:
                    state.pop("thinking", None)
                    state.pop("thinking_provenance", None)

            state["memory_output"] = response
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["memory"] = response
            state["current_agent"] = "memory_agent"

            public_memory_thinking = _resolve_public_thinking_content(state)
            if public_memory_thinking:
                state["thinking_content"] = public_memory_thinking
            else:
                state["thinking_content"] = ""

            logger.info(
                "[MEMORY_AGENT] Processed for user %s: %d existing, %d extracted, actions=%s",
                user_id,
                len(existing_facts_list),
                len(new_facts),
                action_counts,
            )

        except Exception as exc:
            logger.error("[MEMORY_AGENT] Error: %s", exc)
            fallback = self._template_response(
                query,
                [],
                [],
                "",
                recent_conversation=self._recent_conversation_excerpt(state),
            )
            state["memory_output"] = fallback
            state["agent_outputs"] = state.get("agent_outputs", {})
            state["agent_outputs"]["memory"] = fallback
            state["current_agent"] = "memory_agent"
            state["thinking_content"] = ""
            state.pop("thinking", None)
            state.pop("thinking_provenance", None)

        return state

    async def _retrieve_facts(self, user_id: str) -> list:
        """Retrieve existing user facts from semantic memory."""
        if not self._semantic_memory or not user_id:
            return []

        try:
            facts_dict = await self._semantic_memory.get_user_facts(user_id)
            result = []
            for fact_type, value in facts_dict.items():
                if str(fact_type).endswith("__updated_at"):
                    continue
                if value:
                    if isinstance(value, list):
                        for item in value:
                            result.append({"type": fact_type, "content": str(item)})
                    else:
                        result.append({"type": fact_type, "content": str(value)})
            return result
        except Exception as exc:
            logger.warning("[MEMORY_AGENT] Failed to retrieve facts: %s", exc)
            return []

    async def _extract_and_store_facts(
        self,
        user_id: str,
        message: str,
        existing_facts: dict,
    ) -> tuple[list, list]:
        """Extract facts from the current message and store them via upsert."""
        if not self._semantic_memory or not user_id or not message:
            return [], []

        try:
            fact_extractor = getattr(self._semantic_memory, "_fact_extractor", None)
            if fact_extractor is None:
                logger.warning("[MEMORY_AGENT] No fact extractor available on semantic memory")
                return [], []

            stored_facts = await fact_extractor.extract_and_store_facts(
                user_id=user_id,
                message=message,
                existing_facts=existing_facts,
            )
            facts = list(stored_facts or [])
            decisions = self._classify_fact_changes(facts, existing_facts)
            return [fact.to_content() for fact in facts], list(decisions or [])
        except Exception as exc:
            logger.warning("[MEMORY_AGENT] Failed to extract facts: %s", exc)
            return [], []

    def _classify_fact_changes(
        self,
        facts: list,
        existing_facts: dict,
    ) -> list:
        extracted_facts = []
        for fact in facts or []:
            payload = self._fact_to_payload(fact)
            if payload:
                extracted_facts.append(payload)
        if not extracted_facts:
            return []
        return self._updater.classify_batch(extracted_facts, existing_facts or {})

    @staticmethod
    def _fact_to_payload(fact) -> dict | None:
        if fact is None:
            return None

        fact_type = ""
        value = ""
        confidence = 0.9

        if isinstance(fact, dict):
            fact_type = str(fact.get("fact_type") or fact.get("type") or "").strip()
            value = str(fact.get("value") or fact.get("content") or "").strip()
            confidence = float(fact.get("confidence") or confidence)
        else:
            if hasattr(fact, "to_content"):
                try:
                    content = str(fact.to_content() or "").strip()
                except Exception:
                    content = ""
                if ": " in content:
                    fact_type, value = content.split(": ", 1)
                    fact_type = fact_type.strip()
                    value = value.strip()

            if not fact_type:
                raw_fact_type = getattr(fact, "fact_type", None)
                fact_type = str(getattr(raw_fact_type, "value", raw_fact_type) or "").strip()

            if not value:
                raw_value = getattr(fact, "value", "")
                value = str(raw_value or "").strip()

            raw_confidence = getattr(fact, "confidence", confidence)
            try:
                confidence = float(raw_confidence or confidence)
            except (TypeError, ValueError):
                confidence = 0.9

        if not fact_type or not value:
            return None

        return {
            "fact_type": fact_type,
            "value": value,
            "confidence": confidence,
        }

    @staticmethod
    def _serialize_content(content) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = str(item.get("text") or item.get("content") or "").strip()
                    if text:
                        parts.append(text)
                else:
                    text = str(item or "").strip()
                    if text:
                        parts.append(text)
            return "\n".join(part for part in parts if part).strip()
        return str(content or "").strip()

    def _recent_conversation_excerpt(self, state: AgentState) -> str:
        context = state.get("context", {}) or {}
        history_list = context.get("history_list") or []
        lines = []
        for item in history_list[-6:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            label = "User" if role == "user" else "AI"
            lines.append(f"{label}: {content}")
        if lines:
            return "\n".join(lines)

        langchain_messages = context.get("langchain_messages") or []
        for msg in langchain_messages[-6:]:
            role = str(
                getattr(msg, "type", None)
                or getattr(msg, "role", None)
                or msg.__class__.__name__
            ).strip().lower()
            if "system" in role:
                continue
            content = self._serialize_content(getattr(msg, "content", ""))
            if not content:
                continue
            label = "User" if ("human" in role or role == "user") else "AI"
            lines.append(f"{label}: {content}")
        if lines:
            return "\n".join(lines)

        conversation_history = str(context.get("conversation_history") or "").strip()
        if conversation_history:
            return conversation_history[-1200:]
        return ""

    async def _generate_response(
        self,
        llm,
        query: str,
        existing_facts: list,
        new_facts: list,
        changes_summary: str,
        state: AgentState,
    ) -> str:
        """Generate a natural Vietnamese response using LLM memory context."""
        state.pop("_memory_native_thinking", None)
        state.pop("_memory_thinking_source", None)
        recent_conversation = self._recent_conversation_excerpt(state)
        if _should_use_template_for_explicit_memory_write(
            query=query,
            new_facts=new_facts,
            changes_summary=changes_summary,
        ):
            concise_ack = _explicit_memory_ack_response(query)
            if concise_ack:
                return concise_ack
            return self._template_response(
                query,
                existing_facts,
                new_facts,
                changes_summary,
                recent_conversation=recent_conversation,
            )
        recall_response = _build_memory_recall_template_response(query, existing_facts)
        if recall_response:
            return recall_response
        if not llm:
            return self._template_response(
                query,
                existing_facts,
                new_facts,
                changes_summary,
                recent_conversation=recent_conversation,
            )

        try:
            context_parts = []
            if recent_conversation:
                context_parts.append(f"Doan hoi thoai gan day:\n{recent_conversation}")
            ctx = state.get("context") or {}
            if not isinstance(ctx, dict):
                ctx = {}
            core_memory_block = str(ctx.get("core_memory_block") or "").strip()
            if core_memory_block:
                context_parts.append(f"Core memory block:\n{core_memory_block}")
            if existing_facts:
                facts_str = "\n".join(f"- {fact['type']}: {fact['content']}" for fact in existing_facts)
                context_parts.append(f"Thong tin da biet ve user:\n{facts_str}")
            if new_facts:
                new_str = "\n".join(f"- {fact}" for fact in new_facts)
                context_parts.append(f"Thong tin moi vua ghi nho:\n{new_str}")
            if changes_summary:
                context_parts.append(f"Thay doi: {changes_summary}")

            lms_external_id = ctx.get("lms_external_id")
            lms_connector_id = ctx.get("lms_connector_id")
            if lms_external_id and lms_connector_id:
                try:
                    from app.core.config import settings as cfg

                    if getattr(cfg, "enable_lms_integration", False):
                        from app.integrations.lms.context_loader import get_lms_context_loader

                        loader = get_lms_context_loader()
                        lms_ctx = loader.load_student_context(
                            lms_external_id,
                            connector_id=lms_connector_id,
                        )
                        if lms_ctx:
                            context_parts.append(loader.format_for_prompt(lms_ctx))
                except Exception:
                    pass

            for key in (
                "host_context_prompt",
                "host_capabilities_prompt",
                "operator_context_prompt",
                "living_context_prompt",
                "widget_feedback_prompt",
            ):
                prompt = state.get(key, "")
                if prompt:
                    context_parts.append(prompt)

            context_block = (
                "\n\n".join(context_parts)
                if context_parts
                else "Chua co fact lau dai nao ve user. Neu van co ngu canh hoi thoai gan day, hay dua vao do de tra loi tu nhien."
            )

            messages = [
                to_openai_dict(Message(
                    role="system",
                    content=_build_memory_response_prompt(ctx.get("response_language", "vi")),
                ))
            ]
            langchain_messages = ctx.get("langchain_messages", [])
            if langchain_messages:
                messages.extend(langchain_messages[-5:])
            messages.append(
                to_openai_dict(Message(
                    role="user",
                    content=(
                        f"Ngu canh bo nho:\n{context_block}\n\n"
                        f"Tin nhan cua user: {query}"
                    ),
                ))
            )

            response = await llm.ainvoke(messages)

            from app.services.thinking_post_processor import get_thinking_processor

            text, thinking_raw = get_thinking_processor().process(response.content)
            result = text.strip()
            thinking = (thinking_raw or "").strip()
            if thinking:
                state["_memory_native_thinking"] = thinking
                state["thinking"] = thinking

            if result:
                return result

            return self._template_response(
                query,
                existing_facts,
                new_facts,
                changes_summary,
                recent_conversation=recent_conversation,
            )

        except Exception as exc:
            logger.warning("[MEMORY_AGENT] LLM response generation failed: %s", exc)
            return self._template_response(
                query,
                existing_facts,
                new_facts,
                changes_summary,
                recent_conversation=recent_conversation,
            )

    @staticmethod
    def _compact_recent_user_context(recent_conversation: str) -> str:
        user_lines = []
        for line in str(recent_conversation or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("User:"):
                text = stripped.removeprefix("User:").strip()
                if text:
                    user_lines.append(text)
        compact = "; ".join(user_lines[-3:]).strip()
        if len(compact) > 260:
            compact = compact[:257].rstrip() + "..."
        return compact

    def _template_response(
        self,
        query: str,
        existing_facts: list,
        new_facts: list,
        changes_summary: str,
        recent_conversation: str = "",
    ) -> str:
        """Template fallback response when LLM is unavailable."""
        if changes_summary:
            return f"{changes_summary}. Bạn cứ hỏi lại bất cứ lúc nào nhé!"

        if new_facts:
            items = ", ".join(new_facts[:3])
            return f"Mình đã ghi nhớ: {items}. Bạn cứ hỏi lại bất cứ lúc nào nhé!"

        if existing_facts:
            facts_str = ", ".join(
                f"{fact['type']}: {fact['content']}" for fact in existing_facts[:5]
            )
            return f"Đây là thông tin mình biết về bạn: {facts_str}"

        recent_user_context = self._compact_recent_user_context(recent_conversation)
        if recent_user_context:
            return (
                f"Mình vẫn theo được đoạn vừa rồi: bạn nói \"{recent_user_context}\". "
                "Mình chưa thấy fact dài hạn nào đủ rõ để lưu, nhưng ngữ cảnh gần thì vẫn còn đây."
            )

        return "Mình chưa có thông tin gì về bạn. Bạn có thể chia sẻ để mình ghi nhớ nhé!"

    def is_available(self) -> bool:
        """Check if memory services are available."""
        return self._semantic_memory is not None


_memory_node: Optional[MemoryAgentNode] = None


def get_memory_agent_node(semantic_memory=None) -> MemoryAgentNode:
    """Get or create MemoryAgentNode singleton."""
    global _memory_node
    if _memory_node is None:
        _memory_node = MemoryAgentNode(semantic_memory=semantic_memory)
    return _memory_node
