"""
Streamlit Test UI for Maritime AI Tutor.

Simple chat interface for testing the API.

Run with: streamlit run streamlit_app.py
"""

import os
import sys
from uuid import uuid4

import streamlit as st

# Add app to path for direct imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# USER ID PERSISTENCE - Giữ user_id qua F5 refresh
# ============================================================================
# Sử dụng query parameter để persist user_id
# Khi tích hợp LMS, sẽ thay bằng JWT token từ LMS

def get_persistent_user_id():
    """
    Get or create persistent user_id.
    
    Strategy:
    1. Check query params for existing user_id
    2. If not found, generate new one and redirect with query param
    
    Khi tích hợp LMS: Thay bằng user_id từ JWT token
    """
    query_params = st.query_params
    
    if "uid" in query_params:
        return query_params["uid"]
    
    # Generate new user_id and set in query params
    new_user_id = str(uuid4())
    st.query_params["uid"] = new_user_id
    return new_user_id

# Page config
st.set_page_config(
    page_title="Maritime AI Tutor",
    page_icon="🚢",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
.chat-message {
    padding: 1rem;
    border-radius: 0.5rem;
    margin-bottom: 1rem;
}
.user-message {
    background-color: #e3f2fd;
}
.assistant-message {
    background-color: #f5f5f5;
}
.agent-badge {
    font-size: 0.8rem;
    padding: 0.2rem 0.5rem;
    border-radius: 0.3rem;
    margin-left: 0.5rem;
}
.chat-agent { background-color: #4caf50; color: white; }
.rag-agent { background-color: #2196f3; color: white; }
.tutor-agent { background-color: #ff9800; color: white; }
</style>
""", unsafe_allow_html=True)

# Title
st.title("🚢 Maritime AI Tutor")
st.markdown("*Hệ thống AI hỗ trợ đào tạo hàng hải*")

# Sidebar
with st.sidebar:
    st.header("⚙️ Cài đặt")
    
    # User ID - Persistent qua F5 refresh
    if "user_id" not in st.session_state:
        st.session_state.user_id = get_persistent_user_id()
    
    # Hiển thị user_id (có thể copy để test)
    st.text_input(
        "User ID (persistent)", 
        value=st.session_state.user_id, 
        disabled=True,
        help="ID này được giữ qua F5 refresh. Khi tích hợp LMS sẽ dùng tài khoản thật."
    )
    
    # Option để tạo user mới (cho testing)
    if st.button("🔄 Tạo User mới"):
        new_id = str(uuid4())
        st.session_state.user_id = new_id
        st.session_state.messages = []
        st.query_params["uid"] = new_id
        st.rerun()
    
    # API settings
    api_url = st.text_input(
        "API URL", 
        value="http://localhost:8000",
        help="URL của Maritime AI Service"
    )
    
    api_key = st.text_input(
        "API Key",
        value="test-api-key-123",
        type="password",
        help="API Key để xác thực"
    )
    
    st.divider()
    
    st.header("📚 Hướng dẫn")
    st.markdown("""
    **Các loại câu hỏi:**
    
    🔵 **Knowledge (RAG)**
    - "SOLAS là gì?"
    - "Giải thích COLREGs Rule 5"
    - "Quy định về an toàn cháy nổ"
    
    🟠 **Teaching (Tutor)**
    - "Dạy tôi về SOLAS"
    - "Giúp tôi học về navigation"
    - "Giải thích về fire safety"
    
    🟢 **General (Chat)**
    - "Xin chào"
    - "Bạn có thể giúp gì?"
    """)
    
    st.divider()
    
    if st.button("🗑️ Xóa lịch sử chat (UI only)"):
        st.session_state.messages = []
        st.rerun()
    
    st.info("💡 **Tip:** User ID được lưu trong URL. F5 sẽ giữ nguyên user!")

# Initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant" and "agent_type" in msg:
            agent_type = msg["agent_type"]
            badge_class = f"{agent_type.lower()}-agent"
            st.markdown(
                f'<span class="agent-badge {badge_class}">{agent_type}</span>',
                unsafe_allow_html=True
            )


# Chat input
if prompt := st.chat_input("Nhập câu hỏi của bạn..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Process with API or direct service
    with st.chat_message("assistant"):
        with st.spinner("Đang xử lý..."):
            try:
                # Try API first
                import httpx
                
                response = httpx.post(
                    f"{api_url}/api/v1/chat/completion",
                    json={
                        "user_id": st.session_state.user_id,
                        "message": prompt
                    },
                    headers={
                        "X-API-Key": api_key,
                        "Content-Type": "application/json"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    assistant_message = data["message"]
                    agent_type = data.get("agent_type", "chat")
                    
                    # Show sources if available
                    if data.get("sources"):
                        assistant_message += "\n\n**Nguồn tham khảo:**\n"
                        for source in data["sources"]:
                            assistant_message += f"- {source['title']}\n"
                    
                else:
                    assistant_message = f"Lỗi API: {response.status_code} - {response.text}"
                    agent_type = "error"
                    
            except httpx.ConnectError:
                # Fallback to direct service if API not available
                st.warning("API không khả dụng. Sử dụng service trực tiếp...")
                
                try:
                    import asyncio
                    from app.services.chat_service import get_chat_service
                    from app.models.schemas import ChatRequest
                    from uuid import UUID
                    
                    chat_service = get_chat_service()
                    request = ChatRequest(
                        user_id=UUID(st.session_state.user_id),
                        message=prompt
                    )
                    
                    # Run async function
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        chat_service.process_message(request)
                    )
                    loop.close()
                    
                    assistant_message = result.message
                    agent_type = result.agent_type.value
                    
                except Exception as e:
                    assistant_message = f"Lỗi: {str(e)}"
                    agent_type = "error"
                    
            except Exception as e:
                assistant_message = f"Lỗi: {str(e)}"
                agent_type = "error"
        
        st.markdown(assistant_message)
        
        # Show agent badge
        if agent_type != "error":
            badge_class = f"{agent_type.lower()}-agent"
            st.markdown(
                f'<span class="agent-badge {badge_class}">{agent_type.upper()}</span>',
                unsafe_allow_html=True
            )
    
    # Save assistant message
    st.session_state.messages.append({
        "role": "assistant",
        "content": assistant_message,
        "agent_type": agent_type
    })

# Footer
st.divider()
st.markdown("""
<div style="text-align: center; color: #888;">
    Maritime AI Tutor v1.0 | 🚢 Hệ thống AI hỗ trợ đào tạo hàng hải
</div>
""", unsafe_allow_html=True)
