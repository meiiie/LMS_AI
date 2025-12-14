# LMS Integration Guide

> **For:** LMS Backend & Frontend Teams  
> **Version:** 1.0.0  
> **Last Updated:** 2025-12-14

---

## Quick Start

### 1. Get API Key

Contact the AI Team to receive your production API key:
- **Format:** `sk_live_xxxxxxxx...`
- **Environment:** Store in `.env` as `AI_SERVICE_API_KEY`

### 2. Configure Base URL

| Environment | URL |
|-------------|-----|
| Development | `http://localhost:8000/api/v1` |
| Staging | `https://staging-ai.maritime.edu/api/v1` |
| Production | `https://ai.maritime.edu/api/v1` |

### 3. Set Required Headers

Every request must include:

```http
X-API-Key: {your_api_key}
X-User-ID: {student_id_from_lms}
X-Role: student|teacher|admin
```

---

## Backend Integration (Spring Boot)

### Configuration

```yaml
# application.yml
ai-service:
  base-url: ${AI_SERVICE_URL:http://localhost:8000/api/v1}
  api-key: ${AI_SERVICE_API_KEY}
  timeout: 30s
  retry:
    max-attempts: 3
    backoff: 1s
```

### Service Layer

```java
@Service
public class AIChatService {
    
    private final WebClient webClient;
    
    public AIChatService(
        @Value("${ai-service.base-url}") String baseUrl,
        @Value("${ai-service.api-key}") String apiKey
    ) {
        this.webClient = WebClient.builder()
            .baseUrl(baseUrl)
            .defaultHeader("X-API-Key", apiKey)
            .build();
    }
    
    public Mono<ChatResponse> sendMessage(ChatRequest request, User user) {
        return webClient.post()
            .uri("/chat")
            .header("X-User-ID", user.getId())
            .header("X-Role", user.getRole().name().toLowerCase())
            .bodyValue(request)
            .retrieve()
            .bodyToMono(ChatResponse.class);
    }
    
    public Flux<ServerSentEvent<String>> streamMessage(ChatRequest request, User user) {
        return webClient.post()
            .uri("/chat/stream")
            .header("X-User-ID", user.getId())
            .header("X-Role", user.getRole().name().toLowerCase())
            .bodyValue(request)
            .retrieve()
            .bodyToFlux(new ParameterizedTypeReference<ServerSentEvent<String>>() {});
    }
}
```

### DTOs

```java
public record ChatRequest(
    String message,
    @JsonProperty("user_id") String userId,
    String role,
    @JsonProperty("thread_id") String threadId,
    @JsonProperty("user_context") UserContext userContext
) {}

public record UserContext(
    @JsonProperty("display_name") String displayName,
    @JsonProperty("current_module_id") String currentModuleId,
    @JsonProperty("current_course_name") String currentCourseName,
    String language
) {}

public record ChatResponse(
    @JsonProperty("response_id") String responseId,
    String message,
    @JsonProperty("agent_type") String agentType,
    List<Source> sources,
    Map<String, Object> metadata
) {}

public record Source(
    @JsonProperty("node_id") String nodeId,
    String title,
    @JsonProperty("content_snippet") String contentSnippet,
    @JsonProperty("page_number") Integer pageNumber,
    @JsonProperty("document_id") String documentId,
    @JsonProperty("image_url") String imageUrl,
    @JsonProperty("bounding_boxes") List<BoundingBox> boundingBoxes
) {}
```

---

## Frontend Integration (Angular)

### Service

