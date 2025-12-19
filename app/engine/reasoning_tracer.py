"""
Reasoning Tracer - Explainability Layer for Agentic RAG

Captures and structures the AI reasoning process step-by-step
for transparency and user trust.

**Feature: reasoning-trace**
**CHỈ THỊ KỸ THUẬT SỐ 28: Explainability Layer**
**SOTA 2025: Chain of Thought + RAG Transparency**
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from app.models.schemas import ReasoningStep, ReasoningTrace
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StepContext:
    """Internal step tracking during processing"""
    step_name: str
    description: str
    start_time_ms: int
    confidence: Optional[float] = None
    result: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class ReasoningTracer:
    """
    Traces AI reasoning steps for explainability.
    
    Usage:
        tracer = ReasoningTracer()
        tracer.start_step("query_analysis", "Phân tích câu hỏi")
        # ... do work ...
        tracer.end_step(result="Câu hỏi về Điều 15", confidence=0.9)
        
        trace = tracer.build_trace()
    
    **Feature: reasoning-trace**
    **CHỈ THỊ KỸ THUẬT SỐ 28: Explainability Layer**
    """
    
    def __init__(self):
        """Initialize tracer"""
        self._steps: List[ReasoningStep] = []
        self._current_step: Optional[StepContext] = None
        self._start_time_ms: int = self._now_ms()
        self._was_corrected: bool = False
        self._correction_reason: Optional[str] = None
        
    def _now_ms(self) -> int:
        """Get current time in milliseconds"""
        return int(time.time() * 1000)
    
    def start_step(
        self,
        step_name: str,
        description: str
    ) -> None:
        """
        Start tracking a reasoning step.
        
        Args:
            step_name: Identifier (query_analysis, retrieval, grading, etc.)
            description: Human-readable description
        """
        # End previous step if not ended
        if self._current_step is not None:
            self.end_step(result="Auto-closed", confidence=None)
        
        self._current_step = StepContext(
            step_name=step_name,
            description=description,
            start_time_ms=self._now_ms()
        )
        logger.debug(f"[Tracer] Started step: {step_name}")
    
    def end_step(
        self,
        result: str,
        confidence: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        End current step with result.
        
        Args:
            result: Summary of step result
            confidence: Optional confidence score (0.0-1.0)
            details: Optional additional details
        """
        if self._current_step is None:
            logger.warning("[Tracer] end_step called without active step")
            return
        
        duration_ms = self._now_ms() - self._current_step.start_time_ms
        
        step = ReasoningStep(
            step_name=self._current_step.step_name,
            description=self._current_step.description,
            result=result,
            confidence=confidence,
            duration_ms=duration_ms,
            details=details
        )
        
        self._steps.append(step)
        logger.debug(f"[Tracer] Ended step: {self._current_step.step_name} ({duration_ms}ms)")
        self._current_step = None
    
    def record_correction(self, reason: str) -> None:
        """
        Record that a query correction/rewrite occurred.
        
        Args:
            reason: Why the query was rewritten
        """
        self._was_corrected = True
        self._correction_reason = reason
        logger.debug(f"[Tracer] Recorded correction: {reason}")
    
    def add_step(
        self,
        step_name: str,
        description: str,
        result: str,
        confidence: Optional[float] = None,
        duration_ms: int = 0,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add a complete step directly (for simple steps).
        
        Args:
            step_name: Step identifier
            description: What the step does
            result: Step result
            confidence: Optional confidence
            duration_ms: How long it took
            details: Optional extra details
        """
        step = ReasoningStep(
            step_name=step_name,
            description=description,
            result=result,
            confidence=confidence,
            duration_ms=duration_ms,
            details=details
        )
        self._steps.append(step)
    
    def build_trace(self, final_confidence: Optional[float] = None) -> ReasoningTrace:
        """
        Build the complete reasoning trace.
        
        Args:
            final_confidence: Override final confidence (defaults to avg of steps)
            
        Returns:
            ReasoningTrace object ready for response
        """
        # End any open step
        if self._current_step is not None:
            self.end_step(result="Auto-closed", confidence=None)
        
        # Calculate total duration
        total_duration_ms = self._now_ms() - self._start_time_ms
        
        # Calculate final confidence
        if final_confidence is None:
            confidences = [s.confidence for s in self._steps if s.confidence is not None]
            final_confidence = sum(confidences) / len(confidences) if confidences else 0.8
        
        trace = ReasoningTrace(
            total_steps=len(self._steps),
            total_duration_ms=total_duration_ms,
            was_corrected=self._was_corrected,
            correction_reason=self._correction_reason,
            final_confidence=final_confidence,
            steps=self._steps
        )
        
        logger.info(
            f"[Tracer] Built trace: {len(self._steps)} steps, "
            f"{total_duration_ms}ms, confidence={final_confidence:.2f}"
        )
        
        return trace
    
    def build_thinking_summary(self) -> str:
        """
        Generate prose thinking summary from traced steps.
        
        SOTA Pattern: OpenAI o1's reasoning.summary / DeepSeek R1's reasoning_content
        CHỈ THỊ SỐ 28: Explainability for LMS frontend display
        
        Converts structured ReasoningTrace steps into human-readable
        narrative format suitable for "Thought Process" UI display.
        
        Returns:
            Markdown-formatted thinking summary string
        """
        if not self._steps:
            return ""
        
        lines = ["**Quá trình suy nghĩ:**\n"]
        
        for i, step in enumerate(self._steps, 1):
            # Format: "1. **Description**: Result"
            lines.append(f"{i}. **{step.description}**: {step.result}")
            
            # Add confidence if available
            if step.confidence is not None:
                confidence_pct = step.confidence * 100
                lines.append(f"   _(Độ tin cậy: {confidence_pct:.0f}%)_")
        
        # Add correction note if applicable
        if self._was_corrected and self._correction_reason:
            lines.append(f"\n⚠️ **Lưu ý**: {self._correction_reason}")
        
        summary = "\n".join(lines)
        logger.debug(f"[Tracer] Built thinking summary: {len(summary)} chars")
        
        return summary
    
    def merge_trace(
        self,
        other_trace: ReasoningTrace,
        position: str = "after_first"
    ) -> None:
        """
        Merge steps from another trace into this tracer.
        
        CHỈ THỊ SỐ 31: Option C - Priority merge pattern.
        SOTA Pattern: Hierarchical trace merging (OpenAI o1, Claude, DeepSeek R1)
        
        Args:
            other_trace: ReasoningTrace to merge (e.g., from CorrectiveRAG)
            position: Where to insert other steps:
                - "after_first": Insert after first step (routing), before rest
                - "prepend": Insert at beginning
                - "append": Insert at end
        
        Example:
            Graph trace: [routing, quality_check, synthesis]
            CRAG trace: [query_analysis, retrieval, grading, generation, verification]
            
            After merge (position="after_first"):
            [routing, query_analysis, retrieval, grading, generation, verification, 
             quality_check, synthesis]
        """
        if other_trace is None or not other_trace.steps:
            return
        
        if position == "after_first" and len(self._steps) >= 1:
            # Insert CRAG steps after first step (routing)
            first_step = self._steps[0]
            remaining_steps = self._steps[1:]
            self._steps = [first_step] + list(other_trace.steps) + remaining_steps
        elif position == "prepend":
            self._steps = list(other_trace.steps) + self._steps
        else:  # append
            self._steps.extend(other_trace.steps)
        
        # Inherit correction info if present
        if other_trace.was_corrected:
            self._was_corrected = True
            self._correction_reason = other_trace.correction_reason
        
        logger.info(
            f"[Tracer] Merged {len(other_trace.steps)} steps from other trace, "
            f"total now: {len(self._steps)}"
        )
    
    def reset(self) -> None:
        """Reset tracer for reuse"""
        self._steps = []
        self._current_step = None
        self._start_time_ms = self._now_ms()
        self._was_corrected = False
        self._correction_reason = None


# Step name constants for consistency
class StepNames:
    """Standard step names for reasoning trace"""
    # Core CRAG steps
    QUERY_ANALYSIS = "query_analysis"
    RETRIEVAL = "retrieval"
    GRADING = "grading"
    QUERY_REWRITE = "query_rewrite"
    GENERATION = "generation"
    VERIFICATION = "verification"
    MEMORY_LOOKUP = "memory_lookup"
    TOOL_CALL = "tool_call"
    
    # CHỈ THỊ SỐ 30: Universal tracing step names
    ROUTING = "routing"  # Supervisor routing decision
    DIRECT_RESPONSE = "direct_response"  # Simple greetings
    TEACHING = "teaching"  # Tutor agent
    QUALITY_CHECK = "quality_check"  # Grader agent
    SYNTHESIS = "synthesis"  # Final synthesizer


def get_reasoning_tracer() -> ReasoningTracer:
    """Factory function to create a new tracer"""
    return ReasoningTracer()
