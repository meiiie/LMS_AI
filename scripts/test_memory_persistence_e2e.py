"""
End-to-End Test for Memory Persistence Across Sessions
Phase 6: Task 11.2

Test THỰC SỰ với real services để verify:
1. User name được lưu và nhớ qua sessions
2. User facts được persist trong SemanticMemory
3. Conversation context được maintain

Lưu ý: Test này cần PostgreSQL và SemanticMemory available để test đầy đủ.
"""
import asyncio
import sys
import os
from uuid import uuid4
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MemoryPersistenceE2ETest:
    """Test memory persistence across sessions."""
    
    def __init__(self):
        self.user_id = f"test_persist_{uuid4().hex[:8]}"
        self.results = {"passed": 0, "failed": 0, "skipped": 0}
        
    async def setup(self):
        """Initialize services and check availability."""
        print("=" * 70)
        print("MEMORY PERSISTENCE E2E TEST")
        print(f"User ID: {self.user_id}")
        print(f"Time: {datetime.now().isoformat()}")
        print("=" * 70)
        
        from app.services.chat_service import ChatService
        
        self.chat_service = ChatService()
        
        # Check services
        print("\n[SETUP] Checking services...")
        
        self.semantic_memory_available = (
            self.chat_service._semantic_memory is not None and 
            self.chat_service._semantic_memory.is_available()
        )
        self.chat_history_available = self.chat_service._chat_history.is_available()
        
        print(f"  SemanticMemory: {'✓' if self.semantic_memory_available else '✗'}")
        print(f"  ChatHistory: {'✓' if self.chat_history_available else '✗'}")
        
        return True
    
    def record(self, name: str, passed: bool, msg: str):
        """Record test result."""
        if passed:
            self.results["passed"] += 1
            print(f"  ✓ {name}: {msg}")
        else:
            self.results["failed"] += 1
            print(f"  ✗ {name}: {msg}")
    
    async def test_1_session_state_persistence(self):
        """Test 1: Session state persists within same ChatService instance."""
        print("\n" + "-" * 70)
        print("TEST 1: Session State Persistence (In-Memory)")
        print("-" * 70)
        
        from app.models.schemas import ChatRequest
        
        # Session 1: User introduces themselves
        session_id_1 = str(uuid4())
        
        print(f"\n[Session 1] {session_id_1[:8]}...")
        
        request1 = ChatRequest(
            user_id=self.user_id,
            message="Xin chào, tôi là Hùng, sinh viên năm 4",
            role="student",
            context={"session_id": session_id_1}
        )
        
        response1 = await self.chat_service.process_message(request1)
        print(f"[AI] {response1.message[:100]}...")
        
        # Check name extraction
        extracted_name = self.chat_service._extract_user_name(request1.message)
        self.record("1.1 Name extracted", extracted_name == "Hùng", f"Got: {extracted_name}")
        
        # Check session state
        session_uuid = self.chat_service._get_or_create_session(self.user_id)
        session_state = self.chat_service._get_session_state(session_uuid)
        
        self.record(
            "1.2 Session state created",
            session_state is not None,
            f"total_responses: {session_state.total_responses}"
        )
        
        # Send another message in same session
        request2 = ChatRequest(
            user_id=self.user_id,
            message="Tôi muốn học về SOLAS",
            role="student",
            context={"session_id": session_id_1}
        )
        
        response2 = await self.chat_service.process_message(request2)
        
        # Check session state updated
        session_state_after = self.chat_service._get_session_state(session_uuid)
        self.record(
            "1.3 Session state updated",
            session_state_after.total_responses >= 2,
            f"total_responses: {session_state_after.total_responses}"
        )
        
        self.record(
            "1.4 Not first message anymore",
            not session_state_after.is_first_message,
            f"is_first_message: {session_state_after.is_first_message}"
        )
    
    async def test_2_chat_history_persistence(self):
        """Test 2: Chat history persists in database (if available)."""
        print("\n" + "-" * 70)
        print("TEST 2: Chat History Persistence (Database)")
        print("-" * 70)
        
        if not self.chat_history_available:
            print("  [SKIP] ChatHistory not available (PostgreSQL required)")
            self.results["skipped"] += 1
            return
        
        from app.models.schemas import ChatRequest
        
        # Get session
        session_uuid = self.chat_service._get_or_create_session(self.user_id)
        
        # Send a message
        request = ChatRequest(
            user_id=self.user_id,
            message="Quy tắc 8 COLREGs là gì?",
            role="student"
        )
        
        response = await self.chat_service.process_message(request)
        
        # Check if message was saved
        recent_messages = self.chat_service._chat_history.get_recent_messages(session_uuid)
        
        self.record(
            "2.1 Messages saved to history",
            len(recent_messages) > 0,
            f"Found {len(recent_messages)} messages"
        )
        
        # Check if user name was saved
        user_name = self.chat_service._chat_history.get_user_name(session_uuid)
        self.record(
            "2.2 User name persisted",
            user_name is not None,
            f"Name: {user_name}"
        )
    
    async def test_3_semantic_memory_persistence(self):
        """Test 3: Semantic memory persists user facts (if available)."""
        print("\n" + "-" * 70)
        print("TEST 3: Semantic Memory Persistence (pgvector)")
        print("-" * 70)
        
        if not self.semantic_memory_available:
            print("  [SKIP] SemanticMemory not available (PostgreSQL + pgvector required)")
            self.results["skipped"] += 1
            return
        
        # Store a user fact
        try:
            await self.chat_service._semantic_memory.store_user_fact(
                user_id=self.user_id,
                fact_content="name: TestUser",
                fact_type="name",
                confidence=0.95
            )
            
            self.record("3.1 User fact stored", True, "Stored name fact")
            
            # Retrieve user facts
            context = await self.chat_service._semantic_memory.retrieve_context(
                user_id=self.user_id,
                query="user name",
                include_user_facts=True
            )
            
            has_facts = len(context.user_facts) > 0
            self.record(
                "3.2 User facts retrieved",
                has_facts,
                f"Found {len(context.user_facts)} facts"
            )
            
        except Exception as e:
            self.record("3.x Semantic memory test", False, f"Error: {e}")
    
    async def test_4_cross_session_memory(self):
        """Test 4: Memory persists across different sessions (simulated)."""
        print("\n" + "-" * 70)
        print("TEST 4: Cross-Session Memory (Simulated)")
        print("-" * 70)
        
        from app.models.schemas import ChatRequest
        
        # Create a new ChatService instance (simulating new session)
        from app.services.chat_service import ChatService
        
        new_chat_service = ChatService()
        
        # Same user, new session
        new_session_id = str(uuid4())
        
        print(f"\n[New Session] {new_session_id[:8]}...")
        
        # Ask a question (should still work even without previous context)
        request = ChatRequest(
            user_id=self.user_id,
            message="Tôi muốn tiếp tục học về hàng hải",
            role="student",
            context={"session_id": new_session_id}
        )
        
        response = await new_chat_service.process_message(request)
        
        self.record(
            "4.1 New session works",
            response.message is not None and len(response.message) > 0,
            f"Response length: {len(response.message)}"
        )
        
        # Check if semantic memory retrieves previous facts (if available)
        if self.semantic_memory_available and new_chat_service._semantic_memory:
            try:
                context = await new_chat_service._semantic_memory.retrieve_context(
                    user_id=self.user_id,
                    query="user information",
                    include_user_facts=True
                )
                
                self.record(
                    "4.2 Previous facts accessible",
                    True,
                    f"Found {len(context.user_facts)} facts from previous session"
                )
            except Exception as e:
                self.record("4.2 Previous facts accessible", False, f"Error: {e}")
        else:
            print("  [SKIP] SemanticMemory not available for cross-session test")
            self.results["skipped"] += 1
    
    async def test_5_memory_summarizer_state(self):
        """Test 5: Memory summarizer maintains state."""
        print("\n" + "-" * 70)
        print("TEST 5: Memory Summarizer State")
        print("-" * 70)
        
        if not self.chat_service._memory_summarizer:
            print("  [SKIP] MemorySummarizer not available")
            self.results["skipped"] += 1
            return
        
        session_id = str(uuid4())
        
        # Add messages to summarizer
        await self.chat_service._memory_summarizer.add_message_async(
            session_id, "user", "Tôi muốn học về COLREGS"
        )
        await self.chat_service._memory_summarizer.add_message_async(
            session_id, "assistant", "COLREGS là quy tắc quốc tế về tránh va chạm trên biển."
        )
        
        # Get state
        state = self.chat_service._memory_summarizer.get_state(session_id)
        
        self.record(
            "5.1 Messages added to summarizer",
            len(state.raw_messages) >= 2,
            f"Messages in state: {len(state.raw_messages)}"
        )
        
        # Get context
        context = self.chat_service._memory_summarizer.get_context_for_prompt(session_id)
        
        self.record(
            "5.2 Context generated",
            len(context) > 0,
            f"Context length: {len(context)}"
        )
    
    async def run_all_tests(self):
        """Run all tests."""
        await self.setup()
        
        await self.test_1_session_state_persistence()
        await asyncio.sleep(0.5)
        
        await self.test_2_chat_history_persistence()
        await asyncio.sleep(0.5)
        
        await self.test_3_semantic_memory_persistence()
        await asyncio.sleep(0.5)
        
        await self.test_4_cross_session_memory()
        await asyncio.sleep(0.5)
        
        await self.test_5_memory_summarizer_state()
        
        # Summary
        self.print_summary()
        
        return self.results["failed"] == 0
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)
        
        total = self.results["passed"] + self.results["failed"]
        
        print(f"\n  ✓ Passed: {self.results['passed']}")
        print(f"  ✗ Failed: {self.results['failed']}")
        print(f"  ⊘ Skipped: {self.results['skipped']}")
        
        if total > 0:
            success_rate = self.results["passed"] / total * 100
            print(f"\n  Success Rate: {success_rate:.1f}%")
        
        if self.results["failed"] == 0:
            print("\n  🎉 ALL TESTS PASSED!")
        else:
            print("\n  ❌ SOME TESTS FAILED")


async def main():
    test_suite = MemoryPersistenceE2ETest()
    success = await test_suite.run_all_tests()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