```typescript
// services/ai-chat.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, Subject } from 'rxjs';
import { environment } from '@env/environment';

export interface ChatRequest {
  message: string;
  user_id: string;
  role: 'student' | 'teacher' | 'admin';
  thread_id?: string;
  user_context?: UserContext;
}

export interface UserContext {
  display_name?: string;
  current_module_id?: string;
  current_course_name?: string;
  language?: string;
}

export interface ChatResponse {
  response_id: string;
  message: string;
  agent_type: 'rag' | 'chat' | 'tutor';
  sources: Source[];
  metadata: Record<string, any>;
}

export interface Source {
  node_id: string;
  title: string;
  content_snippet: string;
  page_number?: number;
  document_id?: string;
  image_url?: string;
  bounding_boxes?: BoundingBox[];
}

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

@Injectable({ providedIn: 'root' })
export class AIChatService {
  private baseUrl = environment.aiServiceUrl;
  
  constructor(
    private http: HttpClient,
    private authService: AuthService
  ) {}
  
  private getHeaders(): HttpHeaders {
    const user = this.authService.getCurrentUser();
    return new HttpHeaders({
      'Content-Type': 'application/json',
      'X-API-Key': environment.aiApiKey,
      'X-User-ID': user.id,
      'X-Role': user.role
    });
  }
  
  sendMessage(request: ChatRequest): Observable<ChatResponse> {
    return this.http.post<ChatResponse>(
      `${this.baseUrl}/chat`,
      request,
      { headers: this.getHeaders() }
    );
  }
  
  streamMessage(request: ChatRequest): Observable<StreamEvent> {
    const subject = new Subject<StreamEvent>();
    
    fetch(`${this.baseUrl}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': environment.aiApiKey,
        'X-User-ID': request.user_id,
        'X-Role': request.role
      },
      body: JSON.stringify(request)
    }).then(async response => {
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      
      while (reader) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const text = decoder.decode(value);
        const events = this.parseSSE(text);
        events.forEach(event => subject.next(event));
      }
      
      subject.complete();
    }).catch(error => subject.error(error));
    
    return subject.asObservable();
  }
  
  private parseSSE(text: string): StreamEvent[] {
    // Parse SSE format: "event: type\ndata: {...}\n\n"
    const events: StreamEvent[] = [];
    const lines = text.split('\n\n');
    
    for (const block of lines) {
      if (!block.trim()) continue;
      
      const eventMatch = block.match(/event: (\w+)/);
      const dataMatch = block.match(/data: (.+)/);
      
      if (eventMatch && dataMatch) {
        events.push({
          type: eventMatch[1] as StreamEventType,
          data: JSON.parse(dataMatch[1])
        });
      }
    }
    
    return events;
  }
}

export type StreamEventType = 'thinking' | 'answer' | 'sources' | 'metadata' | 'done';

export interface StreamEvent {
  type: StreamEventType;
  data: any;
}
```

### Component

```typescript
// components/chat/chat.component.ts
@Component({
  selector: 'app-chat',
  templateUrl: './chat.component.html'
})
export class ChatComponent {
  messages: Message[] = [];
  currentMessage = '';
  isLoading = false;
  currentThreadId?: string;
  
  constructor(
    private aiChat: AIChatService,
    private auth: AuthService
  ) {}
  
  async sendMessage() {
    if (!this.currentMessage.trim()) return;
    
    const userMessage = this.currentMessage;
    this.currentMessage = '';
    this.isLoading = true;
    
    // Add user message to UI
    this.messages.push({
      role: 'user',
      content: userMessage
    });
    
    // Prepare request
    const request: ChatRequest = {
      message: userMessage,
      user_id: this.auth.userId,
      role: this.auth.userRole as any,
      thread_id: this.currentThreadId,
      user_context: {
        display_name: this.auth.displayName,
        current_course_name: this.currentCourse?.name
      }
    };
    
    // Stream response
    let aiContent = '';
    const aiMessage: Message = { role: 'assistant', content: '', sources: [] };
    this.messages.push(aiMessage);
    
    this.aiChat.streamMessage(request).subscribe({
      next: (event) => {
        switch (event.type) {
          case 'thinking':
            // Optional: Show thinking indicator
            break;
          case 'answer':
            aiContent += event.data.content;
            aiMessage.content = aiContent;
            break;
          case 'sources':
            aiMessage.sources = event.data.sources;
            break;
          case 'metadata':
            // Save thread_id for continuity
            if (event.data.session_id) {
              this.currentThreadId = event.data.session_id;
            }
            break;
          case 'done':
            this.isLoading = false;
            break;
        }
      },
      error: (err) => {
        console.error('Chat error:', err);
        this.isLoading = false;
      }
    });
  }
}
```

---

## Thread-Based Conversations

The AI service supports conversation threads (like ChatGPT's "New Chat"):

### Creating a New Thread

```typescript
// Don't send thread_id, or send "new"
const request = {
  message: "Hello",
  user_id: "user_123",
  role: "student"
  // thread_id: omitted = new thread
};
```

### Continuing a Thread

```typescript
// Send the thread_id from previous response
const request = {
  message: "Tell me more",
  user_id: "user_123",
  role: "student",
  thread_id: "uuid-from-previous-response"  // Continue conversation
};
```

### Data Persistence

| Data Type | Scope | Storage |
|-----------|-------|---------|
| Chat History | Per Thread | PostgreSQL |
| User Facts | Per User (global) | Vector DB |
| Learning Insights | Per User (global) | Vector DB |

---

## PDF Source Highlighting

When displaying sources, you can highlight the exact text in a PDF viewer:

### Bounding Box Format

```json
{
  "x": 10.5,      // Left position (% of page width)
  "y": 20.3,      // Top position (% of page height)
  "width": 80.0,  // Box width (% of page width)
  "height": 15.2  // Box height (% of page height)
}
```

### Usage with PDF.js

```typescript
function highlightSource(source: Source, pdfViewer: PDFViewer) {
  const page = pdfViewer.getPageView(source.page_number - 1);
  const viewport = page.viewport;
  
  source.bounding_boxes?.forEach(box => {
    const rect = document.createElement('div');
    rect.className = 'highlight-box';
    rect.style.left = `${box.x}%`;
    rect.style.top = `${box.y}%`;
    rect.style.width = `${box.width}%`;
    rect.style.height = `${box.height}%`;
    rect.style.position = 'absolute';
    rect.style.backgroundColor = 'rgba(255, 255, 0, 0.3)';
    
    page.div.appendChild(rect);
  });
}
```

---

## Error Handling

### Backend (Java)

```java
@ControllerAdvice
public class AIServiceExceptionHandler {
    
