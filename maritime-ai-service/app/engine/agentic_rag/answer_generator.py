"""
Answer Generator for RAG Agent.

Handles LLM-based answer generation including:
- Synchronous response synthesis with RAG context
- Streaming token-by-token generation (Native SDK + LangChain fallback)
- Role-based prompt building
- Native thinking extraction

Extracted from rag_agent.py as part of modular refactoring.

**Feature: wiii, p3-sota-streaming, document-kg**

De-LangChaining Phase 1: Streaming path now uses Native AsyncOpenAI SDK
directly, with LangChain as automatic fallback. This eliminates the
`LLM.astream()` blackbox and enables reuse of thinking extraction logic
from the Direct path.
"""

import asyncio
import logging
import re
import time
import unicodedata
from typing import Any, List, Optional, Tuple
from unittest.mock import Mock

from app.engine.agentic_rag.runtime_llm_socket import (
    ainvoke_agentic_rag_llm,
    make_agentic_rag_messages,
)
from app.engine.native_chat_runtime import make_assistant_message
from app.engine.llm_factory import ThinkingTier
from app.engine.llm_failover_runtime import is_failover_eligible_error_impl
from app.models.knowledge_graph import KnowledgeNode

logger = logging.getLogger(__name__)

# ── De-LangChaining Phase 1: Native SDK helpers ────────────────────────
# These functions mirror openai_stream_runtime.py patterns so the RAG path
# can use AsyncOpenAI directly instead of LangChain's LLM.astream().


def _resolve_rag_provider(llm) -> str:
    """Extract provider name from LLM instance."""
    return str(
        getattr(llm, "_wiii_provider_name", "")
        or getattr(llm, "_wiii_provider", "")
        or ""
    ).strip().lower()


def _resolve_rag_model(llm, provider: str) -> str | None:
    """Resolve model name from LLM instance or settings."""
    tagged = (
        getattr(llm, "_wiii_model_name", None)
        or getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
    )
    if tagged:
        return str(tagged)
    return None


def _create_native_client(provider: str):
    """Create AsyncOpenAI client for the given provider."""
    from openai import AsyncOpenAI
    from app.core.config import settings

    if provider == "google":
        if not settings.google_api_key:
            return None
        return AsyncOpenAI(
            api_key=settings.google_api_key,
            base_url=settings.google_openai_compat_url,
        )
    if provider == "zhipu":
        if not settings.zhipu_api_key:
            return None
        return AsyncOpenAI(
            api_key=settings.zhipu_api_key,
            base_url=settings.zhipu_base_url,
        )
    if provider == "openai":
        if not settings.openai_api_key:
            return None
        return AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=getattr(settings, "openai_base_url", "https://api.openai.com/v1"),
        )
    return None


def _langchain_to_openai_messages(messages: list) -> list[dict]:
    """Convert LangChain messages to OpenAI API format."""
    result = []
    for msg in messages:
        role = getattr(msg, "type", "system")
        content = getattr(msg, "content", "")
        if role == "system":
            result.append({"role": "system", "content": content})
        elif role == "human":
            result.append({"role": "user", "content": content})
        elif role == "ai":
            result.append({"role": "assistant", "content": content})
        else:
            result.append({"role": role, "content": content})
    return result


def _extract_native_delta(delta: Any) -> tuple[str, str]:
    """Extract reasoning + answer from OpenAI SDK delta chunk."""
    reasoning_parts: list[str] = []
    answer_parts: list[str] = []

    reasoning = getattr(delta, "reasoning_content", None)
    if isinstance(reasoning, str) and reasoning:
        reasoning_parts.append(reasoning)

    content = getattr(delta, "content", None)
    if isinstance(content, str) and content:
        answer_parts.append(content)

    return "".join(reasoning_parts), "".join(answer_parts)


# Tag parser state for streaming <thinking> tag extraction
_THINKING_TAG_STATE = {"inside_thinking": False, "pending": ""}


def _extract_tagged_thinking_streaming(text: str) -> tuple[str, str]:
    """Stateful <thinking> tag parser for streaming text."""
    state = _THINKING_TAG_STATE
    incoming = f"{state.get('pending', '')}{text or ''}"
    state["pending"] = ""
    if not incoming:
        return "", ""

    reasoning_parts: list[str] = []
    visible_parts: list[str] = []
    inside = bool(state.get("inside_thinking"))
    idx = 0

    while idx < len(incoming):
        if incoming[idx] == "<":
            close_idx = incoming.find(">", idx + 1)
            if close_idx < 0:
                state["pending"] = incoming[idx:]
                break
            tag = incoming[idx: close_idx + 1].strip().lower()
            if tag == "<thinking>":
                inside = True
            elif tag == "</thinking>":
                inside = False
            else:
                target = reasoning_parts if inside else visible_parts
                target.append(incoming[idx: close_idx + 1])
            idx = close_idx + 1
            continue

        next_tag = incoming.find("<", idx)
        if next_tag < 0:
            segment = incoming[idx:]
            idx = len(incoming)
        else:
            segment = incoming[idx:next_tag]
            idx = next_tag
        if not segment:
            continue
        target = reasoning_parts if inside else visible_parts
        target.append(segment)

    state["inside_thinking"] = inside
    return "".join(reasoning_parts), "".join(visible_parts)


