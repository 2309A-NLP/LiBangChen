from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.container import AppContainer
from app.schemas.query import QueryRequest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--retrieval-mode", default="fulltext")
    parser.add_argument("--top-k", default=8, type=int)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with args.questions.open("r", encoding="utf-8") as handle:
        questions = json.load(handle)

    container = AppContainer.build()
    container.document_ingestion_service.load_document(force=True)
    container.prepare_retrieval(selected_only=False)

    rows = []
    for index, item in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] {item['source']}", flush=True)
        container.document_ingestion_service.select_sources([item["source"]])
        started_at = time.perf_counter()
        response = container.pipeline_service.answer_question(
            QueryRequest(
                question=item["question"],
                source_files=[item["source"]],
                include_debug=True,
                retrieval_mode=args.retrieval_mode,
                top_k=args.top_k,
                reranker_enabled=False,
            )
        )
        rows.append(
            {
                "question": item["question"],
                "ground_truth": item["ground_truth"],
                "source": item["source"],
                "answer": response.answer,
                "contexts": [citation.snippet for citation in response.citations if citation.snippet],
                "citations": [citation.model_dump() for citation in response.citations],
                "debug": response.debug,
                "elapsed_seconds": round(time.perf_counter() - started_at, 3),
                "error": None,
            }
        )

    output_path = args.output_dir / "ragas_eval_samples.json"
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)
    print(f"samples: {output_path}", flush=True)


if __name__ == "__main__":
    main()
