#!/usr/bin/env python3
"""
Test Full Conversation - Đánh giá độ tự nhiên của AI
Xuất kết quả ra file TXT để báo cáo chuyên gia

Kịch bản hội thoại:
1. Giới thiệu bản thân (test memory)
2. Hỏi về COLREGs (test RAG)
3. Hỏi tiếp câu liên quan (test context)
4. Chia sẻ cảm xúc (test empathy)
5. Hỏi thêm quy tắc khác (test anti-repetition)
6. Kiểm tra AI nhớ tên (test cross-turn memory)
"""
import requests
import sys
import uuid
from datetime import datetime

# URLs
PROD_URL = "https://maritime-ai-chatbot.onrender.com"
LOCAL_URL = "http://localhost:8000"

BASE_URL = PROD_URL if "--prod" in sys.argv else LOCAL_URL

# Generate unique user_id for this test
USER_ID = f"test_conversation_{uuid.uuid4().hex[:8]}"
SESSION_ID = f"session_{uuid.uuid4().hex[:8]}"

# Conversation script
CONVERSATION = [
    {
        "turn": 1,
        "context": "Giới thiệu bản thân",
        "message": "Xin chào! Tôi là Minh, sinh viên năm 3 ngành Hàng hải. Tôi đang chuẩn bị thi COLREGs.",
        "expected": ["greeting", "name_recognition", "encouragement"]
    },
    {
        "turn": 2,
        "context": "Hỏi về COLREGs - Quy tắc 5",
        "message": "Anh có thể giải thích quy tắc 5 về quan sát cho em được không?",
        "expected": ["rule_5_content", "look_out", "proper_means"]
    },
    {
        "turn": 3,
        "context": "Hỏi tiếp - Quy tắc 6",
        "message": "Còn quy tắc 6 về tốc độ an toàn thì sao ạ?",
        "expected": ["rule_6_content", "safe_speed", "different_opening"]
    },
    {
        "turn": 4,
        "context": "Chia sẻ cảm xúc - Test empathy",
        "message": "Em thấy học COLREGs hơi khó, nhiều quy tắc quá 😅",
        "expected": ["empathy", "encouragement", "not_just_answer"]
    },
    {
        "turn": 5,
        "context": "Hỏi thêm - Quy tắc 7",
        "message": "Quy tắc 7 về nguy cơ va chạm thì nói gì vậy anh?",
        "expected": ["rule_7_content", "risk_collision", "different_opening"]
    },
    {
        "turn": 6,
        "context": "Kiểm tra AI nhớ tên",
        "message": "Cảm ơn anh nhiều! Anh có lời khuyên gì cho em trước kỳ thi không?",
        "expected": ["advice", "name_minh", "personalized"]
    }
]