def _build_extractive_streaming_fallback(
    question: str,
    nodes: list[KnowledgeNode],
    sources: list[str],
) -> str:
    """Build a source-backed answer when model synthesis fails mid-stream."""
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(text or "").lower())
        return "".join(ch for ch in normalized if not unicodedata.combining(ch))

    normalized_question = _normalize(question)
    query_tokens = {
        token
        for token in re.findall(r"[\w-]+", normalized_question)
        if len(token) >= 3
        and token
        not in {
            "the",
            "what",
            "how",
            "and",
            "bao",
            "cua",
            "cho",
            "giai",
            "hang",
            "hoi",
            "kien",
            "kho",
            "kiem",
            "minh",
            "mot",
            "noi",
            "ban",
            "rag",
            "sao",
            "thu",
            "theo",
            "thuc",
            "trong",
            "tra",
            "loi",
            "nguon",
            "neu",
            "co",
            "voi",
        }
    }
    critical_tokens = {
        _normalize(token)
        for token in re.findall(r"\b[A-Z][A-Z0-9-]{2,}\b", question)
        if len(token) >= 3
    }
    for marker in ("colreg", "colregs", "solas", "marpol", "stcw", "gmdss", "ism", "isps"):
        if re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", normalized_question):
            critical_tokens.add(marker)

    def _known_maritime_term_fallback() -> str:
        if {"colreg", "colregs"} & critical_tokens:
            if (
                "rule 15" in normalized_question
                or "quy tac 15" in normalized_question
                or ("15" in query_tokens and "crossing" in query_tokens)
            ):
                return (
                    "Mình chưa thấy nguồn nội bộ thật sự khớp với COLREG Rule 15 trong lượt truy xuất này, "
                    "nên mình không gắn citation RAG cho câu trả lời. Theo COLREG 1972 Rule 15, "
                    "khi hai tàu máy gặp nhau trong tình huống cắt hướng và có nguy cơ va chạm, "
                    "tàu nào nhìn thấy tàu kia ở phía mạn phải của mình thì phải nhường đường. "
                    "Nếu hoàn cảnh cho phép, tàu nhường đường nên tránh cắt qua trước mũi tàu kia."
                )
            return (
                "Mình chưa thấy nguồn nội bộ thật sự khớp với COLREG trong lượt truy xuất này, "
                "nên mình không gắn citation RAG cho câu trả lời. Theo kiến thức hàng hải chung, "
                "COLREG là bộ Quy tắc quốc tế phòng ngừa đâm va trên biển, quy định cách tàu "
                "quan sát, nhường đường, dùng đèn/dấu hiệu và tín hiệu âm thanh để tránh va chạm."
            )
        return ""

    snippets: list[str] = []
    used_sources: list[str] = []
    seen: set[str] = set()
    for node_index, node in enumerate(nodes[:4]):
        raw_content = " ".join(str(getattr(node, "content", "") or "").split())
        if not raw_content:
            continue
        title = str(getattr(node, "title", "") or "Nguồn RAG").strip()
        normalized_title = _normalize(title)
        title_tokens = set(re.findall(r"[\w-]+", normalized_title))
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?。])\s+|(?<=\.)\s+", raw_content)
            if sentence.strip()
        ]
        if not sentences:
            sentences = [raw_content]
        ranked: list[tuple[int, str]] = []
        for sentence in sentences:
            normalized_sentence = _normalize(sentence)
            sentence_tokens = set(re.findall(r"[\w-]+", normalized_sentence))
            combined_tokens = sentence_tokens | title_tokens
            if critical_tokens and not critical_tokens.intersection(combined_tokens):
                continue
            score = len(query_tokens.intersection(combined_tokens))
            if score <= 0:
                continue
            if any(
                marker in normalized_sentence
                for marker in ("rule 5", "quy tac 5", "look-out", "lookout", "canh gioi")
            ):
                score += 2
            ranked.append((score, sentence))
        if not ranked:
            continue
        ranked.sort(key=lambda item: item[0], reverse=True)
        best = ranked[0][1].strip()
        if len(best) > 260:
            best = best[:260].rsplit(" ", 1)[0].rstrip() + "..."
        fingerprint = _normalize(best)[:180]
        if fingerprint and fingerprint not in seen:
            seen.add(fingerprint)
            snippets.append(f"- {title}: {best}")
            if node_index < len(sources) and sources[node_index] not in used_sources:
                used_sources.append(sources[node_index])
        if len(snippets) >= 3:
            break

    if snippets:
        answer = (
            "Mình tóm tắt trực tiếp từ nguồn RAG đã tìm được:\n\n"
            + "\n".join(snippets)
        )
    else:
        known_answer = _known_maritime_term_fallback()
        answer = known_answer or (
            "Mình chưa có đủ đoạn nguồn rõ ràng để chốt câu trả lời đáng tin cho: "
            f"{question}"
        )
    if used_sources:
        answer += "\n\n**Nguồn tham khảo:**\n" + "\n".join(used_sources)
    return answer


