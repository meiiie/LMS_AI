# 📊 BÁO CÁO TIẾN ĐỘ - TUẦN 2: THE MEMORY (MEMORY LITE)

**Ngày:** 27/11/2025  
**Trạng thái:** ✅ HOÀN THÀNH

---

## 🎯 MỤC TIÊU TUẦN 2

Theo chỉ thị của Cố vấn Kiến trúc:
1. ✅ Memory Lite: Code module lưu/đọc lịch sử chat từ Postgres
2. ✅ Context Injection: Đưa tên user và lịch sử chat vào Prompt
3. ✅ Kết quả: F5 trình duyệt, Chatbot vẫn nhớ user

---

## 🔧 CÔNG VIỆC ĐÃ THỰC HIỆN

### 1. Database Models (SQLAlchemy)
- **File:** `app/models/database.py`
- **Thêm mới:**
  - `ChatSessionModel`: Lưu session của user
  - `ChatMessageModel`: Lưu từng tin nhắn với role (user/assistant)
  - Index trên `session_id` và `created_at` để query nhanh

### 2. Chat History Repository
- **File:** `app/repositories/chat_history_repository.py`
- **Chức năng:**
  - `get_or_create_session()`: Tạo/lấy session cho user
  - `save_message()`: Lưu tin nhắn vào database
  - `get_recent_messages()`: Sliding Window - lấy 10 tin nhắn gần nhất
  - `update_user_name()`: Lưu tên user khi extract được
  - `format_history_for_prompt()`: Format lịch sử cho LLM prompt

### 3. Chat Service Integration
- **File:** `app/services/chat_service.py`
- **Cập nhật:**
  - Tích hợp `ChatHistoryRepository`
  - Lưu tin nhắn user trước khi xử lý
  - Lưu tin nhắn AI sau khi trả lời
  - Extract tên user từ tin nhắn (regex patterns)
  - Truyền conversation history vào RAG và Chat Agent

### 4. RAG Agent với Conversation History
- **File:** `app/engine/tools/rag_tool.py`
- **Cập nhật:**
  - Thêm parameter `conversation_history`
  - Prompt template mới với LỊCH SỬ HỘI THOẠI section
  - AI có thể hiểu câu hỏi nối tiếp (follow-up questions)

---

## 📈 KẾT QUẢ TEST

### Kịch bản test (theo yêu cầu của chuyên gia):

```
User: "Chào Captain, mình tên là Huy."
AI: "Chào Huy! Rất vui được gặp bạn..."
✅ Tên được extract và lưu vào database

User: "Quy tắc 5 COLREGs là gì?"
AI: "Chào Huy! Quy tắc 5 COLREGs (Rule 5 - Look-out)..."
✅ AI nhớ tên và trả lời chính xác

User: "Nếu không làm thế thì sao?" (Câu hỏi thiếu chủ ngữ)
AI: "Nếu không tuân thủ Quy tắc 5 COLREGs (Look-out)..."
✅ AI hiểu ngữ cảnh từ lịch sử hội thoại

--- F5 REFRESH (New service instance) ---

User: "Hôm nay biển động quá."
AI: "Chào Huy! Ừa, biển động là chuyện thường..."
✅ AI VẪN NHỚ TÊN HUY SAU KHI F5!
```

---

## 📊 THỐNG KÊ

| Metric | Giá trị |
|--------|---------|
| Database Tables | 2 (chat_sessions, chat_messages) |
| Sliding Window Size | 10 messages |
| Name Extraction Patterns | 4 patterns (Việt + Anh) |
| Persistence | PostgreSQL |

---

## 🗄️ DATABASE SCHEMA

```sql
-- Chat Sessions
CREATE TABLE chat_sessions (
    session_id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    user_name VARCHAR(255),
    created_at TIMESTAMP
);

-- Chat Messages
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY,
    session_id UUID REFERENCES chat_sessions,
    role VARCHAR(50) NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP
);

CREATE INDEX idx_messages_session ON chat_messages(session_id, created_at);
```

---

## 🚀 BƯỚC TIẾP THEO (TUẦN 3)

Theo chỉ thị của Cố vấn:
1. **UI/UX:** Tinh chỉnh Streamlit CSS cho đẹp
2. **Deploy:** Đẩy lên Cloud server để demo từ xa

---

## ✅ CHECKLIST TUẦN 2

- [x] Tạo bảng chat_sessions trong PostgreSQL
- [x] Tạo bảng chat_messages trong PostgreSQL
- [x] Implement Sliding Window (10 tin nhắn gần nhất)
- [x] Lưu tin nhắn user vào database
- [x] Lưu tin nhắn AI vào database
- [x] Extract tên user từ tin nhắn
- [x] Đưa lịch sử chat vào Prompt
- [x] AI nhớ tên user sau F5
- [x] AI hiểu câu hỏi nối tiếp (follow-up)

**Trạng thái: TUẦN 2 HOÀN THÀNH ✅**

---

## 📝 FILES ĐÃ THAY ĐỔI

1. `app/models/database.py` - Thêm ChatSessionModel, ChatMessageModel
2. `app/repositories/chat_history_repository.py` - NEW: Memory Lite repository
3. `app/services/chat_service.py` - Tích hợp Memory Lite
4. `app/engine/tools/rag_tool.py` - Thêm conversation_history parameter
