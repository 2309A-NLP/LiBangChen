"""Quick test: RAG -> LiveTalking /human integration"""
import json, urllib.request, sys

# Test that the NEW livetalking server can reach RAG
print("=== RAG health ===")
r = urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)
print(r.read().decode())

print("\n=== LiveTalking health ===")
r = urllib.request.urlopen("http://127.0.0.1:8010/index.html", timeout=5)
print(f"HTTP {r.status}")

print("\n=== LiveTalking /human (no session, expect session-not-found, not RAG error) ===")
payload = json.dumps({
    "sessionid": "diag001",
    "text": "你好",
    "type": "chat"
}).encode()
req = urllib.request.Request("http://127.0.0.1:8010/human", data=payload,
    headers={"Content-Type": "application/json"}, method="POST")
try:
    r = urllib.request.urlopen(req, timeout=15)
    data = json.loads(r.read().decode())
    print(f"Response: {data}")
except urllib.request.HTTPError as e:
    body = json.loads(e.read().decode())
    print(f"Response: {body}")
    # If it says "session not found" that means RAG module loaded correctly
    # If it says something else, there might be a real issue
    if "session not found" in str(body):
        print(">> llm_rag module loaded successfully (session needed for full test)")
    else:
        print(">> WARNING: Unexpected response!")

print("\n=== DONE ===")
