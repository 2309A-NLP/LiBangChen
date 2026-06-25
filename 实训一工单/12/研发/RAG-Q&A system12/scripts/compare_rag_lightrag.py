from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.container import AppContainer
from app.schemas.query import QueryRequest
from app.services.retrievers.lightrag.errors import LightRAGError


def load_questions(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("questions file must contain a JSON array")
    questions = []
    for item in data:
        if isinstance(item, str):
            questions.append({"question": item})
        elif isinstance(item, dict) and item.get("question"):
            questions.append(item)
    return questions


def collect_answers(
    container: AppContainer,
    questions: list[dict[str, Any]],
    retrieval_mode: str,
    top_k: int,
) -> list[dict[str, Any]]:
    answers: list[dict[str, Any]] = []
    for item in questions:
        question = str(item["question"])
        try:
            response = container.pipeline_service.answer_question(
                QueryRequest(
                    question=question,
                    top_k=top_k,
                    include_debug=True,
                    retrieval_mode=retrieval_mode,
                )
            )
            answers.append(
                {
                    "question": question,
                    "retrieval_mode": retrieval_mode,
                    "answer": response.answer,
                    "citations": [citation.model_dump() for citation in response.citations],
                    "debug": response.debug,
                    "error": None,
                }
            )
        except LightRAGError as exc:
            answers.append(
                {
                    "question": question,
                    "retrieval_mode": retrieval_mode,
                    "answer": None,
                    "citations": [],
                    "debug": None,
                    "error": str(exc),
                }
            )
        except Exception as exc:
            answers.append(
                {
                    "question": question,
                    "retrieval_mode": retrieval_mode,
                    "answer": None,
                    "citations": [],
                    "debug": None,
                    "error": str(exc),
                }
            )
    return answers


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Hybrid vs LightRAG Comparison",
        "",
        f"- Questions: {len(report['questions'])}",
        f"- Hybrid mode: {report['hybrid_mode']}",
        f"- LightRAG mode: {report['lightrag_mode']}",
        "",
        "| # | Question | Hybrid citations | LightRAG citations | LightRAG error |",
        "|---|---|---:|---:|---|",
    ]
    hybrid = report["answers"]["hybrid"]
    lightrag = report["answers"]["lightrag"]
    for index, (hybrid_item, lightrag_item) in enumerate(zip(hybrid, lightrag), start=1):
        question = hybrid_item["question"].replace("|", "\\|")
        error = (lightrag_item.get("error") or "").replace("|", "\\|")
        lines.append(
            "| {index} | {question} | {hybrid_count} | {lightrag_count} | {error} |".format(
                index=index,
                question=question,
                hybrid_count=len(hybrid_item.get("citations") or []),
                lightrag_count=len(lightrag_item.get("citations") or []),
                error=error,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare hybrid RAG with LightRAG retrieval.")
    parser.add_argument("--questions", required=True, type=Path, help="JSON question set")
    parser.add_argument("--out", default=Path("reports/rag_lightrag_compare.json"), type=Path)
    parser.add_argument("--markdown-out", default=Path("reports/rag_lightrag_compare.md"), type=Path)
    parser.add_argument("--hybrid-mode", default="hybrid")
    parser.add_argument("--lightrag-mode", default="lightrag_mix")
    parser.add_argument("--top-k", default=8, type=int)
    args = parser.parse_args()

    questions = load_questions(args.questions)
    container = AppContainer.build()
    hybrid_answers = collect_answers(container, questions, args.hybrid_mode, args.top_k)
    lightrag_answers = collect_answers(container, questions, args.lightrag_mode, args.top_k)

    report = {
        "questions": questions,
        "hybrid_mode": args.hybrid_mode,
        "lightrag_mode": args.lightrag_mode,
        "answers": {
            "hybrid": hybrid_answers,
            "lightrag": lightrag_answers,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(report, args.markdown_out)
    print(f"Wrote {args.out}")
    print(f"Wrote {args.markdown_out}")


if __name__ == "__main__":
    main()
