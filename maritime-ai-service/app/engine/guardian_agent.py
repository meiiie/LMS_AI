"""
Guardian Agent - LLM-based Content Moderation

CHỈ THỊ KỸ THUẬT SỐ 21: LLM CONTENT GUARDIAN

Sử dụng Gemini để:
1. Validate custom pronoun requests (gọi tôi là công chúa)
2. Detect inappropriate content contextually
3. Fallback to rule-based when LLM unavailable

Architecture:
    User Message -> Quick Check -> LLM Validation -> Decision
                                                  -> ALLOW + custom pronouns
                                                  -> BLOCK + reason
                                                  -> FLAG + review needed

**Feature: wiii**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 21**
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

from app.core.config import settings
from app.core.resilience import retry_on_transient

logger = logging.getLogger(__name__)


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class GuardianDecision:
    """
    Result of Guardian Agent validation.
    
    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    action: Literal["ALLOW", "BLOCK", "FLAG"]
    reason: Optional[str] = None
    custom_pronouns: Optional[Dict[str, str]] = None
    confidence: float = 1.0
    used_llm: bool = False
    latency_ms: int = 0
    cached: bool = False


@dataclass
class PronounValidationResult:
    """
    Result of custom pronoun request validation.
    
    **Validates: Requirements 1.2, 1.3**
    """
    approved: bool
    user_called: str  # How AI calls user (e.g., "công chúa")
    ai_self: str  # How AI refers to itself (e.g., "trẫm")
    rejection_reason: Optional[str] = None


@dataclass
class GuardianConfig:
    """Configuration for Guardian Agent."""
    enable_llm: bool = True
    timeout_ms: int = 2000
    cache_ttl_seconds: int = 3600
    skip_patterns: List[str] = field(default_factory=lambda: [
        "chào", "hello", "hi", "xin chào", "hey",
        "cảm ơn", "thanks", "thank you",
        "tạm biệt", "bye", "goodbye"
    ])


# =============================================================================
# GUARDIAN PROMPT TEMPLATE
# =============================================================================

GUARDIAN_PROMPT = """Bạn là Guardian Agent, chuyên kiểm tra nội dung tin nhắn trong hệ thống Wiii.

NHIỆM VỤ: Phân tích tin nhắn sau và trả về JSON.

TIN NHẮN: "{message}"
NGỮ CẢNH: {context}

PHÂN TÍCH:
1. Có yêu cầu xưng hô đặc biệt không? (ví dụ: "gọi tôi là X", "xưng hô với tôi là Y")
2. Có nội dung tục tĩu/xúc phạm không?
3. Nếu có từ "nhạy cảm", có phù hợp với ngữ cảnh hàng hải không?

QUY TẮC:
- "cướp biển", "piracy" trong ngữ cảnh hàng hải → ALLOW
- "công chúa", "hoàng tử", "thuyền trưởng" là roleplay → ALLOW
- Từ tục tĩu tiếng Việt: mày, tao, đ.m, vcl, vl, đéo, địt → BLOCK
- Xúc phạm: đồ ngu, thằng khốn, con điên → BLOCK
- Nếu không chắc chắn → FLAG (không BLOCK)

TRẢ VỀ JSON (KHÔNG có markdown, chỉ JSON thuần):
{{
    "action": "ALLOW" hoặc "BLOCK" hoặc "FLAG",
    "reason": "lý do nếu BLOCK/FLAG, null nếu ALLOW",
    "pronoun_request": {{
        "detected": true hoặc false,
        "user_called": "cách gọi user nếu detected",
        "ai_self": "cách AI tự xưng nếu detected",
        "appropriate": true hoặc false
    }},
    "confidence": 0.0 đến 1.0
}}
"""


# =============================================================================
# GUARDIAN AGENT CLASS
# =============================================================================

