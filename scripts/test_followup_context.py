"""
Test Follow-up Context Understanding

Kiểm tra AI có hiểu ngữ cảnh câu hỏi mơ hồ/nối tiếp không.
Ví dụ: "Đèn đỏ thì sao?" -> "Còn đèn vàng thì sao?"

Mục tiêu: Xem <thinking> tag để đánh giá chất lượng suy luận
"""
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

RENDER_URL = os.getenv("RENDER_URL", "https://maritime-ai-chatbot.onrender.com")
API_KEY = os.getenv("API_KEY", "")

def send_message(message: str, user_id: str, session_id: str) -> dict:
    """Send chat message"""
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    payload = {
        "message": message,
        "user_id": user_id,
        "session_id": session_id,
        "role": "student"
    }
    
    response = requests.post(
        f"{RENDER_URL}/api/v1/chat/",
        json=payload,
        headers=headers,
        timeout=120
    )
    
    if response.status_code == 200:
        return response.json()
    return {"error": response.status_code, "detail": response.text[:200]}


def extract_thinking(answer: str) -> str:
    """Extract <thinking> content from answer"""
    if "<thinking>" in answer and "</thinking>" in answer:
        start = answer.find("<thinking>") + len("<thinking>")
        end = answer.find("</thinking>")
        return answer[start:end].strip()
    return ""


def test_light_signals_followup():
    """Test follow-up questions about navigation lights"""
    print("="*70)
    print("TEST 1: NAVIGATION LIGHTS FOLLOW-UP")
    print("Kiểm tra AI hiểu ngữ cảnh khi hỏi về đèn tín hiệu")
    print("="*70)
    
    session_id = f"lights-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    user_id = "lights-test-user"
    
    # Message 1: Ask about red light
    print("\n📤 Message 1: 'Khi thấy đèn đỏ trên tàu khác, tôi nên làm gì?'")
    r1 = send_message("Khi thấy đèn đỏ trên tàu khác, tôi nên làm gì?", user_id, session_id)
    answer1 = r1.get("data", {}).get("answer", "")
    thinking1 = extract_thinking(answer1)
    
    print(f"\n🧠 THINKING 1:\n{thinking1}")
    print(f"\n📥 RESPONSE 1:\n{answer1[answer1.find('</thinking>')+11:].strip()[:500]}...")
    
    # Message 2: Follow-up about green light (ambiguous)
    print("\n" + "-"*50)
    print("📤 Message 2: 'Còn đèn xanh thì sao?' (MƠ HỒ)")
    r2 = send_message("Còn đèn xanh thì sao?", user_id, session_id)
    answer2 = r2.get("data", {}).get("answer", "")
    thinking2 = extract_thinking(answer2)
    
    print(f"\n🧠 THINKING 2:\n{thinking2}")
    print(f"\n📥 RESPONSE 2:\n{answer2[answer2.find('</thinking>')+11:].strip()[:500]}...")
    
    # Message 3: Follow-up about white light
    print("\n" + "-"*50)
    print("📤 Message 3: 'Đèn trắng thì sao?' (MƠ HỒ)")
    r3 = send_message("Đèn trắng thì sao?", user_id, session_id)
    answer3 = r3.get("data", {}).get("answer", "")
    thinking3 = extract_thinking(answer3)
    
    print(f"\n🧠 THINKING 3:\n{thinking3}")
    print(f"\n📥 RESPONSE 3:\n{answer3[answer3.find('</thinking>')+11:].strip()[:500]}...")
    
    # Analysis
    print("\n" + "="*70)
    print("📊 ANALYSIS - THINKING QUALITY")
    print("="*70)
    
    # Check if AI understood context in thinking
    context_keywords = ["đèn", "tàu", "tín hiệu", "mạn", "hàng hải", "colregs", "trước đó", "câu hỏi"]
    
    context_in_2 = sum(1 for kw in context_keywords if kw in thinking2.lower())
    context_in_3 = sum(1 for kw in context_keywords if kw in thinking3.lower())
    
    print(f"\n🔍 Thinking 2 (đèn xanh):")
    print(f"   Context keywords found: {context_in_2}")
    print(f"   AI hiểu ngữ cảnh: {'✅' if context_in_2 >= 2 else '⚠️'}")
    
    print(f"\n🔍 Thinking 3 (đèn trắng):")
    print(f"   Context keywords found: {context_in_3}")
    print(f"   AI hiểu ngữ cảnh: {'✅' if context_in_3 >= 2 else '⚠️'}")