    @ExceptionHandler(WebClientResponseException.class)
    public ResponseEntity<ErrorResponse> handleAIServiceError(WebClientResponseException ex) {
        if (ex.getStatusCode() == HttpStatus.UNAUTHORIZED) {
            return ResponseEntity.status(503)
                .body(new ErrorResponse("AI_SERVICE_AUTH_ERROR", "AI Service authentication failed"));
        }
        
        if (ex.getStatusCode() == HttpStatus.TOO_MANY_REQUESTS) {
            return ResponseEntity.status(429)
                .body(new ErrorResponse("RATE_LIMITED", "Too many requests to AI service"));
        }
        
        return ResponseEntity.status(503)
            .body(new ErrorResponse("AI_SERVICE_ERROR", "AI Service unavailable"));
    }
}
```

### Frontend (Angular)

```typescript
// interceptors/ai-error.interceptor.ts
@Injectable()
export class AIErrorInterceptor implements HttpInterceptor {
  
  intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    return next.handle(req).pipe(
      catchError((error: HttpErrorResponse) => {
        if (error.url?.includes('api/v1')) {
          // AI Service error
          if (error.status === 429) {
            this.toast.error('Quá nhiều yêu cầu. Vui lòng thử lại sau.');
          } else if (error.status === 503) {
            this.toast.error('Dịch vụ AI đang bảo trì.');
          }
        }
        return throwError(() => error);
      })
    );
  }
}
```

---

## Analytics & Metrics

The AI service returns analytics in the `metadata` field:

```json
{
  "metadata": {
    "session_id": "uuid",
    "user_name": "Nguyễn Văn A",
    "analytics": {
      "topics_accessed": ["colregs", "rule15"],
      "confidence_score": 0.92,
      "document_ids_used": ["colregs_2024"],
      "query_type": "factual"
    }
  }
}
```

### Suggested LMS Usage

| Metric | LMS Feature |
|--------|-------------|
| `topics_accessed` | Learning progress tracking |
| `confidence_score` | Quality indicator in chat UI |
| `document_ids_used` | Link to source documents |
| `query_type` | Student behavior analytics |

---

## Checklist for Go-Live

### Backend Team

- [ ] Configure AI_SERVICE_API_KEY in environment
- [ ] Implement retry logic (3 attempts, 1s backoff)
- [ ] Set timeout to 30s for chat, 60s for streaming
- [ ] Handle rate limiting (429) gracefully
- [ ] Log API calls for debugging

### Frontend Team

- [ ] Implement SSE streaming for real-time responses
- [ ] Display sources with expandable details
- [ ] Handle PDF highlighting with bounding boxes
- [ ] Show loading states during AI processing
- [ ] Implement "New Chat" (clear thread_id)

---

## Support

| Issue | Contact |
|-------|---------|
| API Key | AI Team - ai-team@maritime.edu |
| Integration Help | Backend Lead |
| Bug Reports | GitHub Issues |

---

*Guide created 2025-12-14*