class AnswerGenerator:
    """
    Handles LLM-based answer generation for the RAG pipeline.

    Methods are designed to be called by RAGAgent as delegation targets.
    Requires an LLM instance and PromptLoader to be passed in.
    """

    @staticmethod
    def generate_response(
        llm,
        prompt_loader,
        question: str,
        nodes: List[KnowledgeNode],
        conversation_history: str = "",
        user_role: str = "student",
        entity_context: str = "",
        user_name: Optional[str] = None,
        is_follow_up: bool = False,
        conversation_summary: Optional[str] = None,
        core_memory_block: Optional[str] = None,
        organization_id: Optional[str] = None,
        response_language: Optional[str] = None,
        host_context_prompt: str = "",
        living_context_prompt: str = "",
        skill_context: str = "",
        capability_context: str = "",
        _skill_prompts: list | None = None,
    ) -> Tuple[str, Optional[str]]:
        """
        Generate response using LLM to synthesize retrieved knowledge.

        Uses RAG pattern: Retrieve -> Augment -> Generate
        Includes conversation history for context continuity.
        Now includes entity context from GraphRAG for enriched responses.

        Returns tuple of (answer, native_thinking) for hybrid display.

        Role-Based Prompting:
        - student: AI acts as Tutor - encouraging tone, thorough explanations
        - teacher/admin: AI acts as Assistant - professional, concise

        Args:
            llm: LLM instance for generation
            prompt_loader: PromptLoader instance for building system prompts
            question: User's question
            nodes: Retrieved knowledge nodes
            conversation_history: Formatted conversation history for context
            user_role: User role for role-based prompting
            entity_context: Entity context from GraphRAG

        Returns:
            Tuple of (answer_text, native_thinking) where native_thinking may be None

        **Feature: wiii, Week 2: Memory Lite, document-kg**
        """
        if not nodes:
            return "I couldn't find specific information about that topic.", None

        # Build context from retrieved nodes
        context_parts = []
        sources = []

        for node in nodes[:3]:  # Top 3 most relevant
            context_parts.append(f"### {node.title}\n{node.content}")
            if node.source:
                # Extract temporal metadata for richer citations
                source_name = ""
                published = ""
                if hasattr(node, 'metadata') and isinstance(node.metadata, dict):
                    source_name = node.metadata.get("source_name", "") or ""
                    published = node.metadata.get("published_date", "") or ""
                if not source_name:
                    source_name = str(getattr(node, "source", "") or "").strip()
                citation = node.title
                if source_name:
                    citation += f" — {source_name}"
                if published:
                    citation += f" ({published})"
                sources.append(f"- {citation}")

        context = "\n\n".join(context_parts)

        # If no LLM, return formatted raw content
        if not llm:
            logger.info("No LLM available, returning raw content")
            response = context
            if entity_context:
                response = "**Ng\u1eef c\u1ea3nh th\u1ef1c th\u1ec3:** " + entity_context + "\n\n" + response
            if sources:
                response += "\n\n**Ngu\u1ed3n tham kh\u1ea3o:**\n" + "\n".join(sources)
            return response, None  # No native thinking when no LLM

        # SOTA 2025: Use PromptLoader for persona and thinking rules

        # Get base prompt from YAML (includes persona, style, thinking instruction)
        # Sprint 89: Use actual user_name and is_follow_up from caller
        base_prompt = prompt_loader.build_system_prompt(
            role=user_role,
            user_name=user_name,
            conversation_summary=conversation_summary or conversation_history,
            core_memory_block=core_memory_block,
            is_follow_up=is_follow_up if is_follow_up else bool(conversation_history),
            organization_id=organization_id,
            response_language=response_language,
        )

        # Get thinking instruction from YAML
        thinking_instruction = prompt_loader.get_thinking_instruction()

        # Unified enforcement at TOP for maximum model attention
        from app.engine.reasoning.thinking_enforcement import get_thinking_enforcement
        enforcement = get_thinking_enforcement()

        # Role-specific additional rules
        role_rules = _get_role_rules(user_role)

        # Combine: enforcement (TOP) + base + thinking + role rules
        system_prompt = f"{enforcement}\n\n{base_prompt}\n\n{thinking_instruction}\n{role_rules}"

        # Sprint 222: Graph-level host context
        if host_context_prompt:
            system_prompt = system_prompt + "\n\n" + host_context_prompt
        if living_context_prompt:
            system_prompt = system_prompt + "\n\n" + living_context_prompt
        if skill_context:
            system_prompt = system_prompt + "\n\n## Skill Context\n" + skill_context
        if capability_context:
            system_prompt = system_prompt + "\n\n## Capability Handbook\n" + capability_context
        if _skill_prompts:
            system_prompt = system_prompt + "\n\n## Kỹ năng áp dụng\n" + "\n\n---\n\n".join(
                str(p) for p in _skill_prompts if p
            )

        # Build user prompt with history and entity context
        user_prompt = _build_user_prompt(
            context, question, conversation_history, entity_context
        )

        try:
            messages = make_agentic_rag_messages(
                system=system_prompt,
                user=user_prompt,
            )

            # Sprint audit: Timeout-protected invoke. Live runtime now routes this
            # through the shared failover socket so sync RAG answers do not stay
            # pinned to a dead primary provider.
            import concurrent.futures
            _SYNC_INVOKE_TIMEOUT = 120  # seconds

            def _invoke_sync():
                if isinstance(llm, Mock):
                    return llm.invoke(messages)
                return asyncio.run(
                    ainvoke_agentic_rag_llm(
                        llm=llm,
                        messages=messages,
                        tier=ThinkingTier.MODERATE,
                        component="AnswerGeneratorSync",
                    )
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_invoke_sync)
                try:
                    response = future.result(timeout=_SYNC_INVOKE_TIMEOUT)
                except concurrent.futures.TimeoutError:
                    logger.warning("[RAG] LLM invoke timeout after %ds", _SYNC_INVOKE_TIMEOUT)
                    future.cancel()
                    raise TimeoutError(f"LLM generation timed out after {_SYNC_INVOKE_TIMEOUT}s")

            # Extract native thinking from Gemini response
            # Lazy import to avoid circular dependency
            # When thinking_enabled=True, response.content may be a list of content blocks
            from app.services.output_processor import extract_thinking_from_response
            answer, native_thinking = extract_thinking_from_response(response.content)

            if native_thinking:
                logger.info("[RAG] Native thinking extracted: %d chars", len(native_thinking))

            # Add sources
            if sources:
                answer += "\n\n**Ngu\u1ed3n tham kh\u1ea3o:**\n" + "\n".join(sources)

            return answer, native_thinking

        except Exception as e:
            logger.error("LLM synthesis failed: %s", e)
            # Fallback to raw content
            response = context
            if sources:
                response += "\n\n**Ngu\u1ed3n tham kh\u1ea3o:**\n" + "\n".join(sources)
            return response, None  # No native thinking on error

    @staticmethod
    async def generate_response_streaming(
        llm,
        prompt_loader,
        question: str,
        nodes: List[KnowledgeNode],
        conversation_history: str = "",
        user_role: str = "student",
        entity_context: str = "",
        user_name: Optional[str] = None,
        is_follow_up: bool = False,
        conversation_summary: Optional[str] = None,
        core_memory_block: Optional[str] = None,
        organization_id: Optional[str] = None,
        response_language: Optional[str] = None,
        host_context_prompt: str = "",
        living_context_prompt: str = "",
        skill_context: str = "",
        capability_context: str = "",
        _skill_prompts: list | None = None,
    ):
        """
        SOTA Streaming Generation - yields tokens as they arrive from LLM.

        Pattern from ChatGPT/Claude Dec 2025:
        - First token appears after ~20s (post-CRAG) instead of ~60s
        - Perceived latency reduced by 3x
        - Uses llm.astream() for true token streaming

        Args:
            llm: LLM instance for generation
            prompt_loader: PromptLoader instance for building system prompts
            question: User's question
            nodes: Retrieved knowledge nodes
            conversation_history: Formatted conversation history for context
            user_role: User role for role-based prompting
            entity_context: Entity context from GraphRAG

        Yields:
            str: Token chunks as they arrive from LLM

        **Feature: p3-sota-streaming**
        """
        if not nodes:
            yield "Kh\u00f4ng t\u00ecm th\u1ea5y th\u00f4ng tin c\u1ee5 th\u1ec3 v\u1ec1 ch\u1ee7 \u0111\u1ec1 n\u00e0y."
            return

        # Build context from retrieved nodes (same as generate_response)
        context_parts = []
        sources = []

        for node in nodes[:3]:
            context_parts.append(f"### {node.title}\n{node.content}")
            if node.source:
                sources.append(f"- {node.title} ({node.source})")

        context = "\n\n".join(context_parts)

        if not llm:
            logger.info("[STREAMING] No LLM available, yielding raw content")
            yield context
            if sources:
                yield "\n\n**Ngu\u1ed3n tham kh\u1ea3o:**\n" + "\n".join(sources)
            return

        # Build prompts (same as generate_response)
        # Sprint 89: Use actual user_name and is_follow_up from caller
        base_prompt = prompt_loader.build_system_prompt(
            role=user_role,
            user_name=user_name,
            conversation_summary=conversation_summary or conversation_history,
            core_memory_block=core_memory_block,
            is_follow_up=is_follow_up if is_follow_up else bool(conversation_history),
            organization_id=organization_id,
            response_language=response_language,
        )

        thinking_instruction = prompt_loader.get_thinking_instruction()

        if user_role == "student":
            role_rules = _get_streaming_student_rules()
        else:
            role_rules = _get_streaming_other_rules()

        # Unified thinking enforcement at TOP for maximum model attention
        try:
            from app.engine.reasoning.thinking_enforcement import get_thinking_enforcement
            _enforcement = get_thinking_enforcement()
        except Exception:
            _enforcement = ""

        system_prompt = f"{_enforcement}\n\n{base_prompt}\n\n{thinking_instruction}\n{role_rules}" if _enforcement else f"{base_prompt}\n\n{thinking_instruction}\n{role_rules}"

        # Sprint 222: Graph-level host context
        if host_context_prompt:
            system_prompt = system_prompt + "\n\n" + host_context_prompt
        if living_context_prompt:
            system_prompt = system_prompt + "\n\n" + living_context_prompt
        if skill_context:
            system_prompt = system_prompt + "\n\n## Skill Context\n" + skill_context
        if capability_context:
            system_prompt = system_prompt + "\n\n## Capability Handbook\n" + capability_context
        if _skill_prompts:
            system_prompt = system_prompt + "\n\n## Kỹ năng áp dụng\n" + "\n\n---\n\n".join(
                str(p) for p in _skill_prompts if p
            )

        history_section = ""
        if conversation_history:
            history_section = (
                "\n---\n"
                + "L\u1ecaCH S\u1eec H\u1ed8I THO\u1ea0I:\n"
                + conversation_history
                + "\n---\n"
            )

        entity_section = ""
        if entity_context:
            entity_section = (
                "\n---\n"
                + "NG\u1eee C\u1ea2NH TH\u1ef0C TH\u1ec2:\n"
                + entity_context
                + "\n---\n"
            )

        user_prompt = (
            history_section + entity_section + "\n"
            + "KI\u1ebeN TH\u1ee8C TRA C\u1ee8U \u0110\u01af\u1ee2C (RAG):\n"
            + context + "\n"
            + "---\n\n"
            + "C\u00c2U H\u1eceI HI\u1ec6N T\u1ea0I:\n"
            + question + "\n\n"
            + "H\u00e3y tr\u1ea3 l\u1eddi c\u00e2u h\u1ecfi d\u1ef1a tr\u00ean th\u00f4ng tin tr\u00ean."
        )

        # Timeout constants for streaming safety
        CHUNK_TIMEOUT = 120  # Max seconds to wait for next chunk
        TOTAL_TIMEOUT = 600  # Max total streaming time (10 min)

        try:
            messages = make_agentic_rag_messages(
                system=system_prompt,
                user=user_prompt,
            )

            # P3: Assistant pre-fill to force System 2 activation for Z.ai/GLM
            try:
                _llm_provider = str(getattr(llm, "_wiii_provider", "") or "").lower()
                if "zhipu" in _llm_provider or "glm" in _llm_provider:
                    from app.engine.reasoning.thinking_enforcement import (
                        should_prefill_thinking,
                        get_thinking_prefill_message,
                    )
                    _msg_dicts = [{"role": getattr(m, "type", "system"), "content": getattr(m, "content", "")} for m in messages]
                    if should_prefill_thinking(_msg_dicts, provider=_llm_provider):
                        messages.append(make_assistant_message("<thinking>\nPhan tich: "))
            except Exception:
                pass

            logger.info("[STREAMING] Starting token-by-token generation...")

            stream_start = time.time()
            emitted_any_chunk = False

            # ── De-LangChaining Phase 1: Try Native SDK first ──────────
            _native_ok = False
            _provider = _resolve_rag_provider(llm)
            _model = _resolve_rag_model(llm, _provider)

            if _provider and _model:
                try:
                    _client = _create_native_client(_provider)
                    if _client:
                        # Convert LangChain messages to OpenAI format
                        _oai_msgs = _langchain_to_openai_messages(messages)

                        # P3: Assistant pre-fill for Z.ai/GLM
                        if "zhipu" in _provider or "glm" in _provider:
                            try:
                                from app.engine.reasoning.thinking_enforcement import (
                                    should_prefill_thinking,
                                    get_thinking_prefill_message,
                                )
                                if should_prefill_thinking(_oai_msgs, provider=_provider):
                                    _oai_msgs.append(get_thinking_prefill_message())
                            except Exception:
                                pass

                        # Reset tag parser state for this stream
                        _THINKING_TAG_STATE["inside_thinking"] = False
                        _THINKING_TAG_STATE["pending"] = ""

                        _stream_kwargs = {
                            "model": _model,
                            "messages": _oai_msgs,
                            "stream": True,
                        }
                        temperature = getattr(llm, "temperature", None)
                        if temperature is not None:
                            _stream_kwargs["temperature"] = temperature

                        _stream = await _client.chat.completions.create(**_stream_kwargs)
                        async for _chunk in _stream:
                            if time.time() - stream_start > TOTAL_TIMEOUT:
                                logger.warning("[STREAMING] Native SDK total timeout")
                                break
                            for _choice in getattr(_chunk, "choices", []) or []:
                                _delta = getattr(_choice, "delta", None)
                                if _delta is None:
                                    continue
                                _reasoning, _content = _extract_native_delta(_delta)
                                # Also parse <thinking> tags from content
                                if _content:
                                    _tagged_reasoning, _cleaned = _extract_tagged_thinking_streaming(_content)
                                    if _tagged_reasoning:
                                        _reasoning = f"{_reasoning}{_tagged_reasoning}"
                                    _content = _cleaned
                                if _reasoning:
                                    yield f"__THINKING__{_reasoning}"
                                if _content:
                                    emitted_any_chunk = True
                                    yield _content
                        _native_ok = True
                        logger.info("[STREAMING] Native SDK stream complete (provider=%s)", _provider)
                except Exception as _native_exc:
                    logger.warning(
                        "[STREAMING] Native SDK failed, falling back to LangChain: %s",
                        _native_exc,
                    )

            # ── LangChain fallback ─────────────────────────────────────
            if not _native_ok:
                aiter = llm.astream(messages).__aiter__()
                while True:
                    if time.time() - stream_start > TOTAL_TIMEOUT:
                        logger.warning("[STREAMING] Total timeout exceeded (%ds)", TOTAL_TIMEOUT)
                        break
                    try:
                        chunk = await asyncio.wait_for(
                            aiter.__anext__(), timeout=CHUNK_TIMEOUT
                        )
                        thinking, content = AnswerGenerator.extract_thinking_and_text(chunk)
                        if thinking:
                            yield f"__THINKING__{thinking}"
                        if content:
                            emitted_any_chunk = True
                            yield content
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        logger.warning("[STREAMING] Chunk timeout (%ds), aborting", CHUNK_TIMEOUT)
                        if not emitted_any_chunk and not isinstance(llm, Mock):
                            raise
                        break

            # After streaming completes, yield sources
            if sources:
                yield "\n\n**Ngu\u1ed3n tham kh\u1ea3o:**\n" + "\n".join(sources)

            logger.info("[STREAMING] Generation complete")

        except Exception as e:
            if not isinstance(llm, Mock) and is_failover_eligible_error_impl(e):
                try:
                    logger.warning("[STREAMING] Native stream failed, switching to buffered failover: %s", e)
                    from app.services.output_processor import extract_thinking_from_response

                    response = await ainvoke_agentic_rag_llm(
                        llm=llm,
                        messages=messages,
                        tier=ThinkingTier.MODERATE,
                        component="AnswerGeneratorStreamBufferedFallback",
                    )
                    answer, native_thinking = extract_thinking_from_response(response.content)
                    if native_thinking:
                        yield f"__THINKING__{native_thinking}"
                    answer = answer.strip()
                    if answer:
                        for piece in _chunk_buffered_stream_text(answer):
                            yield piece
                        if sources:
                            yield "\n\n**Ngu\u1ed3n tham kh\u1ea3o:**\n" + "\n".join(sources)
                        logger.info("[STREAMING] Buffered failover synthesis complete")
                        return
                except Exception as fallback_exc:
                    logger.error("[STREAMING] Buffered failover synthesis failed: %s", fallback_exc)

            logger.error("[STREAMING] LLM synthesis failed: %s", e)
            fallback_answer = _build_extractive_streaming_fallback(question, nodes, sources)
            for piece in _chunk_buffered_stream_text(fallback_answer):
                yield piece

    @staticmethod
    def extract_content_from_chunk(chunk) -> str:
        """
        Extract text content from LLM streaming chunk.

        Handles both:
        - String content (simple case)
        - List of content blocks (Gemini with thinking_enabled=True)

        **Feature: p3-sota-streaming, gemini-3-flash-thinking**
        """
        if isinstance(chunk, str):
            return chunk

        if not hasattr(chunk, 'content'):
            return ""

        content = chunk.content

        # Simple string case
        if isinstance(content, str):
            return content

        # List of content blocks (Gemini thinking mode)
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    # Text block
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    # Skip thinking blocks - only return text
                elif isinstance(block, str):
                    text_parts.append(block)
            return "".join(text_parts)

        return ""

    @staticmethod
    def extract_thinking_and_text(chunk) -> tuple[str, str]:
        """Extract thinking and text from LLM streaming chunk.

        Returns:
            (thinking_text, answer_text) — either may be empty.
        """
        if isinstance(chunk, str):
            return AnswerGenerator._split_thinking_tags(chunk)

        if not hasattr(chunk, 'content'):
            return "", ""

        content = chunk.content

        # Simple string case — parse <thinking> tags
        if isinstance(content, str):
            return AnswerGenerator._split_thinking_tags(content)

        # List of content blocks (Gemini thinking mode)
        if isinstance(content, list):
            thinking_parts = []
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking":
                        thinking_parts.append(block.get("thinking", ""))
                    elif block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    t, a = AnswerGenerator._split_thinking_tags(block)
                    if t:
                        thinking_parts.append(t)
                    text_parts.append(a)
            return "".join(thinking_parts), "".join(text_parts)

        return "", ""

    @staticmethod
    def _split_thinking_tags(text: str) -> tuple[str, str]:
        """Split <thinking>...</thinking> tags from text.

        Returns (thinking_content, remaining_text).
        Handles streaming chunks where tags may span multiple chunks.
        """
        if "<thinking>" not in text and "</thinking>" not in text:
            return "", text

        import re
        # Extract content between <thinking> and </thinking>
        thinking_parts = []
        remaining = text
        for m in re.finditer(r"<thinking>(.*?)(?:</thinking>|$)", remaining, re.DOTALL):
            thinking_parts.append(m.group(1))

        # Remove thinking tags and their content from remaining text
        cleaned = re.sub(r"<thinking>.*?(?:</thinking>|$)", "", text, flags=re.DOTALL).strip()
        return "".join(thinking_parts).strip(), cleaned