def send_message(message: str, turn: int) -> dict:
    """Send message to chat API"""
    try:
        # Get API key from environment
        import os
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.getenv("LMS_API_KEY", "secret_key_cho_team_lms")
        
        response = requests.post(
            f"{BASE_URL}/api/v1/chat",
            headers={"X-API-Key": api_key},
            json={
                "user_id": USER_ID,
                "message": message,
                "role": "student",
                "session_id": SESSION_ID
            },
            timeout=60
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def format_conversation_report(results: list) -> str:
    """Format conversation results for report"""
    report = []
    report.append("=" * 80)
    report.append("BÁO CÁO ĐÁNH GIÁ ĐỘ TỰ NHIÊN CỦA AI CHATBOT")
    report.append("Maritime AI Tutor - Production Test")
    report.append("=" * 80)
    report.append("")
    report.append(f"Ngày test: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"Server: {BASE_URL}")
    report.append(f"User ID: {USER_ID}")
    report.append(f"Session ID: {SESSION_ID}")
    report.append("")
    report.append("-" * 80)
    report.append("KỊCH BẢN HỘI THOẠI")
    report.append("-" * 80)
    report.append("")
    
    for result in results:
        turn = result["turn"]
        context = result["context"]
        user_msg = result["user_message"]
        ai_response = result["ai_response"]
        sources = result.get("sources", [])
        
        report.append(f"[TURN {turn}] {context}")
        report.append("-" * 40)
        report.append(f"[USER] {user_msg}")
        report.append("")
        report.append(f"[AI] {ai_response}")
        report.append("")
        
        if sources:
            report.append(f"[SOURCES] {len(sources)} nguồn tham khảo:")
            for i, src in enumerate(sources[:3], 1):
                title = src.get("title", "N/A")
                report.append(f"  {i}. {title}")
        
        report.append("")
        report.append("=" * 80)
        report.append("")
    
    # Analysis section
    report.append("-" * 80)
    report.append("PHÂN TÍCH")
    report.append("-" * 80)
    report.append("")
    
    # Check for repetition
    openings = [r["ai_response"][:50] for r in results]
    unique_openings = len(set(openings))
    
    report.append(f"1. Đa dạng cách mở đầu: {unique_openings}/{len(results)} unique")
    
    # Check for "À" pattern
    a_count = sum(1 for r in results if r["ai_response"].strip().startswith("À"))
    report.append(f"2. Bắt đầu bằng 'À': {a_count}/{len(results)} lần")
    
    # Check name memory (turn 6)
    if len(results) >= 6:
        last_response = results[5]["ai_response"].lower()
        name_remembered = "minh" in last_response
        report.append(f"3. AI nhớ tên user (Minh): {'✅ CÓ' if name_remembered else '❌ KHÔNG'}")
    
    report.append("")
    report.append("-" * 80)
    report.append("KẾT LUẬN")
    report.append("-" * 80)
    
    # Overall assessment
    issues = []
    if unique_openings < len(results) * 0.8:
        issues.append("Cách mở đầu còn lặp lại")
    if a_count > 1:
        issues.append("Còn dùng 'À' nhiều lần")
    if len(results) >= 6 and not name_remembered:
        issues.append("Không nhớ tên user")
    
    if not issues:
        report.append("✅ AI HOẠT ĐỘNG TỐT - Đa dạng, tự nhiên, nhớ context")
    else:
        report.append("⚠️ CẦN CẢI THIỆN:")
        for issue in issues:
            report.append(f"  - {issue}")
    
    report.append("")
    report.append("=" * 80)
    report.append("HẾT BÁO CÁO")
    report.append("=" * 80)
    
    return "\n".join(report)


def main():
    print(f"\n{'='*60}")
    print("TEST FULL CONVERSATION - PRODUCTION")
    print(f"{'='*60}")
    print(f"Server: {BASE_URL}")
    print(f"User: {USER_ID}")
    print(f"Session: {SESSION_ID}")
    print(f"{'='*60}\n")
    
    results = []
    
    for conv in CONVERSATION:
        turn = conv["turn"]
        context = conv["context"]
        message = conv["message"]
        
        print(f"[Turn {turn}] {context}")
        print(f"  User: {message[:50]}...")
        
        response = send_message(message, turn)
        
        if "error" in response:
            print(f"  ❌ Error: {response['error']}")
            ai_response = f"ERROR: {response['error']}"
            sources = []
        else:
            # Handle different response formats
            data = response.get("data", response)
            ai_response = data.get("answer") or data.get("response") or data.get("message") or str(data)
            sources = data.get("sources", [])
            print(f"  AI: {ai_response[:60]}...")
            if sources:
                print(f"  Sources: {len(sources)}")
        
        results.append({
            "turn": turn,
            "context": context,
            "user_message": message,
            "ai_response": ai_response,
            "sources": sources
        })
        
        print()
    
    # Generate report
    report = format_conversation_report(results)
    
    # Save to file
    import os
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "Documents", "baocao")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "CONVERSATION_TEST_REPORT.txt")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"\n{'='*60}")
    print(f"✅ Report saved to: {output_file}")
    print(f"{'='*60}")
    
    # Also print report to console
    print("\n" + report)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
