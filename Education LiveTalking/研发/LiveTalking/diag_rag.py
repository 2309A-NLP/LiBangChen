"""Test RAG from the livetalking conda env to diagnose the crash"""
import json, urllib.request, sys, time

BASE = "http://127.0.0.1:8000"

print("=== Step 1: Login ===")
payload = json.dumps({"username": "123456", "password": "123456"}).encode()
req = urllib.request.Request(f"{BASE}/api/users/login", data=payload,
    headers={"Content-Type": "application/json"}, method="POST")
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode())
    token = data["data"]["access_token"]
    print(f"OK - token: {token[:20]}...")
except Exception as e:
    print(f"Login FAILED: {e}")
    sys.exit(1)

print("\n=== Step 2: Create conversation ===")
payload = json.dumps({"role_type": "teacher"}).encode()
req = urllib.request.Request(f"{BASE}/api/conversations/create", data=payload,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}, method="POST")
try:
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read().decode())
    conv_id = data["data"]["conversation_id"]
    print(f"OK - conv_id: {conv_id}")
except Exception as e:
    print(f"Create conversation FAILED: {e}")
    sys.exit(1)

print("\n=== Step 3: Stream chat (simulating 3 requests) ===")
for i in range(3):
    print(f"\n--- Request {i+1} ---")
    payload = json.dumps({
        "conversation_id": conv_id,
        "message": "简单说一句话",
        "stream": True,
    }).encode()
    req = urllib.request.Request(f"{BASE}/api/chat", data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        }, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        full = ""
        buffer = ""
        for chunk in resp:
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                line, buffer = buffer.split("\n\n", 1)
                line = line.strip()
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                    if event.get("type") == "delta":
                        full += event.get("delta", "")
                    elif event.get("type") == "done":
                        pass
                except:
                    pass
        print(f"OK - got {len(full)} chars: {full[:80]}...")
    except Exception as e:
        print(f"Stream FAILED: {e}")
        if hasattr(e, 'read'):
            print(f"Body: {e.read().decode()[:200]}")

print("\n=== All tests done ===")
