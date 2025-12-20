# Roadmap

Maritime AI Tutor Service - Future Development Plans

---

## Current Version: 1.0.0

**Release Date:** 2025-12-13  
**SOTA Score:** ~90%

---

## Short-Term (Q1 2025)

### ✅ Complete

| Phase | Feature | Status | Date |
|-------|---------|--------|------|
| 7 | Agentic RAG | ✅ | 2025-12-13 |
| 8 | Multi-Agent System | ✅ | 2025-12-13 |
| 10 | Explicit Memory Control | ✅ | 2025-12-13 |
| 11 | Memory Compression | ✅ | 2025-12-13 |

### 🔄 In Progress

None currently.

### 📋 Planned

| Phase | Feature | Priority | Effort | Dependencies |
|-------|---------|----------|--------|--------------|
| 3 | RAG Accuracy Optimization | HIGH | 3-5 days | HyDE, Neural Reranker ready |
| 9 | Proactive Learning | MEDIUM | 5-7 days | LMS frontend webhook |
| 12 | Scheduled Tasks | LOW | 5-7 days | APScheduler, Push notifications |

---

## Phase 3: RAG Accuracy Optimization (SOTA 2025)

**Goal:** Tăng retrieval accuracy +35-45% với HyDE và Neural Reranking

### Features
- [ ] **HyDE Integration** - Hypothetical Document Embeddings (+20-30% accuracy)
- [ ] **Neural Reranker** - BGE-Reranker-v2-m3 cross-encoder (+15-25% accuracy)
- [ ] Config flags for enable/disable
- [ ] A/B testing framework for accuracy measurement

### Components Ready
| Component | File | Status | Latency Cost |
|-----------|------|--------|--------------|
| HyDE Service | `app/services/hyde_service.py` | ✅ Ready | +2-3s |
| Neural Reranker | `app/services/neural_reranker.py` | ✅ Ready | +0.5-1s |

### Technical Details
- **HyDE**: Generate hypothetical answer → embed → search (Google/MIT research)
- **Neural Reranker**: Cross-encoder reranking with 70% rerank + 30% original scoring
- **Fallback**: Graceful degradation if model unavailable

### Estimated Effort
- Integration: 2-3 days
- Testing & Tuning: 1-2 days

## Phase 9: Proactive Learning

**Goal:** AI tự động gợi ý học tập dựa trên hành vi user

### Features
- [ ] Learning pattern detection
- [ ] Spaced repetition reminders
- [ ] "You should review X" suggestions
- [ ] Quiz generation based on weak topics

### Technical Requirements
- Background task scheduler
- LMS webhook for push notifications
- User engagement tracking

### Estimated Effort
- Backend: 3-4 days
- LMS Integration: 2-3 days

---

## Phase 12: Scheduled Tasks

**Goal:** User có thể nói "Nhắc tôi học X vào 8h sáng"

### Features
- [ ] `tool_schedule_task()` - Create reminder
- [ ] `tool_list_tasks()` - View scheduled tasks
- [ ] `tool_cancel_task()` - Cancel reminder
- [ ] Recurring task support (daily, weekly)

### Technical Requirements
- APScheduler or Celery
- Database table for tasks
- Push notification service

### Estimated Effort
- Backend: 3-4 days
- Notification Integration: 2-3 days

---

## Mid-Term (Q2 2025)

| Feature | Description | Priority |
|---------|-------------|----------|
| Voice Interface | GPT-4o style voice chat | MEDIUM |
| MCP Integration | Model Context Protocol | LOW |
| Analytics Dashboard | Learning insights visualization | MEDIUM |
| A/B Testing Framework | Experiment with prompts | LOW |

---

## Long-Term (Q3-Q4 2025)

| Feature | Description |
|---------|-------------|
| Mobile App | React Native companion app |
| Offline Mode | Local LLM for offline learning |
| Multi-language | Support English, Vietnamese |
| Gamification | Points, badges, leaderboards |

---

## Technical Debt

| Item | Priority | Effort |
|------|----------|--------|
| Refactor `chat_service.py` (60KB) | LOW | 4h |
| Add comprehensive unit tests | MEDIUM | 1 week |
| Performance benchmarking | MEDIUM | 2 days |
| Documentation website | LOW | 1 week |

---

## Contribution Guidelines

1. Create feature branch from `main`
2. Follow existing code patterns
3. Add tests for new features
4. Update CHANGELOG.md
5. Create PR with detailed description

---

## Version Numbering

- **Major (X.0.0)**: Breaking changes
- **Minor (1.X.0)**: New features (backward compatible)
- **Patch (1.0.X)**: Bug fixes

---

*Last Updated: 2025-12-20*
