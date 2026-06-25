from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import requests
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import answer_correctness, context_precision, context_recall, faithfulness
from ragas.run_config import RunConfig

from app.core.config import Settings


DEFAULT_OUTPUT_DIR = Path(".tmp")


def load_questions(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Question file must contain a JSON array.")
    return data


def request_answer(
    api_url: str,
    item: dict[str, Any],
    *,
    top_k: int,
    retrieval_mode: str,
    timeout: float,
) -> dict[str, Any]:
    payload = {
        "question": item["question"],
        "source_files": [item["source"]],
        "include_debug": True,
        "top_k": top_k,
        "retrieval_mode": retrieval_mode,
        "reranker_enabled": False,
    }
    started_at = time.perf_counter()
    response = requests.post(f"{api_url.rstrip('/')}/api/query", json=payload, timeout=timeout)
    elapsed = round(time.perf_counter() - started_at, 3)
    response.raise_for_status()
    body = response.json()
    citations = body.get("citations") or []
    contexts = [str(citation.get("snippet") or "") for citation in citations if citation.get("snippet")]
    return {
        "question": item["question"],
        "ground_truth": item["ground_truth"],
        "source": item["source"],
        "answer": body.get("answer", ""),
        "contexts": contexts,
        "citations": citations,
        "debug": body.get("debug"),
        "elapsed_seconds": elapsed,
        "error": None,
    }


def collect_answers(
    questions: list[dict[str, Any]],
    *,
    api_url: str,
    top_k: int,
    retrieval_mode: str,
    timeout: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(questions, start=1):
        source = item.get("source", "")
        print(f"[{index}/{len(questions)}] querying source={source}", flush=True)
        try:
            rows.append(
                request_answer(
                    api_url,
                    item,
                    top_k=top_k,
                    retrieval_mode=retrieval_mode,
                    timeout=timeout,
                )
            )
        except Exception as exc:  # keep the run auditable even if one item fails
            rows.append(
                {
                    "question": item.get("question", ""),
                    "ground_truth": item.get("ground_truth", ""),
                    "source": source,
                    "answer": "",
                    "contexts": [],
                    "citations": [],
                    "debug": None,
                    "elapsed_seconds": None,
                    "error": repr(exc),
                }
            )
            print(f"  error: {exc!r}", flush=True)
    return rows


def build_llm(settings: Settings):
    from langchain_openai import ChatOpenAI

    if not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model:
        raise RuntimeError("LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL are required for RAGAS.")
    return ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=0,
        timeout=120,
        max_retries=2,
    )


def build_embeddings(settings: Settings):
    from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=str(settings.embedding_model_name),
        model_kwargs={"device": settings.embedding_device},
        encode_kwargs={"normalize_embeddings": True},
    )


def safe_number(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def run_ragas(rows: list[dict[str, Any]], output_dir: Path, *, metric_set: str) -> dict[str, Any]:
    valid_rows = [row for row in rows if not row.get("error")]
    dataset = Dataset.from_dict(
        {
            "question": [row["question"] for row in valid_rows],
            "answer": [row["answer"] for row in valid_rows],
            "contexts": [row["contexts"] for row in valid_rows],
            "ground_truth": [row["ground_truth"] for row in valid_rows],
        }
    )
    settings = Settings()
    metrics = [faithfulness, context_precision, context_recall]
    embeddings = None
    if metric_set == "full":
        metrics.append(answer_correctness)
        embeddings = build_embeddings(settings)

    result = evaluate(
        dataset,
        metrics=metrics,
        llm=build_llm(settings),
        embeddings=embeddings,
        run_config=RunConfig(timeout=180, max_retries=2, max_workers=2),
        is_async=False,
        raise_exceptions=False,
    )

    frame = result.to_pandas()
    scores_csv = output_dir / "ragas_eval_scores.csv"
    frame.to_csv(scores_csv, index=False, encoding="utf-8-sig")

    metric_names = [metric.name for metric in metrics]
    summary = {
        name: safe_number(float(frame[name].mean())) if name in frame else None
        for name in metric_names
    }
    per_item = json.loads(frame.to_json(orient="records", force_ascii=False))
    payload = {
        "summary": summary,
        "metric_set": metric_set,
        "items": per_item,
        "scores_csv": str(scores_csv),
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", required=True, type=Path)
    parser.add_argument("--api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, type=Path)
    parser.add_argument("--top-k", default=8, type=int)
    parser.add_argument("--retrieval-mode", default="fulltext")
    parser.add_argument("--request-timeout", default=300.0, type=float)
    parser.add_argument("--limit", default=None, type=int)
    parser.add_argument("--skip-ragas", action="store_true")
    parser.add_argument("--samples", default=None, type=Path)
    parser.add_argument("--metric-set", choices=["llm-only", "full"], default="full")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.samples:
        with args.samples.open("r", encoding="utf-8") as handle:
            rows = json.load(handle)
        print(f"samples: {args.samples}", flush=True)
    else:
        questions = load_questions(args.questions)
        if args.limit is not None:
            questions = questions[: args.limit]

        rows = collect_answers(
            questions,
            api_url=args.api_url,
            top_k=args.top_k,
            retrieval_mode=args.retrieval_mode,
            timeout=args.request_timeout,
        )

        samples_path = args.output_dir / "ragas_eval_samples.json"
        with samples_path.open("w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
        print(f"samples: {samples_path}", flush=True)

    if args.skip_ragas:
        return

    scores = run_ragas(rows, args.output_dir, metric_set=args.metric_set)
    scores_path = args.output_dir / "ragas_eval_scores.json"
    with scores_path.open("w", encoding="utf-8") as handle:
        json.dump(scores, handle, ensure_ascii=False, indent=2, default=safe_number)
    print(f"scores: {scores_path}", flush=True)
    print(json.dumps(scores["summary"], ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