def test_registration_followup():
    """Test follow-up questions about ship registration"""
    print("\n" + "="*70)
    print("TEST 2: SHIP REGISTRATION FOLLOW-UP")
    print("Kiểm tra AI hiểu ngữ cảnh khi hỏi về đăng ký tàu")
    print("="*70)
    
    session_id = f"reg-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    user_id = "reg-test-user"
    
    # Message 1: Ask about registration conditions
    print("\n📤 Message 1: 'Điều kiện đăng ký tàu biển Việt Nam là gì?'")
    r1 = send_message("Điều kiện đăng ký tàu biển Việt Nam là gì?", user_id, session_id)
    answer1 = r1.get("data", {}).get("answer", "")
    thinking1 = extract_thinking(answer1)
    
    print(f"\n🧠 THINKING 1:\n{thinking1}")
    print(f"\n📥 RESPONSE 1:\n{answer1[answer1.find('</thinking>')+11:].strip()[:400]}...")
    
    # Message 2: Follow-up about documents (ambiguous)
    print("\n" + "-"*50)
    print("📤 Message 2: 'Cần những giấy tờ gì?' (MƠ HỒ)")
    r2 = send_message("Cần những giấy tờ gì?", user_id, session_id)
    answer2 = r2.get("data", {}).get("answer", "")
    thinking2 = extract_thinking(answer2)
    
    print(f"\n🧠 THINKING 2:\n{thinking2}")
    print(f"\n📥 RESPONSE 2:\n{answer2[answer2.find('</thinking>')+11:].strip()[:400]}...")
    
    # Message 3: Follow-up about fees
    print("\n" + "-"*50)
    print("📤 Message 3: 'Phí bao nhiêu?' (RẤT MƠ HỒ)")
    r3 = send_message("Phí bao nhiêu?", user_id, session_id)
    answer3 = r3.get("data", {}).get("answer", "")
    thinking3 = extract_thinking(answer3)
    
    print(f"\n🧠 THINKING 3:\n{thinking3}")
    print(f"\n📥 RESPONSE 3:\n{answer3[answer3.find('</thinking>')+11:].strip()[:400]}...")
    
    # Analysis
    print("\n" + "="*70)
    print("📊 ANALYSIS - CONTEXT UNDERSTANDING")
    print("="*70)
    
    # Check if AI connected to registration context
    reg_keywords = ["đăng ký", "tàu", "giấy tờ", "hồ sơ", "thủ tục", "trước đó", "câu hỏi"]
    
    context_in_2 = sum(1 for kw in reg_keywords if kw in thinking2.lower())
    context_in_3 = sum(1 for kw in reg_keywords if kw in thinking3.lower())
    
    print(f"\n🔍 Thinking 2 (giấy tờ):")
    print(f"   Registration context found: {context_in_2}")
    print(f"   AI liên kết đúng ngữ cảnh: {'✅' if context_in_2 >= 2 else '⚠️'}")
    
    print(f"\n🔍 Thinking 3 (phí):")
    print(f"   Registration context found: {context_in_3}")
    print(f"   AI liên kết đúng ngữ cảnh: {'✅' if context_in_3 >= 2 else '⚠️'}")


def test_colregs_rules_followup():
    """Test follow-up questions about COLREGs rules"""
    print("\n" + "="*70)
    print("TEST 3: COLREGS RULES FOLLOW-UP")
    print("Kiểm tra AI hiểu ngữ cảnh khi hỏi về các quy tắc COLREGs")
    print("="*70)
    
    session_id = f"colregs-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    user_id = "colregs-test-user"
    
    # Message 1: Ask about Rule 15
    print("\n📤 Message 1: 'Quy tắc 15 COLREGs nói về gì?'")
    r1 = send_message("Quy tắc 15 COLREGs nói về gì?", user_id, session_id)
    answer1 = r1.get("data", {}).get("answer", "")
    thinking1 = extract_thinking(answer1)
    
    print(f"\n🧠 THINKING 1:\n{thinking1}")
    print(f"\n📥 RESPONSE 1:\n{answer1[answer1.find('</thinking>')+11:].strip()[:400]}...")
    
    # Message 2: Follow-up about Rule 16 (ambiguous)
    print("\n" + "-"*50)
    print("📤 Message 2: 'Còn quy tắc 16?' (MƠ HỒ)")
    r2 = send_message("Còn quy tắc 16?", user_id, session_id)
    answer2 = r2.get("data", {}).get("answer", "")
    thinking2 = extract_thinking(answer2)
    
    print(f"\n🧠 THINKING 2:\n{thinking2}")
    print(f"\n📥 RESPONSE 2:\n{answer2[answer2.find('</thinking>')+11:].strip()[:400]}...")
    
    # Message 3: Follow-up about Rule 17
    print("\n" + "-"*50)
    print("📤 Message 3: 'Quy tắc 17 thì sao?' (MƠ HỒ)")
    r3 = send_message("Quy tắc 17 thì sao?", user_id, session_id)
    answer3 = r3.get("data", {}).get("answer", "")
    thinking3 = extract_thinking(answer3)
    
    print(f"\n🧠 THINKING 3:\n{thinking3}")
    print(f"\n📥 RESPONSE 3:\n{answer3[answer3.find('</thinking>')+11:].strip()[:400]}...")


def main():
    print("="*70)
    print("MARITIME AI TUTOR - FOLLOW-UP CONTEXT TEST")
    print(f"Server: {RENDER_URL}")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*70)
    print("\n⚠️ Chú ý: Xem kỹ <thinking> tag để đánh giá chất lượng suy luận")
    
    # Run tests
    test_light_signals_followup()
    test_registration_followup()
    test_colregs_rules_followup()
    
    print("\n" + "="*70)
    print("📊 OVERALL SUMMARY")
    print("="*70)
    print("""
Các điểm cần đánh giá trong <thinking>:
1. AI có nhận ra đây là câu hỏi follow-up không?
2. AI có liên kết với ngữ cảnh câu hỏi trước không?
3. AI có quyết định đúng khi nào cần search, khi nào dùng context?
4. Suy luận có logic và hợp lý không?
""")


if __name__ == "__main__":
    main()
