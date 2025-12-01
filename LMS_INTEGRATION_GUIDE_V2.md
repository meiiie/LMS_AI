# 🚢 HƯỚNG DẪN TÍCH HỢP MARITIME AI CHATBOT V2
## Dành cho Team LMS Hàng Hải

**Ngày cập nhật:** 28/11/2025  
**Phiên bản API:** 0.2.0 (Memory & Personalization)  
**Trạng thái:** ✅ SẴN SÀNG TÍCH HỢP

---

## 🆕 TÍNH NĂNG MỚI - CHỈ THỊ SỐ 04

### Memory (Trí nhớ)
- AI nhớ lịch sử hội thoại của từng user
- Sử dụng 10 tin nhắn gần nhất làm context
- Tự động nhận diện và nhớ tên user

### Personalization (Cá nhân hóa)
- Learning profile cho từng user
- Theo dõi điểm mạnh/yếu
- Đếm số tin nhắn và sessions

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

### 1. Chat Completion (với Memory)
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
| `user_id` | string | **QUAN TRỌNG:** ID user từ LMS - dùng để lưu lịch sử chat và learning profile |
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
    "answer": "**Quy tắc 5 COLREGs - Cảnh giới**\n\nTheo Điều 5...",
    "sources": [
      {
        "title": "COLREGs Rule 5 - Look-out",
        "content": "Every vessel shall at all times maintain..."
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
    "agent_type": "chat"
  }
}
```

---

## 🧠 MEMORY BEHAVIOR

### Cách Memory hoạt động

1. **Lần đầu chat:** AI tạo session mới cho user
2. **Các lần sau:** AI tự động load 10 tin nhắn gần nhất
3. **Nhận diện tên:** Nếu user nói "Tôi là Hùng", AI sẽ nhớ và gọi tên

### Ví dụ Memory

**Request 1:**
```json
{"user_id": "student_001", "message": "Xin chào, tôi là Hùng", "role": "student"}
```
**Response 1:** "Chào Hùng! Rất vui được gặp bạn..."

**Request 2:**
```json
{"user_id": "student_001", "message": "Tên tôi là gì?", "role": "student"}
```
**Response 2:** "Tên bạn là **Hùng** mà, bạn tự giới thiệu từ lần đầu chat rồi đấy!"

### Lưu ý quan trọng

⚠️ **`user_id` phải nhất quán** - Nếu gửi `user_id` khác nhau, AI sẽ coi là user khác và không có memory.

---

## 🎭 ROLE-BASED BEHAVIOR

### Student Role (`role: "student"`)
- AI đóng vai **Gia sư thân thiện**
- Giải thích từng bước, dễ hiểu
- Đặt câu hỏi ngược để kích thích tư duy
- Khuyến khích học tập

### Teacher/Admin Role (`role: "teacher"` hoặc `role: "admin"`)
- AI đóng vai **Trợ lý chuyên nghiệp**
- Trả lời trực tiếp, ngắn gọn
- Trích dẫn nguồn chính xác
- Hỗ trợ soạn bài giảng

---

## 💻 CODE EXAMPLES

### JavaScript/TypeScript (Angular)
```typescript
// chat.service.ts
interface ChatRequest {
  user_id: string;
  message: string;
  role: 'student' | 'teacher' | 'admin';
  session_id?: string;
  context?: {
    course_id?: string;
    lesson_id?: string;
  };
}

@Injectable({ providedIn: 'root' })
export class ChatService {
  private apiUrl = 'https://maritime-ai-chatbot.onrender.com';
  private apiKey = 'secret_key_cho_team_lms';

  constructor(private http: HttpClient) {}

  sendMessage(request: ChatRequest): Observable<ChatResponse> {
    const headers = new HttpHeaders({
      'Content-Type': 'application/json',
      'X-API-Key': this.apiKey
    });

    return this.http.post<ChatResponse>(
      `${this.apiUrl}/api/v1/chat`,
      request,
      { headers }
    ).pipe(
      timeout(90000),  // 90 giây timeout cho cold start
      retry(2),
      catchError(this.handleError)
    );
  }
}
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
            "user_id": user_id,  # Quan trọng: giữ nhất quán để có memory
            "message": message,
            "role": role
        },
        timeout=90
    )
    response.raise_for_status()
    return response.json()

# Sử dụng
result = send_chat_message(
    user_id="student_123",  # Luôn dùng cùng user_id cho cùng user
    message="Quy tắc 5 COLREGs là gì?",
    role="student"
)
print(result["data"]["answer"])
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
      "field": "body.role",
      "message": "Input should be 'student', 'teacher' or 'admin'",
      "code": "enum"
    }
  ]
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

---

## ⏱️ PERFORMANCE NOTES

| Trạng thái Server | Thời gian Response |
|-------------------|-------------------|
| Cold Start (sau 15 phút idle) | 20-30 giây |
| Warm (đang hoạt động) | 2-5 giây |
| Health Check | < 1 giây |

**Recommendations:**
1. Set timeout ≥ 90 giây
2. Implement retry logic (2-3 lần)
3. Hiển thị loading indicator cho user

---

## ✅ INTEGRATION CHECKLIST

- [ ] Lưu API Key vào environment variable
- [ ] Implement error handling cho tất cả status codes
- [ ] Set request timeout ≥ 90 giây
- [ ] **Map user ID từ LMS sang `user_id` field (QUAN TRỌNG cho memory)**
- [ ] Map user role từ LMS sang `role` field (lowercase)
- [ ] Render Markdown trong `answer` field
- [ ] Hiển thị `sources` nếu có
- [ ] Hiển thị `suggested_questions` cho user

---

## 📞 SUPPORT

**GitHub Repository:** https://github.com/meiiie/LMS_AI

---

## 📝 CHANGELOG

### v0.2.0 (28/11/2025) - CHỈ THỊ SỐ 04
- ✅ Memory: AI nhớ lịch sử hội thoại
- ✅ Personalization: Learning profile cho từng user
- ✅ BackgroundTasks: Lưu không blocking response

### v0.1.0 (27/11/2025)
- ✅ Initial release
- ✅ Chat completion endpoint
- ✅ Role-based prompting

---

**Happy Coding! 🚀**
