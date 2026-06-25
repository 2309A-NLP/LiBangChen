import urllib.request, json, time
url = 'http://127.0.0.1:8010/api/query'
data = {
    'question': '组织结构图中销售部有哪些销售处',
    'source_files': ['招股说明书1-无水印.pdf'],
    'include_debug': True
}
start = time.time()
req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='POST')
with urllib.request.urlopen(req, timeout=300) as resp:
    result = json.loads(resp.read().decode('utf-8'))
    elapsed = time.time() - start
    d = result.get('debug', {})
    print(f"time: {elapsed:.1f}s")
    print(f"chart_fallback: {d.get('chart_fallback_used')}")
    print(f"chunks: {d.get('retrieved_chunk_count')}")
    print(f"answer: {result.get('answer', '')[:300]}")