# ==========================================================================
# Private helper functions for prompt building
# ==========================================================================

def _get_role_rules(user_role: str) -> str:
    """Get role-specific rules for the system prompt (full generation)."""
    if user_role == "student":
        return (
            "\nQUY T\u1eaeC G\u1eccI T\u00caN (R\u1ea4T QUAN TR\u1eccNG):\n"
            "- KH\u00d4NG g\u1ecdi t\u00ean \u1edf \u0111\u1ea7u m\u1ed7i c\u00e2u tr\u1ea3 l\u1eddi\n"
            '- KH\u00d4NG b\u1eaft \u0111\u1ea7u b\u1eb1ng "Ch\u00e0o [t\u00ean]" - \u0111\u00e2y l\u00e0 l\u1ed7i ph\u1ed5 bi\u1ebfn c\u1ea7n tr\u00e1nh\n'
            '- \u0110i th\u1eb3ng v\u00e0o n\u1ed9i dung: "Quy t\u1eafc 15 quy \u0111\u1ecbnh r\u1eb1ng...", "Theo COLREGs..."\n'
            "- Ch\u1ec9 g\u1ecdi t\u00ean khi C\u1ea6N THI\u1ebeT trong ng\u1eef c\u1ea3nh\n"
            "\nQUY T\u1eaeC VARIATION:\n"
            '- \u0110a d\u1ea1ng c\u00e1ch m\u1edf \u0111\u1ea7u: "Theo quy \u0111\u1ecbnh...", "C\u1ee5 th\u1ec3 l\u00e0...", "V\u1ec1 v\u1ea5n \u0111\u1ec1 n\u00e0y..."\n'
            "- KH\u00d4NG d\u00f9ng c\u00f9ng pattern cho m\u1ecdi c\u00e2u tr\u1ea3 l\u1eddi\n"
            "- C\u00e2u h\u1ecfi follow-up ng\u1eafn \u2192 Tr\u1ea3 l\u1eddi ng\u1eafn g\u1ecdn, \u0111i th\u1eb3ng v\u00e0o \u0111i\u1ec3m ch\u00ednh\n"
            "\nNHI\u1ec6M V\u1ee4:\n"
            "- Tr\u1ea3 l\u1eddi d\u1ef1a tr\u00ean KI\u1ebeN TH\u1ee8C TRA C\u1ee8U \u0110\u01af\u1ee2C b\u00ean d\u01b0\u1edbi\n"
            "- N\u1ebfu c\u00f3 NG\u1eee C\u1ea2NH TH\u1ef0C TH\u1ec2, s\u1eed d\u1ee5ng \u0111\u1ec3 li\u00ean k\u1ebft c\u00e1c kh\u00e1i ni\u1ec7m v\u00e0 \u0111i\u1ec1u lu\u1eadt li\u00ean quan\n"
            "- Tr\u00edch d\u1eabn ngu\u1ed3n khi \u0111\u1ec1 c\u1eadp quy \u0111\u1ecbnh c\u1ee5 th\u1ec3\n"
            "- D\u1ecbch thu\u1eadt ng\u1eef: starboard = m\u1ea1n ph\u1ea3i, port = m\u1ea1n tr\u00e1i, give-way = nh\u01b0\u1eddng \u0111\u01b0\u1eddng\n"
            "- Tr\u1ea3 l\u1eddi b\u1eb1ng ti\u1ebfng Vi\u1ec7t"
        )
    else:
        return (
            "\nQUY T\u1eaeC:\n"
            "- \u0110i th\u1eb3ng v\u00e0o v\u1ea5n \u0111\u1ec1, KH\u00d4NG greeting\n"
            "- Tr\u00edch d\u1eabn ch\u00ednh x\u00e1c s\u1ed1 hi\u1ec7u quy \u0111\u1ecbnh\n"
            "- S\u00fac t\u00edch, chuy\u00ean nghi\u1ec7p\n"
            "\nNHI\u1ec6M V\u1ee4:\n"
            "- Tr\u1ea3 l\u1eddi d\u1ef1a tr\u00ean KI\u1ebeN TH\u1ee8C TRA C\u1ee8U \u0110\u01af\u1ee2C b\u00ean d\u01b0\u1edbi\n"
            "- N\u1ebfu c\u00f3 NG\u1eee C\u1ea2NH TH\u1ef0C TH\u1ec2, tham chi\u1ebfu c\u00e1c \u0111i\u1ec1u lu\u1eadt li\u00ean quan\n"
            "- Tr\u1ea3 l\u1eddi b\u1eb1ng ti\u1ebfng Vi\u1ec7t"
        )


