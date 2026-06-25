import sys

with open("D:\\LiveTalking\\livetalking.log", "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

# Count RAG occurrence
rag_count = content.count("RAG")
print(f"Total RAG entries: {rag_count}")

# Get the last RAG lines by counting
lines = content.split("\n")
rag_indices = [i for i, l in enumerate(lines) if "RAG" in l]
if rag_indices:
    last_rag_idx = rag_indices[-1]
    # Show lines around last RAG entry
    for i in range(max(0, last_rag_idx-2), min(len(lines), last_rag_idx+3)):
        # Output in ASCII-safe mode
        safe = lines[i].encode("ascii", errors="replace").decode("ascii")
        print(safe)
