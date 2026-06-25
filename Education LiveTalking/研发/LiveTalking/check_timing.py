with open("D:\\LiveTalking\\livetalking.log", "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

lines = content.split("\n")
# Find timing lines
for l in lines:
    if any(k in l for k in ["总耗时", "edge tts", "首token", "连接成功, 耗时"]):
        ts = l[:23] if len(l) > 23 else ""
        text = l[50:] if len(l) > 50 else l
        print(f"{ts} | {text.strip()}")