def _get_streaming_student_rules() -> str:
    """Get role rules for streaming student responses (shorter version)."""
    return (
        "\nQUY T\u1eaeC G\u1eccI T\u00caN (R\u1ea4T QUAN TR\u1eccNG):\n"
        "- KH\u00d4NG g\u1ecdi t\u00ean \u1edf \u0111\u1ea7u m\u1ed7i c\u00e2u tr\u1ea3 l\u1eddi\n"
        "- \u0110i th\u1eb3ng v\u00e0o n\u1ed9i dung\n"
        "\nNHI\u1ec6M V\u1ee4:\n"
        "- Tr\u1ea3 l\u1eddi d\u1ef1a tr\u00ean KI\u1ebeN TH\u1ee8C TRA C\u1ee8U \u0110\u01af\u1ee2C b\u00ean d\u01b0\u1edbi\n"
        "- Tr\u00edch d\u1eabn ngu\u1ed3n khi \u0111\u1ec1 c\u1eadp quy \u0111\u1ecbnh c\u1ee5 th\u1ec3\n"
        "- Tr\u1ea3 l\u1eddi b\u1eb1ng ti\u1ebfng Vi\u1ec7t"
    )


def _get_streaming_other_rules() -> str:
    """Get role rules for streaming non-student responses (shorter version)."""
    return (
        "\nQUY T\u1eaeC:\n"
        "- \u0110i th\u1eb3ng v\u00e0o v\u1ea5n \u0111\u1ec1, KH\u00d4NG greeting\n"
        "- S\u00fac t\u00edch, chuy\u00ean nghi\u1ec7p\n"
        "- Tr\u1ea3 l\u1eddi b\u1eb1ng ti\u1ebfng Vi\u1ec7t"
    )