class GuardianAgent:
    """
    LLM-based content moderation agent.
    
    CHỈ THỊ KỸ THUẬT SỐ 21: LLM Content Guardian
    
    Features:
    - Validate custom pronoun requests
    - Detect inappropriate content contextually
    - Fallback to rule-based when LLM unavailable
    - Cache decisions for performance
    
    **Validates: Requirements 1.1, 2.1, 3.1**
    """
    
    def __init__(
        self,
        config: Optional[GuardianConfig] = None,
        fallback_guardrails = None
    ):
        """
        Initialize Guardian Agent.
        
        Args:
            config: GuardianConfig for customization
            fallback_guardrails: Existing Guardrails for fallback
        """
        self._config = config or GuardianConfig()
        self._fallback = fallback_guardrails
        self._llm = None
        self._cache: Dict[str, tuple] = {}  # hash -> (decision, timestamp)
        
        self._init_llm()
        logger.info("GuardianAgent initialized")
    
    def _init_llm(self):
        """Initialize default LLM from shared pool for validation."""
        if not self._config.enable_llm:
            logger.info("GuardianAgent: LLM disabled by config")
            return

        try:
            from app.engine.multi_agent.agent_config import AgentConfigRegistry

            if not settings.google_api_key:
                logger.warning("GuardianAgent: No Google API key")
                return

            # Sprint 69: Use AgentConfigRegistry for per-node LLM config
            self._llm = AgentConfigRegistry.get_llm("guardian")
            logger.info("GuardianAgent: LLM initialized (via AgentConfigRegistry)")

        except Exception as e:
            logger.error("GuardianAgent: Failed to initialize LLM: %s", e)

    def _get_llm_for_provider(self, provider: Optional[str] = None):
        """Get LLM respecting per-request provider override.

        Falls back to fresh AgentConfigRegistry lookup (not cached
        self._llm which may be stale/dead after 429).
        """
        if provider and provider != "auto":
            try:
                from app.engine.multi_agent.agent_config import AgentConfigRegistry
                return AgentConfigRegistry.get_llm(
                    "guardian", provider_override=provider,
                )
            except Exception:
                pass
        try:
            from app.engine.multi_agent.agent_config import AgentConfigRegistry
            return AgentConfigRegistry.get_llm("guardian")
        except Exception:
            return self._llm
    
    async def validate_message(
        self,
        message: str,
        context: Optional[str] = None,
        domain_id: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> GuardianDecision:
        """
        Validate user message using LLM.
        
        Args:
            message: User's message to validate
            context: Optional context (e.g., "maritime education")
            
        Returns:
            GuardianDecision with action and details
            
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        start_time = time.time()
        
        # Step 1: Check cache
        cached = self._get_cached_decision(message)
        if cached:
            cached.latency_ms = int((time.time() - start_time) * 1000)
            return cached
        
        # Step 2: Check if LLM can be skipped
        if self._should_skip_llm(message, domain_id=domain_id):
            decision = GuardianDecision(
                action="ALLOW",
                reason=None,
                used_llm=False,
                latency_ms=int((time.time() - start_time) * 1000)
            )
            return decision

        # Step 3: LLM validation (per-request provider-aware)
        llm = self._get_llm_for_provider(provider) if provider else self._llm
        if llm and self._config.enable_llm:
            try:
                decision = await self._validate_with_llm(
                    message,
                    context,
                    llm=llm,
                    provider=provider,
                )
                decision.latency_ms = int((time.time() - start_time) * 1000)

                # Cache the decision
                self._cache_decision(message, decision)

                return decision

            except Exception as e:
                logger.warning("GuardianAgent: LLM validation failed: %s", e)
                # Fall through to fallback

        # Step 4: Fallback to rule-based (with content filter)
        decision = await self._fallback_validation(message, domain_id=domain_id)
        decision.latency_ms = int((time.time() - start_time) * 1000)
        return decision
    
    async def validate_pronoun_request(
        self,
        message: str
    ) -> PronounValidationResult:
        """
        Validate custom pronoun request.
        
        Args:
            message: User's message containing pronoun request
            
        Returns:
            PronounValidationResult with approved pronouns or rejection
            
        **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
        """
        # Default pronouns
        default_result = PronounValidationResult(
            approved=False,
            user_called="bạn",
            ai_self="tôi",
            rejection_reason="Không phát hiện yêu cầu xưng hô"
        )
        
        # Check if message contains pronoun request pattern
        if not self._contains_pronoun_request(message):
            return default_result
        
        # Use LLM to validate
        decision = await self.validate_message(message, context="pronoun_request")
        
        if decision.custom_pronouns:
            return PronounValidationResult(
                approved=True,
                user_called=decision.custom_pronouns.get("user_called", "bạn"),
                ai_self=decision.custom_pronouns.get("ai_self", "tôi"),
                rejection_reason=None
            )
        
        if decision.action == "BLOCK":
            return PronounValidationResult(
                approved=False,
                user_called="bạn",
                ai_self="tôi",
                rejection_reason=decision.reason or "Yêu cầu xưng hô không phù hợp"
            )
        
        return default_result
    
    def _should_skip_llm(self, message: str, domain_id: Optional[str] = None) -> bool:
        """
        Check if LLM validation can be skipped.

        Simple greetings and common phrases don't need LLM.
        Sprint 74: Short messages (< 200 chars) without banned words skip LLM.
        Sprint 76: Replaced _BANNED_WORDS with ContentFilter (normalization,
        120+ entries, severity levels, domain allowlists).

        **Validates: Requirements 5.3**
        """
        message_lower = message.lower().strip()

        # Check skip patterns
        for pattern in self._config.skip_patterns:
            if message_lower == pattern or message_lower.startswith(pattern + " "):
                logger.debug("GuardianAgent: Skipping LLM for '%s...'", message[:30])
                return True

        # Very short messages (< 5 chars) are usually greetings
        if len(message_lower) < 5:
            return True

        # Sprint 76/247: deterministic filter for safe short-to-medium turns.
        # WARN+ content still escalates to the Guardian LLM.
        if len(message_lower) < 500:
            from app.engine.content_filter import get_content_filter
            result = get_content_filter(domain_id).check(message)
            if result.severity >= 3:  # WARN or higher → needs LLM
                return False
            return True  # ALLOW or FLAG → skip LLM

        return False
    
    def _contains_pronoun_request(self, message: str) -> bool:
        """Check if message contains pronoun request pattern."""
        patterns = [
            "gọi tôi là",
            "gọi mình là",
            "gọi em là",
            "xưng hô với tôi",
            "xưng hô với mình",
            "bạn là",
            "cậu là",
            "anh là",
            "chị là",
            # Patterns for AI self-reference
            "bạn là trẫm",
            "cậu là trẫm",
            "anh là trẫm",
            "chị là trẫm",
            "bạn tự xưng",
            "cậu tự xưng",
        ]
        message_lower = message.lower()
        return any(p in message_lower for p in patterns)
    
    async def _validate_with_llm(
        self,
        message: str,
        context: Optional[str] = None,
        *,
        llm=None,
        provider: Optional[str] = None,
    ) -> GuardianDecision:
        """
        Validate message using LLM.

        **Validates: Requirements 2.1**
        """
        prompt = GUARDIAN_PROMPT.format(
            message=message,
            context=context or "education"
        )

        try:
            # Sprint 67: Structured Outputs — constrained decoding for Guardian
            from app.core.config import settings as _settings
            if getattr(_settings, 'enable_structured_outputs', False):
                return await self._validate_structured(prompt, llm=llm, provider=provider)

            return await self._validate_legacy(prompt, llm=llm)

        except Exception as e:
            logger.error("GuardianAgent: LLM call failed: %s", e)
            raise

    @retry_on_transient()
    async def _validate_structured(self, prompt: str, *, llm=None, provider: Optional[str] = None) -> GuardianDecision:
        """Validate using structured output (constrained decoding)."""
        from app.engine.structured_schemas import GuardianLLMResult
        from app.services.structured_invoke_service import StructuredInvokeService

        result = await StructuredInvokeService.ainvoke(
            llm=(llm or self._llm),
            schema=GuardianLLMResult,
            payload=prompt,
            tier="light",
            provider=provider,
        )

        # Convert structured result to GuardianDecision
        custom_pronouns = None
        if result.pronoun_request and result.pronoun_request.detected and result.pronoun_request.appropriate:
            custom_pronouns = {
                "user_called": result.pronoun_request.user_called,
                "ai_self": result.pronoun_request.ai_self,
            }

        return GuardianDecision(
            action=result.action,
            reason=result.reason,
            custom_pronouns=custom_pronouns,
            confidence=result.confidence,
            used_llm=True,
        )

    @retry_on_transient()
    async def _validate_legacy(self, prompt: str, *, llm=None) -> GuardianDecision:
        """Validate using legacy JSON parsing."""
        response = await (llm or self._llm).ainvoke(prompt)

        # SOTA FIX: Handle Gemini 2.5 Flash content block format
        from app.services.output_processor import extract_thinking_from_response
        text_content, _ = extract_thinking_from_response(response.content)
        content = text_content.strip()

        # Parse JSON response
        decision = self._parse_llm_response(content)
        decision.used_llm = True

        return decision
    
    def _parse_llm_response(self, content: str) -> GuardianDecision:
        """Parse LLM JSON response into GuardianDecision."""
        try:
            # Clean JSON
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            data = json.loads(content)
            
            # Extract pronoun info if present
            custom_pronouns = None
            pronoun_data = data.get("pronoun_request", {})
            if pronoun_data.get("detected") and pronoun_data.get("appropriate"):
                custom_pronouns = {
                    "user_called": pronoun_data.get("user_called", "bạn"),
                    "ai_self": pronoun_data.get("ai_self", "tôi")
                }
            
            return GuardianDecision(
                action=data.get("action", "FLAG"),
                reason=data.get("reason"),
                custom_pronouns=custom_pronouns,
                confidence=data.get("confidence", 0.8),
                used_llm=True
            )
            
        except json.JSONDecodeError as e:
            logger.warning("GuardianAgent: Failed to parse LLM response: %s", e)
            # Default to FLAG when parsing fails
            return GuardianDecision(
                action="FLAG",
                reason="Failed to parse LLM response",
                confidence=0.5,
                used_llm=True
            )
    
    async def _fallback_validation(
        self, message: str, domain_id: Optional[str] = None
    ) -> GuardianDecision:
        """
        Fallback to rule-based validation using ContentFilter.

        Sprint 76: Replaced hardcoded word list with ContentFilter.

        **Validates: Requirements 3.1, 3.2**
        """
        logger.info("GuardianAgent: Using fallback validation")

        if self._fallback:
            result = await self._fallback.validate_input(message)
            return GuardianDecision(
                action="BLOCK" if not result.is_valid else "ALLOW",
                reason="; ".join(result.issues) if result.issues else None,
                used_llm=False
            )

        # Sprint 76: Content filter replaces hardcoded word list
        from app.engine.content_filter import get_content_filter, Severity
        result = get_content_filter(domain_id).check(message)

        if result.severity >= Severity.BLOCK:
            return GuardianDecision(
                action="BLOCK",
                reason=f"Content filter: {', '.join(result.matched_terms)}",
                used_llm=False
            )
        if result.severity >= Severity.WARN:
            return GuardianDecision(
                action="FLAG",
                reason=f"Moderate concern: {', '.join(result.matched_terms)}",
                used_llm=False
            )

        return GuardianDecision(
            action="ALLOW",
            used_llm=False
        )
    
    def _get_cached_decision(self, message: str) -> Optional[GuardianDecision]:
        """
        Get cached decision for message.
        
        **Validates: Requirements 5.2**
        """
        cache_key = self._hash_message(message)
        
        if cache_key in self._cache:
            decision, timestamp = self._cache[cache_key]
            
            # Check TTL
            if time.time() - timestamp < self._config.cache_ttl_seconds:
                logger.debug("GuardianAgent: Cache hit for '%s...'", message[:30])
                # Return a copy with cached flag
                return GuardianDecision(
                    action=decision.action,
                    reason=decision.reason,
                    custom_pronouns=decision.custom_pronouns,
                    confidence=decision.confidence,
                    used_llm=decision.used_llm,
                    cached=True
                )
            else:
                # Expired, remove from cache
                del self._cache[cache_key]
        
        return None
    
    def _cache_decision(self, message: str, decision: GuardianDecision):
        """Cache a decision for future use."""
        cache_key = self._hash_message(message)
        self._cache[cache_key] = (decision, time.time())
        
        # Limit cache size
        if len(self._cache) > 1000:
            # Remove oldest entries
            oldest_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k][1]
            )[:100]
            for key in oldest_keys:
                del self._cache[key]
    
    def _hash_message(self, message: str) -> str:
        """Hash message for cache key."""
        return hashlib.md5(message.lower().strip().encode()).hexdigest()
    
    def is_available(self) -> bool:
        """Check if Guardian Agent is ready."""
        return self._llm is not None or self._fallback is not None


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

_guardian_agent: Optional[GuardianAgent] = None


def get_guardian_agent(fallback_guardrails=None) -> GuardianAgent:
    """Get or create GuardianAgent singleton."""
    global _guardian_agent
    if _guardian_agent is None:
        _guardian_agent = GuardianAgent(fallback_guardrails=fallback_guardrails)
    return _guardian_agent
