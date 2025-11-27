# 🚢 HƯỚNG DẪN TÍCH HỢP MARITIME AI CHATBOT
## Dành cho Team LMS Hàng Hải

**Ngày cập nhật:** 28/11/2025  
**Phiên bản API:** 0.1.0  
**Trạng thái:** ✅ SẴN SÀNG TÍCH HỢP

---

## 📋 THÔNG TIN NHANH

| Thông tin | Giá trị |
|-----------|---------|
| **Base URL** | `https://maritime-ai-chatbot.onrender.com` |
| **API Docs** | https://maritime-ai-chatbot.onrender.com/docs |
| **Health Check** | https://maritime-ai-chatbot.onrender.com/health |
| **API Key** | `secret_key_cho_team_lms` |
| **Header Auth** | `X-API-Key` |

---

## 🔌 ENDPOINTS

### 1. Chat Completion
**URL:** `POST /api/v1/chat`

**Headers:**
```
Content-Type: application/json
X-API-Key: secret_key_cho_team_lms
```

**Request Body:**
```json
{
  "user_id": "student_12345",
  "message": "Quy tắc 5 COLREGs là gì?",
  "role": "student",
  "session_id": "session_abc123",
  "context": {
    "course_id": "COLREGs_101",
    "lesson_id": "lesson_5"
  }
}
```

**Các trường bắt buộc:**
| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `user_id` | string | ID user từ LMS (để lưu lịch sử chat) |
| `message` | string | Câu hỏi của người dùng (1-10000 ký tự) |
| `role` | string | `student` \| `teacher` \| `admin` |

**Các trường tùy chọn:**
| Trường | Kiểu | Mô tả |
|--------|------|-------|
| `session_id` | string | ID phiên học (nếu có) |
| `context` | object | Dữ liệu ngữ cảnh thêm |

**Response thành công (200):**
```json
{
  "status": "success",
  "data": {
    "answer": "**Quy tắc 5 COLREGs - Cảnh giới**\n\nTheo Điều 5 của COLREGs...",
    "sources": [
      {
        "title": "COLREGs Rule 5 - Look-out",
        "content": "Every vessel shall at all times maintain a proper look-out..."
      }
    ],
    "suggested_questions": [
      "Tàu nào phải nhường đường trong tình huống này?",
      "Khi nào áp dụng quy tắc này?",
      "Có ngoại lệ nào cho quy tắc này không?"
    ]
  },
  "metadata": {
    "processing_time": 2.35,
    "model": "maritime-rag-v1",
    "agent_type": "tutor"
  }
}
```

### 2. Health Check
**URL:** `GET /health`

**Response:**
```json
{
  "status": "ok",
  "database": "connected"
}
```

---

## 💻 CODE EXAMPLES

### JavaScript/TypeScript (Fetch)
```javascript
const API_URL = 'https://maritime-ai-chatbot.onrender.com';
const API_KEY = 'secret_key_cho_team_lms';

async function sendChatMessage(userId, message, role = 'student') {
  const response = await fetch(`${API_URL}/api/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY
    },
    body: JSON.stringify({
      user_id: userId,
      message: message,
      role: role
    })
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
}

// Sử dụng
const result = await sendChatMessage(
  'student_123',
  'Quy tắc 5 COLREGs là gì?',
  'student'
);
console.log(result.data.answer);
```

### JavaScript/TypeScript (Axios)
```javascript
import axios from 'axios';

const apiClient = axios.create({
  baseURL: 'https://maritime-ai-chatbot.onrender.com',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'secret_key_cho_team_lms'
  }
});

async function chat(userId, message, role = 'student') {
  const { data } = await apiClient.post('/api/v1/chat', {
    user_id: userId,
    message: message,
    role: role
  });
  return data;
}

// Sử dụng
const response = await chat('student_123', 'Quy tắc 5 COLREGs là gì?');
console.log(response.data.answer);
```

### Python (requests)
```python
import requests

API_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"

def send_chat_message(user_id: str, message: str, role: str = "student"):
    response = requests.post(
        f"{API_URL}/api/v1/chat",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY
        },
        json={
            "user_id": user_id,
            "message": message,
            "role": role
        }
    )
    response.raise_for_status()
    return response.json()

# Sử dụng
result = send_chat_message(
    user_id="student_123",
    message="Quy tắc 5 COLREGs là gì?",
    role="student"
)
print(result["data"]["answer"])
```

### cURL
```bash
curl -X POST "https://maritime-ai-chatbot.onrender.com/api/v1/chat" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret_key_cho_team_lms" \
  -d '{
    "user_id": "student_123",
    "message": "Quy tắc 5 COLREGs là gì?",
    "role": "student"
  }'
