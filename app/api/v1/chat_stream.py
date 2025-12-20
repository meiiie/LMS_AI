"""
Streaming Chat API - Server-Sent Events (SSE)

CHỈ THỊ LMS INTEGRATION: Streaming response cho real-time UX
- Event types: thinking, answer, sources, suggested_questions, metadata, done, error
- Flow: Tool execution first, then stream final answer

**Feature: streaming-api**
"""

import asyncio
import json
import logging
import re
import time
from typing import AsyncGenerator

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import RequireAuth
from app.api.v1.chat import _generate_suggested_questions, _classify_query_type
from app.core.rate_limit import chat_rate_limit, limiter
from app.models.schemas import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


def format_sse(event: str, data: dict) -> str:
    """Format data as Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    auth: RequireAuth  # LMS Integration: Require authentication
):
    """
    Streaming Chat API - SSE Response
    
    LMS Integration: Real-time response streaming cho UX giống ChatGPT.
    
    Event Types:
    - thinking: AI reasoning process
    - answer: Text chunks của câu trả lời
    - sources: Nguồn tham khảo
    - suggested_questions: Câu hỏi gợi ý
    - metadata: Processing info
    - done: Stream completed
    - error: Error occurred
    """
    start_time = time.time()
    
    logger.info(
        f"[STREAM] Chat request from user {chat_request.user_id} "
        f"(role: {chat_request.role.value}): {chat_request.message[:50]}..."
    )
    
    async def generate_events() -> AsyncGenerator[str, None]:
        try:
            # Import services
            from app.services.chat_service import get_chat_service
            from app.engine.unified_agent import get_last_retrieved_sources, clear_retrieved_sources
            
            chat_service = get_chat_service()
            
            # Clear stale sources
            clear_retrieved_sources()
            
            # Phase 1: Send initial thinking event
            yield format_sse("thinking", {
                "content": "Đang phân tích câu hỏi..."
            })
            await asyncio.sleep(0.1)  # Allow flush
            
            # Phase 2: Process with normal flow (includes RAG search)
            # NOTE: Tool execution cannot be streamed, must complete first
            yield format_sse("thinking", {
                "content": "Đang tra cứu cơ sở dữ liệu..."
            })
            
            # Get response (full processing)
            internal_response = await chat_service.process_message(
                chat_request,
                background_save=lambda func, *args, **kwargs: None  # Skip background tasks in stream
            )
            
            processing_time = time.time() - start_time
            
            # Phase 3: Stream the answer in chunks
            answer = internal_response.message
            
            # Check if answer has <thinking> tags
            thinking_pattern = r'<thinking>(.*?)</thinking>'
            thinking_match = re.search(thinking_pattern, answer, re.DOTALL)
            
            if thinking_match:
                thinking_content = thinking_match.group(1).strip()
                # Stream thinking content
                yield format_sse("thinking", {
                    "content": thinking_content
                })
                # Remove thinking from answer
                answer = re.sub(thinking_pattern, '', answer, flags=re.DOTALL).strip()
            
            await asyncio.sleep(0.1)
            
            # Stream answer in chunks (simulate token-by-token)
            chunk_size = 50  # Characters per chunk
            for i in range(0, len(answer), chunk_size):
                chunk = answer[i:i + chunk_size]
                yield format_sse("answer", {"content": chunk})
                await asyncio.sleep(0.03)  # 30ms between chunks
            
            # Phase 4: Send sources
            sources_data = []
            if internal_response.sources:
                for src in internal_response.sources:
                    sources_data.append({
                        "title": src.title,
                        "content": src.content_snippet or "",
                        "image_url": getattr(src, 'image_url', None),
                        "page_number": getattr(src, 'page_number', None),
                        "document_id": getattr(src, 'document_id', None),
                        "bounding_boxes": getattr(src, 'bounding_boxes', None)
                    })
            
            yield format_sse("sources", {"sources": sources_data})
            await asyncio.sleep(0.1)
            
            # Phase 5: Send suggested questions
            suggested_questions = _generate_suggested_questions(
                chat_request.message,
                internal_response.message
            )
            yield format_sse("suggested_questions", {
                "questions": suggested_questions
            })
            await asyncio.sleep(0.1)
            
            # Phase 6: Send metadata
            # Extract analytics data
            topics_accessed = [src.title for src in (internal_response.sources or []) if src.title]
            document_ids_used = list(set(
                src.document_id for src in (internal_response.sources or []) if src.document_id
            ))
            confidence_score = min(0.5 + len(sources_data) * 0.1, 1.0) if sources_data else None
            query_type = _classify_query_type(chat_request.message)
            
            metadata = {
                "processing_time": round(processing_time, 3),
                "model": "maritime-rag-v1",
                "agent_type": internal_response.agent_type.value,
                "topics_accessed": topics_accessed,
                "confidence_score": round(confidence_score, 2) if confidence_score else None,
                "document_ids_used": document_ids_used,
                "query_type": query_type
            }
            yield format_sse("metadata", metadata)
            
            # Phase 7: Done - signal stream completion
            yield format_sse("done", {"status": "complete"})
            
            logger.info(f"[STREAM] Completed in {processing_time:.3f}s")
            
        except Exception as e:
            logger.exception(f"[STREAM] Error: {e}")
            yield format_sse("error", {
                "message": f"Lỗi xử lý: {str(e)}"
            })
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


# =============================================================================
# P3 SOTA: True Token Streaming (Dec 2025)
# Pattern: ChatGPT Progressive Response + Claude Interleaved Thinking
# First token: ~20s instead of ~60s
# =============================================================================

@router.post("/chat/stream/v2")
async def chat_stream_v2(
    request: Request,
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    auth: RequireAuth
):
    """
    P3 SOTA Streaming API - True Token-by-Token Streaming
    
    Difference from /chat/stream (v1):
    - v1: Waits for full response (~60s), then chunks it (fake streaming)
    - v2: Streams tokens as they arrive from LLM (~20s first token)
    
    Event Types:
    - thinking: Progress updates (retrieval, grading)
    - answer: Real-time token chunks
    - sources: Document sources after completion
    - done: Stream completed
    - error: Error occurred
    
    **Feature: p3-sota-streaming**
    """
    start_time = time.time()
    
    logger.info(
        f"[STREAM-V2] Request from {chat_request.user_id}: {chat_request.message[:50]}..."
    )
    
    async def generate_events_v2() -> AsyncGenerator[str, None]:
        try:
            # Import RAG Agent for direct streaming
            from app.engine.agentic_rag.rag_agent import RAGAgent
            from app.services.hybrid_search_service import get_hybrid_search_service
            
            # Initialize RAG Agent
            hybrid_search = get_hybrid_search_service()
            rag_agent = RAGAgent(hybrid_search_service=hybrid_search)
            
            # Initial thinking event
            yield format_sse("thinking", {
                "content": "🎯 Đang phân tích câu hỏi..."
            })
            await asyncio.sleep(0.05)
            
            # P3 SOTA: Use streaming query
            async for event in rag_agent.query_streaming(
                question=chat_request.message,
                limit=10,
                conversation_history="",
                user_role=chat_request.role.value
            ):
                event_type = event.get("type", "answer")
                content = event.get("content", "")
                
                if event_type == "thinking":
                    yield format_sse("thinking", {"content": content})
                elif event_type == "answer":
                    yield format_sse("answer", {"content": content})
                elif event_type == "sources":
                    yield format_sse("sources", {"sources": content})
                elif event_type == "done":
                    pass  # Will send done at the end
                elif event_type == "error":
                    yield format_sse("error", {"message": content})
                    return
                
                await asyncio.sleep(0.01)  # Micro delay for flush
            
            # Processing time
            processing_time = time.time() - start_time
            
            # Send metadata
            metadata = {
                "processing_time": round(processing_time, 3),
                "model": "maritime-rag-v1",
                "agent_type": "rag",
                "streaming_version": "v2",
                "first_token_time": "progressive"
            }
            yield format_sse("metadata", metadata)
            
            # Done signal
            yield format_sse("done", {"status": "complete"})
            
            logger.info(f"[STREAM-V2] Completed in {processing_time:.3f}s")
            
        except Exception as e:
            logger.exception(f"[STREAM-V2] Error: {e}")
            yield format_sse("error", {
                "message": f"Lỗi xử lý: {str(e)}"
            })
    
    return StreamingResponse(
        generate_events_v2(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# =============================================================================
# P3+ SOTA: Full CRAG Pipeline + True Token Streaming (Dec 2025)
# Pattern: OpenAI Responses API + Claude Extended Thinking + Gemini astream
# Best of both worlds: V1 quality + V2 streaming UX
# =============================================================================

@router.post("/chat/stream/v3")
async def chat_stream_v3(
    request: Request,
    chat_request: ChatRequest,
    background_tasks: BackgroundTasks,
    auth: RequireAuth
):
    """
    P3+ SOTA: Full CRAG Pipeline + True Token Streaming
    
    Best of both worlds:
    - Quality: Full CRAG pipeline (grading, verification, reasoning_trace)
    - UX: Progressive events at each step + true token streaming
    
    Event Types (following OpenAI Responses API pattern):
    - status: Processing stage updates (shown as typing indicator)
    - thinking: AI reasoning steps (shown in collapsible section)
    - answer: Response tokens (streamed real-time via LLM.astream())
    - sources: Citation list with image_url for PDF highlighting
    - metadata: reasoning_trace, confidence, timing
    - done: Stream complete
    - error: Error occurred
    
    Timeline:
    - 0s: First status event (user sees progress immediately)
    - 4s: Analysis complete
    - 7s: Retrieval complete  
    - 11s: Grading complete
    - 25s: First answer token
    - 55s: Complete with reasoning_trace
    
    **Feature: p3-v3-full-crag-streaming**
    """
    start_time = time.time()
    
    logger.info(
        f"[STREAM-V3] Request from {chat_request.user_id}: {chat_request.message[:50]}..."
    )
    
    async def generate_events_v3() -> AsyncGenerator[str, None]:
        try:
            # Import CRAG for full pipeline with streaming
            from app.engine.agentic_rag.corrective_rag import get_corrective_rag
            from app.services.memory_service import get_user_memory
            
            # Get CRAG singleton
            crag = get_corrective_rag()
            
            # Build context
            context = {
                "user_id": chat_request.user_id,
                "user_role": chat_request.role.value,
                "conversation_history": ""
            }
            
            # Optionally fetch memory for personalization
            try:
                memory = await get_user_memory(chat_request.user_id)
                if memory and memory.get("name"):
                    context["user_name"] = memory.get("name")
            except Exception as e:
                logger.debug(f"[STREAM-V3] Memory fetch skipped: {e}")
            
            # Stream events from CRAG pipeline
            async for event in crag.process_streaming(
                query=chat_request.message,
                context=context
            ):
                event_type = event.get("type", "answer")
                content = event.get("content", "")
                
                if event_type == "status":
                    # Status events are shown as typing indicator
                    yield format_sse("thinking", {"content": content})
                    
                elif event_type == "thinking":
                    # Thinking events show AI reasoning
                    yield format_sse("thinking", {
                        "content": content,
                        "step": event.get("step"),
                        "details": event.get("details")
                    })
                    
                elif event_type == "answer":
                    # Answer tokens streamed real-time
                    yield format_sse("answer", {"content": content})
                    
                elif event_type == "sources":
                    # Sources with image_url for PDF highlighting
                    yield format_sse("sources", {"sources": content})
                    
                elif event_type == "metadata":
                    # Metadata includes reasoning_trace
                    metadata = content
                    metadata["streaming_version"] = "v3"
                    yield format_sse("metadata", metadata)
                    
                elif event_type == "done":
                    # Will send done at the end
                    pass
                    
                elif event_type == "error":
                    yield format_sse("error", {"message": content})
                    return
                
                # Micro delay for flush
                await asyncio.sleep(0.01)
            
            # Processing time
            processing_time = time.time() - start_time
            
            # Done signal
            yield format_sse("done", {
                "status": "complete",
                "total_time": round(processing_time, 3)
            })
            
            logger.info(f"[STREAM-V3] Completed in {processing_time:.3f}s")
            
        except Exception as e:
            logger.exception(f"[STREAM-V3] Error: {e}")
            yield format_sse("error", {
                "message": f"Lỗi xử lý: {str(e)}"
            })
    
    return StreamingResponse(
        generate_events_v3(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