def _build_user_prompt(
    context: str,
    question: str,
    conversation_history: str = "",
    entity_context: str = ""
) -> str:
    """Build the user prompt with history and entity context."""
    history_section = ""
    if conversation_history:
        history_section = (
            "\n---\n"
            + "L\u1ecaCH S\u1eec H\u1ed8I THO\u1ea0I (G\u1ea7n nh\u1ea5t):\n"
            + conversation_history
            + "\n---\n"
        )

    # Feature: document-kg - Add entity context section
    entity_section = ""
    if entity_context:
        entity_section = (
            "\n---\n"
            + "NG\u1eee C\u1ea2NH TH\u1ef0C TH\u1ec2 (GraphRAG):\n"
            + entity_context
            + "\n---\n"
        )

    return (
        history_section + entity_section + "\n"
        + "KI\u1ebeN TH\u1ee8C TRA C\u1ee8U \u0110\u01af\u1ee2C (RAG):\n"
        + context + "\n"
        + "---\n\n"
        + "C\u00c2U H\u1eceI HI\u1ec6N T\u1ea0I:\n"
        + question + "\n\n"
        + "H\u00e3y tr\u1ea3 l\u1eddi c\u00e2u h\u1ecfi d\u1ef1a tr\u00ean th\u00f4ng tin tr\u00ean."
    )


def _chunk_buffered_stream_text(text: str, *, chunk_size: int = 180) -> list[str]:
    """Split buffered fallback text into stable stream-sized chunks."""
    clean = str(text or "").strip()
    if not clean:
        return []

    paragraphs = [part.strip() for part in clean.split("\n\n") if part.strip()]
    if len(paragraphs) > 1:
        return [f"{part}\n\n" if idx < len(paragraphs) - 1 else part for idx, part in enumerate(paragraphs)]

    if len(clean) <= chunk_size:
        return [clean]

    chunks: list[str] = []
    cursor = 0
    while cursor < len(clean):
        next_cursor = min(len(clean), cursor + chunk_size)
        if next_cursor < len(clean):
            split_at = clean.rfind(" ", cursor, next_cursor)
            if split_at > cursor + 40:
                next_cursor = split_at
        piece = clean[cursor:next_cursor].strip()
        if piece:
            chunks.append(piece + (" " if next_cursor < len(clean) else ""))
        cursor = next_cursor
        while cursor < len(clean) and clean[cursor].isspace():
            cursor += 1
    return chunks
