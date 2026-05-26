"""WiiiChatModel — native AsyncOpenAI-backed chat model.

Phase 9a (runtime migration epic #207): dropped ``BaseChatModel`` inheritance.
The class now returns Wiii native ``Message`` and ``StreamChunk`` types instead
of LangChain ``AIMessage`` / ``ChatGenerationChunk``.

Backward compatibility is preserved via duck typing:
- Consumers reading ``.content`` keep working — ``Message.content`` exists.
- Consumers reading ``.tool_calls`` keep working — ``Message.tool_calls`` exists.
- Streaming consumers reading ``chunk.message.content`` keep working — ``StreamChunk.message``
  is a self-pointing shim. Direct ``chunk.content`` access also works.
- ``chunk.tool_call_chunks`` and ``chunk + chunk`` accumulator both supported.

Provider coverage unchanged: Gemini / OpenAI / Ollama / Zhipu / OpenRouter all
expose OpenAI-compatible endpoints, so the underlying ``openai.AsyncOpenAI`` SDK
suffices.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.engine.messages import Message
from app.engine.messages_adapters import from_openai_response, to_openai_dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# StreamChunk — Wiii native streaming delta
# ---------------------------------------------------------------------------


@dataclass
class StreamChunk:
    """A single streaming delta from the underlying OpenAI-compat endpoint.

    Provides backward-compat duck typing so existing consumers iterating
    ``chunk.message.content`` / ``chunk.tool_call_chunks`` keep working.
    Direct ``chunk.content`` access is the preferred new style.
    """

    content: str = ""
    tool_call_chunks: list[dict] = field(default_factory=list)
    finish_reason: Optional[str] = None

    @property
    def message(self) -> "StreamChunk":
        """Self-pointing shim for ``chunk.message.content`` legacy access."""
        return self

    @property
    def tool_calls(self) -> list[dict]:
        """Resolve accumulated tool_call_chunks into completed tool_call dicts."""
        out: list[dict] = []
        for tcc in self.tool_call_chunks:
            args_raw = tcc.get("args") or ""
            try:
                parsed = json.loads(args_raw) if isinstance(args_raw, str) and args_raw else (args_raw or {})
            except (json.JSONDecodeError, TypeError):
                parsed = args_raw if isinstance(args_raw, dict) else {}
            out.append(
                {
                    "id": tcc.get("id", "") or "",
                    "name": tcc.get("name", "") or "",
                    "args": parsed if isinstance(parsed, dict) else {},
                    "type": "tool_call",
                }
            )
        return out

    def __add__(self, other: Optional["StreamChunk"]) -> "StreamChunk":
        if other is None:
            return self
        merged_content = (self.content or "") + (other.content or "")
        merged_chunks: dict[int, dict] = {}
        for tcc in [*self.tool_call_chunks, *other.tool_call_chunks]:
            idx = tcc.get("index", 0) or 0
            cur = merged_chunks.setdefault(
                idx,
                {"name": "", "args": "", "id": "", "index": idx, "type": "tool_call_chunk"},
            )
            if tcc.get("name"):
                cur["name"] = tcc["name"]
            if tcc.get("id"):
                cur["id"] = tcc["id"]
            cur["args"] = (cur.get("args") or "") + (tcc.get("args") or "")
        return StreamChunk(
            content=merged_content,
            tool_call_chunks=list(merged_chunks.values()),
            finish_reason=other.finish_reason or self.finish_reason,
        )

    def __radd__(self, other: Optional["StreamChunk"]) -> "StreamChunk":
        if other is None:
            return self
        return other.__add__(self)


# ---------------------------------------------------------------------------
# Backward-compat input conversion
# ---------------------------------------------------------------------------


def _coerce_to_openai_messages(messages: Iterable[Any] | str) -> list[dict]:
    """Accept user text, native ``Message``, plain dict, or LC ``BaseMessage``.

    Phase 1 migrated SEND-side callers to dict; some history slices still pass
    raw LC objects through unchanged. Phase 9b will remove the latter.
    """
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]

    out: list[dict] = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
        elif isinstance(m, Message):
            out.append(to_openai_dict(m))
        else:
            out.append(_lc_message_to_dict(m))
    return out


def _lc_message_to_dict(msg: Any) -> dict:
    """Best-effort LC ``BaseMessage`` → OpenAI dict (backward-compat history slice)."""
    msg_type = (getattr(msg, "type", None) or msg.__class__.__name__ or "").lower()
    if "system" in msg_type:
        role = "system"
    elif "ai" in msg_type or "assistant" in msg_type:
        role = "assistant"
    elif "tool" in msg_type:
        role = "tool"
    elif "function" in msg_type:
        role = "function"
    else:
        role = "user"

    content = getattr(msg, "content", "")
    if isinstance(content, list):
        text_parts: list[str] = []
        passthrough_blocks: list[dict] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text") or ""))
                elif block.get("type") == "image_url":
                    passthrough_blocks.append(block)
                elif "text" in block:
                    text_parts.append(str(block["text"]))
            elif isinstance(block, str):
                text_parts.append(block)
        if passthrough_blocks:
            normalised: list[dict] = []
            joined = "\n".join(t for t in text_parts if t).strip()
            if joined:
                normalised.append({"type": "text", "text": joined})
            normalised.extend(passthrough_blocks)
            content = normalised
        else:
            content = "\n".join(t for t in text_parts if t)

    entry: dict[str, Any] = {"role": role}
    if isinstance(content, list):
        entry["content"] = content
    else:
        entry["content"] = "" if content is None else str(content)

    tool_call_id = getattr(msg, "tool_call_id", None)
    if tool_call_id:
        entry["tool_call_id"] = str(tool_call_id)

    name = getattr(msg, "name", None)
    if name and role == "function":
        entry["name"] = str(name)

    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        out_tcs: list[dict] = []
        for i, tc in enumerate(tool_calls):
            if isinstance(tc, dict):
                tc_id = tc.get("id") or f"call_{i}"
                tc_name = tc.get("name") or ""
                tc_args = tc.get("args") or {}
            else:
                tc_id = getattr(tc, "id", None) or f"call_{i}"
                tc_name = getattr(tc, "name", "") or ""
                tc_args = getattr(tc, "args", None) or {}
            args_str = (
                tc_args
                if isinstance(tc_args, str)
                else json.dumps(tc_args, ensure_ascii=False)
            )
            out_tcs.append(
                {
                    "id": str(tc_id),
                    "type": "function",
                    "function": {"name": str(tc_name), "arguments": args_str},
                }
            )
        entry["tool_calls"] = out_tcs

    return entry


# ---------------------------------------------------------------------------
# Provider-specific guards (preserved from pre-Phase-9 implementation)
# ---------------------------------------------------------------------------


_ZHIPU_HOSTS = ("open.bigmodel.cn",)

_ZHIPU_ALLOWED_PARAMS = frozenset({
    "model", "messages", "temperature", "top_p", "max_tokens",
    "stream", "stop", "tools", "tool_choice",
})

# LangChain/LangSmith internals that leak through call-level kwargs and break
# AsyncOpenAI ("unexpected keyword argument"). Filter before forwarding.
_LC_INTERNAL_KWARGS = frozenset({
    "ls_structured_output_format",
    "ls_provider",
    "ls_model_name",
    "ls_model_type",
    "ls_temperature",
    "ls_max_tokens",
    "ls_stop",
    "run_manager",
    "callbacks",
    "run_name",
    "run_id",
    "metadata",
    "tags",
    "configurable",
})


def _strip_unsupported_params(api_kwargs: dict[str, Any], base_url: str) -> dict[str, Any]:
    """Remove parameters not supported by the target provider."""
    api_kwargs = {k: v for k, v in api_kwargs.items() if k not in _LC_INTERNAL_KWARGS}
    if any(host in base_url for host in _ZHIPU_HOSTS):
        return {k: v for k, v in api_kwargs.items() if k in _ZHIPU_ALLOWED_PARAMS}
    return api_kwargs


_VALID_TOOL_CHOICE_STRINGS = frozenset({"auto", "none", "required", "validated"})

_TOOL_CHOICE_ALIASES: dict[str, str] = {
    "any": "required",
    "tool": "required",
}


def _normalize_tool_choice(value: Any) -> Any:
    """Translate plain tool-name strings into the OpenAI/Gemini descriptor object."""
    if isinstance(value, str):
        aliased = _TOOL_CHOICE_ALIASES.get(value, value)
        if aliased in _VALID_TOOL_CHOICE_STRINGS:
            return aliased
        return {"type": "function", "function": {"name": value}}
    return value


# ---------------------------------------------------------------------------
# Vietnamese space injection for Chinese-optimized tokenizers (Zhipu GLM)
# ---------------------------------------------------------------------------


_VI_VOWELS = frozenset(
    "aăâeêioôơuưy"
    "AĂÂEÊIOÔƠUƯY"
    "áàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệ"
    "íìỉĩịóòỏõọốồổỗộớờởỡợ"
    "úùủũụứừửữựýỳỷỹỵ"
    "ÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆ"
    "ÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢ"
    "ÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ"
)


_SPACE_AFTER_PUNCT = frozenset(".,!?;:")


class _ViSpaceInjector:
    """Inject missing spaces between Vietnamese syllables in streaming tokens."""

    __slots__ = ("_has_vowel", "_after_punct")

    def __init__(self) -> None:
        self._has_vowel = False
        self._after_punct = False

    def process(self, token: str) -> str:
        if not token:
            return token

        first_is_alpha = token[0].isalpha()
        token_has_vowel = any(ch in _VI_VOWELS for ch in token)
        inject = first_is_alpha and token_has_vowel and (self._has_vowel or self._after_punct)

        if inject:
            self._has_vowel = False
        self._after_punct = False

        for ch in token:
            if ch in _VI_VOWELS:
                self._has_vowel = True
            elif ch.isalpha():
                pass
            elif ch in _SPACE_AFTER_PUNCT:
                self._has_vowel = False
                self._after_punct = True
            else:
                self._has_vowel = False
                self._after_punct = False

        return (" " + token) if inject else token


# ---------------------------------------------------------------------------
# Streaming chunk conversion
# ---------------------------------------------------------------------------


def _openai_chunk_to_stream_chunk(chunk: Any) -> Optional[StreamChunk]:
    """Convert an OpenAI stream delta into a Wiii ``StreamChunk``."""
    if not getattr(chunk, "choices", None):
        return None

    choice = chunk.choices[0]
    delta = getattr(choice, "delta", None)
    if delta is None:
        return None

    content = getattr(delta, "content", None) or ""
    tool_call_chunks: list[dict] = []
    raw_tool_calls = getattr(delta, "tool_calls", None)
    if raw_tool_calls:
        for tc in raw_tool_calls:
            fn = getattr(tc, "function", None)
            tool_call_chunks.append(
                {
                    "name": (getattr(fn, "name", "") or "") if fn is not None else "",
                    "args": (getattr(fn, "arguments", "") or "") if fn is not None else "",
                    "id": getattr(tc, "id", None) or "",
                    "index": getattr(tc, "index", 0) or 0,
                    "type": "tool_call_chunk",
                }
            )

    return StreamChunk(
        content=content,
        tool_call_chunks=tool_call_chunks,
        finish_reason=getattr(choice, "finish_reason", None),
    )


# ---------------------------------------------------------------------------
# WiiiChatModel — native class
# ---------------------------------------------------------------------------


class WiiiChatModel(BaseModel):
    """AsyncOpenAI-backed chat model — native Wiii types, no LangChain inheritance.

    Methods preserved from the BaseChatModel surface:
    - ``ainvoke(messages, **kwargs) -> Message``
    - ``invoke(messages, **kwargs) -> Message``
    - ``astream(messages, **kwargs) -> AsyncIterator[StreamChunk]``
    - ``bind_tools(tools, **kwargs) -> WiiiChatModel`` (new instance with tools)
    - ``with_structured_output(schema, **kwargs) -> _StructuredOutputWrapper``

    Usage::

        llm = WiiiChatModel(
            model="gemini-3.1-flash-lite-preview",
            api_key=settings.google_api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        result: Message = await llm.ainvoke([{"role": "user", "content": "Hi"}])
    """

    model: str = Field(description="Model name (e.g., gemini-3.1-flash-lite-preview)")
    api_key: str = Field(description="API key for the provider")
    base_url: str = Field(default="", description="OpenAI-compatible base URL")
    temperature: float = Field(default=0.5, description="Sampling temperature")
    streaming: bool = Field(default=True, description="Enable streaming")
    model_kwargs: dict = Field(
        default_factory=dict,
        description="Extra kwargs passed to the API (tools, tool_choice, extra_body, ...)",
    )

    # Pydantic v2 config — allow ``setattr`` for ``_wiii_*`` runtime metadata.
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        populate_by_name=True,
        extra="allow",
    )

    _client: Optional[AsyncOpenAI] = None

    # ------------------------------------------------------------------ #
    # Provider client
    # ------------------------------------------------------------------ #
    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            object.__setattr__(self, "_client", AsyncOpenAI(**kwargs))
        return self._client  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # ainvoke / invoke
    # ------------------------------------------------------------------ #
    def _build_api_kwargs(
        self,
        messages: Iterable[Any] | str,
        kwargs: dict[str, Any],
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        oa_msgs = _coerce_to_openai_messages(messages)

        api_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": oa_msgs,
            "temperature": self.temperature,
            **self.model_kwargs,
        }
        if stream:
            api_kwargs["stream"] = True

        if "tools" in kwargs:
            api_kwargs["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            api_kwargs["tool_choice"] = kwargs["tool_choice"]
        stop = kwargs.get("stop")
        if stop:
            api_kwargs["stop"] = stop

        if "tool_choice" in api_kwargs:
            api_kwargs["tool_choice"] = _normalize_tool_choice(api_kwargs["tool_choice"])

        # Phase 11c: thread the active replay seed through to OpenAI-compat
        # providers so eval replays reproduce the original sampling. The
        # provider-specific param strip below drops ``seed`` for backends
        # that don't accept it (e.g. Zhipu), so this is safe to set always.
        from app.engine.runtime.replay_context import get_replay_seed_int

        replay_seed = get_replay_seed_int()
        if replay_seed is not None:
            api_kwargs["seed"] = replay_seed

        return _strip_unsupported_params(api_kwargs, self.base_url)

    async def ainvoke(self, messages: Iterable[Any] | str, **kwargs: Any) -> Message:
        """Async invoke. Returns a native ``Message`` with ``.content`` + ``.tool_calls``."""
        client = self._get_client()
        api_kwargs = self._build_api_kwargs(messages, kwargs, stream=False)

        # Phase 35 — proactive RPM throttle (client-side). Off by default; opt-in
        # via env (e.g. NVIDIA_RPM_LIMIT=30). Smooths burst load to avoid 429.
        try:
            from app.engine.llm_providers.rpm_limiter import get_provider_rpm_limiter
            provider_key = getattr(self, "_wiii_provider_name", None) or ""
            limiter = get_provider_rpm_limiter(str(provider_key).lower())
            if limiter is not None:
                await limiter.acquire()
        except Exception:  # noqa: BLE001
            pass  # rate limiter is best-effort; never block the call

        response = await client.chat.completions.create(**api_kwargs)

        if not getattr(response, "choices", None):
            return Message(role="assistant", content="")

        return from_openai_response(response.choices[0].message)

    def invoke(self, messages: Iterable[Any] | str, **kwargs: Any) -> Message:
        """Sync invoke — bridges to ``ainvoke`` via thread-pool when in async context."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.ainvoke(messages, **kwargs))
                return future.result()
        return asyncio.run(self.ainvoke(messages, **kwargs))

    # ------------------------------------------------------------------ #
    # astream
    # ------------------------------------------------------------------ #
    async def astream(
        self,
        messages: Iterable[Any] | str,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Async stream. Yields ``StreamChunk`` (with ``.content`` + ``.message`` shim)."""
        client = self._get_client()
        api_kwargs = self._build_api_kwargs(messages, kwargs, stream=True)

        injector = (
            _ViSpaceInjector()
            if any(host in self.base_url for host in _ZHIPU_HOSTS)
            else None
        )

        stream = await client.chat.completions.create(**api_kwargs)
        async for raw_chunk in stream:
            sc = _openai_chunk_to_stream_chunk(raw_chunk)
            if sc is None:
                continue
            if injector and sc.content:
                sc = StreamChunk(
                    content=injector.process(sc.content),
                    tool_call_chunks=sc.tool_call_chunks,
                    finish_reason=sc.finish_reason,
                )
            yield sc

    # ------------------------------------------------------------------ #
    # bind_tools / with_structured_output
    # ------------------------------------------------------------------ #
    def bind_tools(self, tools: list, **kwargs: Any) -> "WiiiChatModel":
        """Bind tools to the model. Returns a new ``WiiiChatModel`` with tools attached."""
        openai_tools: list[dict] = []
        for tool in tools:
            if isinstance(tool, dict) and "type" in tool:
                openai_tools.append(tool)
            elif hasattr(tool, "args_schema") and getattr(tool.args_schema, "schema", None):
                try:
                    schema = tool.args_schema.schema()
                except Exception:
                    schema = getattr(tool.args_schema, "model_json_schema", lambda: {})()
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": getattr(tool, "name", ""),
                            "description": getattr(tool, "description", "") or "",
                            "parameters": schema,
                        },
                    }
                )
            elif hasattr(tool, "name") and hasattr(tool, "description"):
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": getattr(tool, "parameters", {}),
                        },
                    }
                )

        new_model_kwargs = {**self.model_kwargs, "tools": openai_tools}
        if "tool_choice" in kwargs:
            new_model_kwargs["tool_choice"] = kwargs["tool_choice"]

        return self.model_copy(update={"model_kwargs": new_model_kwargs})

    def with_structured_output(
        self,
        schema: Any,
        **kwargs: Any,
    ) -> "_StructuredOutputWrapper":
        """Native structured-output wrapper.

        Returns an object whose ``ainvoke`` parses the LLM JSON response into
        ``schema`` (a Pydantic class). The previous behaviour came from
        ``BaseChatModel`` default; we re-implement minimally.
        """
        return _StructuredOutputWrapper(llm=self, output_schema=schema)


# ---------------------------------------------------------------------------
# Structured-output wrapper
# ---------------------------------------------------------------------------


class _StructuredOutputWrapper(BaseModel):
    """Wraps ``WiiiChatModel`` to coerce JSON responses into a Pydantic schema."""

    llm: Any  # WiiiChatModel — Any avoids forward-ref dance
    output_schema: Any  # Pydantic class

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    def _build_messages_with_instruction(self, messages: Iterable[Any] | str) -> list[Any]:
        try:
            schema_text = json.dumps(
                self.output_schema.model_json_schema(),
                ensure_ascii=False,
            )
        except Exception:
            schema_text = ""
        instruction = (
            "Tra ve DUY NHAT JSON hop le theo schema sau. "
            "Khong them markdown, khong them giai thich."
        )
        if schema_text:
            instruction = f"{instruction}\nSchema: {schema_text}"

        as_list: list[Any]
        if isinstance(messages, str):
            as_list = [{"role": "user", "content": messages}]
        else:
            as_list = list(messages)
        if as_list and isinstance(as_list[0], dict) and as_list[0].get("role") == "system":
            head = dict(as_list[0])
            head["content"] = (head.get("content") or "") + "\n\n" + instruction
            as_list[0] = head
            return as_list

        if as_list and isinstance(as_list[0], Message) and as_list[0].role == "system":
            head_msg = as_list[0]
            updated = head_msg.model_copy(
                update={"content": (head_msg.content or "") + "\n\n" + instruction},
            )
            as_list[0] = updated
            return as_list

        return [{"role": "system", "content": instruction}, *as_list]

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:].strip()
        return text.strip()

    async def ainvoke(self, messages: Iterable[Any] | str, **kwargs: Any) -> Any:
        prepared = self._build_messages_with_instruction(messages)
        response = await self.llm.ainvoke(prepared, **kwargs)

        content = getattr(response, "content", None)
        if content is None:
            content = str(response)

        text = self._strip_fences(content if isinstance(content, str) else str(content))
        if not text:
            raise ValueError("Structured output: empty content from LLM")

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Structured output JSON parse failed: %s. Content: %r",
                exc,
                text[:200],
            )
            raise

        return self.output_schema.model_validate(data)

    def invoke(self, messages: Iterable[Any] | str, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.ainvoke(messages, **kwargs))
                return future.result()
        return asyncio.run(self.ainvoke(messages, **kwargs))

    def bind_tools(self, tools: list, **kwargs: Any) -> "_StructuredOutputWrapper":
        rebound_llm = self.llm.bind_tools(tools, **kwargs)
        return _StructuredOutputWrapper(llm=rebound_llm, output_schema=self.output_schema)


__all__ = [
    "WiiiChatModel",
    "StreamChunk",
    "_StructuredOutputWrapper",
]
