# -*- coding: utf-8 -*-
"""On-demand rerank worker to avoid keeping CrossEncoder resident in the main process."""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    model_path = os.getenv("RERANK_MODEL_PATH", "").strip()
    if not model_path:
        print("missing RERANK_MODEL_PATH", file=sys.stderr)
        return 1

    raw = sys.stdin.read()
    if not raw.strip():
        print("missing payload", file=sys.stderr)
        return 1

    try:
        payload = json.loads(raw)
        query = str(payload.get("query") or "").strip()
        documents = [str(item or "") for item in (payload.get("documents") or [])]
    except Exception as exc:
        print(f"invalid payload: {exc}", file=sys.stderr)
        return 1

    if not query or not documents:
        print("query or documents empty", file=sys.stderr)
        return 1

    try:
        from sentence_transformers import CrossEncoder
    except Exception as exc:
        print(f"failed to import CrossEncoder: {exc}", file=sys.stderr)
        return 1

    try:
        model = CrossEncoder(model_path, trust_remote_code=True)
        scores = model.predict([(query, doc) for doc in documents])
    except Exception as exc:
        print(f"rerank execution failed: {exc}", file=sys.stderr)
        return 1

    result = {"scores": [float(score) for score in scores]}
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