```

---

## 🎭 ROLE-BASED BEHAVIOR

### Student Role
Khi `role: "student"`, AI sẽ:
- Đóng vai gia sư thân thiện
- Giải thích từng bước, dễ hiểu
- Đặt câu hỏi ngược để kích thích tư duy
- Đưa ví dụ thực tế
- Khuyến khích học tập

**Ví dụ response:**
```
Chào em! Câu hỏi hay đấy! 👍

Quy tắc 5 COLREGs nói về **Cảnh giới** (Look-out). 
Hãy tưởng tượng em đang lái xe - em luôn phải quan sát 
xung quanh đúng không? Trên biển cũng vậy!

**Nội dung chính:**
- Mọi tàu phải duy trì cảnh giới liên tục
- Sử dụng mọi phương tiện có sẵn (mắt, tai, radar...)
- Mục đích: đánh giá đầy đủ tình huống và nguy cơ va chạm

Em có thể cho thầy biết tại sao cảnh giới lại quan trọng không?
```

### Teacher/Admin Role
Khi `role: "teacher"` hoặc `role: "admin"`, AI sẽ:
- Đóng vai trợ lý chuyên nghiệp
- Trả lời trực tiếp, đầy đủ
- Trích dẫn nguồn chính xác
- Hỗ trợ soạn bài giảng

**Ví dụ response:**
```
**Quy tắc 5 COLREGs - Cảnh giới (Look-out)**

Theo Điều 5 của Công ước COLREGs 1972:

"Mọi tàu thuyền phải luôn luôn duy trì việc cảnh giới thích hợp 
bằng mắt nhìn và tai nghe cũng như bằng mọi phương tiện sẵn có 
thích ứng với hoàn cảnh và điều kiện hiện tại để đánh giá đầy đủ 
tình huống và nguy cơ va chạm."

**Nguồn:** COLREGs 1972, Rule 5
```

---

## ⚠️ ERROR HANDLING

### Validation Error (400)
```json
{
  "error": "validation_error",
  "message": "Request validation failed",
  "details": [
    {
      "field": "message",
      "message": "Message cannot be empty or whitespace only",
      "code": "value_error"
    }
  ]
}
```

### Unauthorized (401)
```json
{
  "detail": "Invalid API key"
}
```

### Rate Limited (429)
```json
{
  "error": "rate_limited",
  "message": "Rate limit exceeded",
  "retry_after": 60
}
```

### Internal Error (500)
```json
{
  "error": "internal_error",
  "message": "An unexpected error occurred"
}
```

---

## 📊 RATE LIMITS

| Limit | Value |
|-------|-------|
| Requests per minute | 100 |
| Max message length | 10,000 characters |
| Response timeout | 60 seconds |

---

## ⏱️ PERFORMANCE NOTES

### Cold Start
- API sử dụng Render free tier
- Sau 15 phút không hoạt động, server sẽ "ngủ"
- Request đầu tiên sau khi "ngủ" mất ~20-30 giây
- Các request tiếp theo nhanh hơn (~2-5 giây)

### Recommendations
1. Implement loading indicator cho user
2. Set timeout ít nhất 60 giây cho request đầu tiên
3. Có thể gọi `/health` trước để "đánh thức" server

---

## 🔧 INTEGRATION CHECKLIST

- [ ] Lưu API Key vào environment variable (không hardcode)
- [ ] Implement error handling cho tất cả status codes
- [ ] Thêm loading indicator khi chờ response
- [ ] Set request timeout ≥ 60 giây
- [ ] Map user ID từ LMS sang `user_id` field
- [ ] Map user role từ LMS sang `role` field
- [ ] Render Markdown trong `answer` field
- [ ] Hiển thị `sources` nếu có
- [ ] Hiển thị `suggested_questions` cho user

---

## 📞 SUPPORT

**GitHub Repository:** https://github.com/meiiie/LMS_AI

**Liên hệ kỹ thuật:**
- Tạo issue trên GitHub
- Email: [contact email]

---

## 📝 CHANGELOG

### v0.1.0 (28/11/2025)
- ✅ Initial release
- ✅ Chat completion endpoint
- ✅ Health check endpoint
- ✅ Role-based prompting (student/teacher/admin)
- ✅ Swagger documentation
- ✅ Rate limiting
- ✅ Error handling

---

**Happy Coding! 🚀**
