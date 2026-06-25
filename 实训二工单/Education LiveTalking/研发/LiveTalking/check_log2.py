import re

with open("D:\\LiveTalking\\livetalking.log", "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

# Show last 10 lines containing RAG
lines = content.split("\n")
rag_lines = [l for l in lines if "RAG" in l]
for l in rag_lines[-10:]:
    print(l)
