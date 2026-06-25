import re

with open("D:\\LiveTalking\\livetalking.log", "r", encoding="utf-8", errors="replace") as f:
    lines = f.readlines()

# Find RAG timing lines
for line in lines:
    if "RAG" in line and ("耗时" in line or "完成" in line or "收到" in line):
        print(line.rstrip())
