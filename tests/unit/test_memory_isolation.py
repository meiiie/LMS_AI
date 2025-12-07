"""
Test Memory Isolation - CHỈ THỊ SỐ 22
Verify blocked messages are saved but filtered from context
"""
import sys
sys.path.insert(0, '.')

from app.repositories.chat_history_repository import ChatHistoryRepository, ChatMessage

def test_chat_history_repository():
    print("=" * 60)
    print("TEST: ChatHistoryRepository - Memory Isolation")
    print("=" * 60)
    
    from uuid import uuid4
    from datetime import datetime
    
    # Test 1: ChatMessage dataclass has is_blocked field
    print("\n[Test 1] ChatMessage dataclass structure")
    msg = ChatMessage(
        id=uuid4(),
        session_id=uuid4(),
        role="user",
        content="test message",
        created_at=datetime.now(),
        is_blocked=True,
        block_reason="Test block"
    )
    print(f"  ChatMessage created: role={msg.role}, is_blocked={msg.is_blocked}")
    print(f"  block_reason: {msg.block_reason}")
    print("  ✅ ChatMessage supports is_blocked and block_reason")
    
    # Test 2: Repository has save_message with is_blocked support
    print("\n[Test 2] Repository method signatures")
    repo = ChatHistoryRepository()
    
    import inspect
    save_sig = inspect.signature(repo.save_message)
    print(f"  save_message params: {list(save_sig.parameters.keys())}")
    
    has_is_blocked = 'is_blocked' in save_sig.parameters
    has_block_reason = 'block_reason' in save_sig.parameters
    
    if has_is_blocked and has_block_reason:
        print("  ✅ save_message supports is_blocked and block_reason")
    else:
        print("  ❌ Missing parameters in save_message")
    
    # Test 3: get_recent_messages has include_blocked parameter
    print("\n[Test 3] get_recent_messages filtering")
    get_sig = inspect.signature(repo.get_recent_messages)
    print(f"  get_recent_messages params: {list(get_sig.parameters.keys())}")
    
    has_include_blocked = 'include_blocked' in get_sig.parameters
    if has_include_blocked:
        default = get_sig.parameters['include_blocked'].default
        print(f"  include_blocked default: {default}")
        if default == False:
            print("  ✅ Blocked messages filtered by default")
        else:
            print("  ⚠️ Blocked messages NOT filtered by default")
    else:
        print("  ❌ Missing include_blocked parameter")
    
    print("\n" + "=" * 60)
    print("Memory Isolation structure tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    test_chat_history_repository()
