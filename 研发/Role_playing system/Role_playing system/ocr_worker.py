# -*- coding: utf-8 -*-
"""Isolated PaddleOCR worker to avoid protobuf conflicts with Milvus."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
from PIL import Image


def _get_model_root() -> Path:
    configured_root = os.getenv("PADDLEOCR_MODEL_ROOT", "").strip()
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    return Path.home().resolve() / "ocr_models_ascii"


def _extract_ocr_lines(result) -> list[str]:
    lines: list[str] = []

    def collect(node):
        if node is None:
            return
        if isinstance(node, str):
            text = node.strip()
            if text:
                lines.append(text)
            return
        if isinstance(node, (list, tuple)):
            if len(node) >= 2 and isinstance(node[1], (list, tuple)) and node[1]:
                candidate = node[1][0]
                if isinstance(candidate, str):
                    text = candidate.strip()
                    if text:
                        lines.append(text)
                    return
            for item in node:
                collect(item)

    collect(result)
    deduped: list[str] = []
    seen = set()
    for line in lines:
        if line in seen:
            continue
        deduped.append(line)
        seen.add(line)
    return deduped


def main() -> int:
    os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    try:
        with redirect_stdout(io.StringIO()):
            import torch  # noqa: F401
            from paddleocr import PaddleOCR
    except Exception as exc:
        print(f"failed to import OCR dependencies: {exc}", file=sys.stderr)
        return 1

    file_bytes = sys.stdin.buffer.read()
    if not file_bytes:
        print("no image bytes provided", file=sys.stderr)
        return 1

    try:
        image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    except Exception as exc:
        print(f"failed to decode image: {exc}", file=sys.stderr)
        return 1

    model_root = _get_model_root()
    det_model_dir = model_root / "det" / "ch"
    rec_model_dir = model_root / "rec" / "ch"
    cls_model_dir = model_root / "cls"

    try:
        with redirect_stdout(io.StringIO()):
            engine = PaddleOCR(
                use_angle_cls=True,
                lang="ch",
                show_log=False,
                det_model_dir=str(det_model_dir),
                rec_model_dir=str(rec_model_dir),
                cls_model_dir=str(cls_model_dir),
            )
            result = engine.ocr(np.array(image), cls=True)
            lines = _extract_ocr_lines(result)
    except Exception as exc:
        print(f"ocr execution failed: {exc}", file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps({"lines": lines}, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
