import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.page_analyzer import PageAnalyzer

a = PageAnalyzer()
text = "Day la mot doan van ban thuan tuy khong co bang bieu hay hinh anh."
r = a.analyze_text_content(text)
print(f"has_tables: {r['has_tables']}")
print(f"has_diagrams: {r['has_diagrams']}")
print(f"has_maritime: {r['has_maritime_signals']}")
print(f"is_visual: {r['is_visual']}")
print(f"Keywords: {a.maritime_keywords}")
