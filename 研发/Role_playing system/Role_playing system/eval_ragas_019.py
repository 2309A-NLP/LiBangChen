# -*- coding: utf-8 -*-
"""Offline RAGAS evaluation entrypoint with broader dependency compatibility."""

from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# Preload vector_store before ragas/datasets on Windows to avoid torch DLL init failures.
from vector_store import MilvusStore  # noqa: F401

from datasets import Dataset, Features, Sequence, Value

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover - depends on installed package set
    from langchain_community.chat_models import ChatOpenAI

try:
    from langchain_huggingface import HuggingFaceEmbeddings
except ImportError:  # pragma: no cover - depends on installed package set
    from langchain_community.embeddings import HuggingFaceEmbeddings

from ragas import evaluate

try:
    from ragas.embeddings import LangchainEmbeddingsWrapper
except ImportError:  # pragma: no cover - compatibility fallback
    from ragas.embeddings.base import LangchainEmbeddingsWrapper

try:
    from ragas.llms import LangchainLLMWrapper
except ImportError:  # pragma: no cover - compatibility fallback
    from ragas.llms.base import LangchainLLMWrapper

from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness
from ragas.run_config import RunConfig

from chat_bot import ChatBot
from llm_settings import load_llm_config
from models import SessionLocal, User, init_database
from security import hash_password


ROOT = Path(__file__).resolve().parent
DEFAULT_TESTSET_PATH = ROOT / "evals" / "testset_manual.jsonl"
RESULT_PATH = ROOT / "evals" / "ragas_result_019.csv"
INPUT_EXPORT_PATH = ROOT / "evals" / "ragas_inputs_019.jsonl"
WINDOWS_EMBEDDING_PATH = ROOT / "models" / "bge-m3"
LINUX_EMBEDDING_CANDIDATES = [
    Path("/root/.cache/modelscope/hub/models/BAAI/bge-m3"),
    Path("/root/.cache/huggingface/hub/models--BAAI--bge-m3"),
]


def is_non_openai_base(api_base: str) -> bool:
    value = (api_base or "").strip().lower()
    return bool(value) and "api.openai.com" not in value


def is_deepseek_base(api_base: str) -> bool:
    value = (api_base or "").strip().lower()
    return "api.deepseek.com" in value


class DeepSeekCompatibleChatOpenAI(ChatOpenAI):
    """Clamp unsupported `n` values for DeepSeek-compatible judge calls."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if "n" in kwargs and kwargs["n"] not in (None, 1):
            kwargs["n"] = 1
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if "n" in kwargs and kwargs["n"] not in (None, 1):
            kwargs["n"] = 1
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)


def resolve_testset_path() -> Path:
    env_value = (os.getenv("RAGAS_TESTSET_PATH") or "").strip()
    if not env_value:
        return DEFAULT_TESTSET_PATH

    candidate = Path(env_value)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate


def load_testset(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for line in file_obj:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    if not rows:
        raise ValueError(f"测试集为空: {path}")
    return rows


def resolve_metrics_mode() -> str:
    value = (os.getenv("RAGAS_METRICS") or "full").strip().lower()
    if value in {"minimal", "fast", "core"}:
        return "minimal"
    return "full"


def resolve_max_workers() -> int:
    raw_value = (os.getenv("RAGAS_MAX_WORKERS") or "1").strip()
    try:
        return max(int(raw_value), 1)
    except ValueError:
        return 1


def get_or_create_eval_user() -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "ragas_eval").first()
        if user:
            return user.id

        user = User(
            username="ragas_eval",
            password=hash_password("ragas_eval_only"),
            email="ragas_eval@example.local",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()


def normalize_eval_text(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return ""

    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"^#{1,6}\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def format_context_blocks(hits: Iterable[Dict[str, str]]) -> List[str]:
    blocks: List[str] = []
    for hit in hits:
        title = (hit.get("title") or "").strip()
        content = normalize_eval_text(hit.get("content") or "")
        source = (hit.get("source") or "").strip()

        parts: List[str] = []
        if title:
            parts.append(f"标题：{title}")
        if content:
            parts.append(f"内容：{content}")
        if source:
            parts.append(f"来源：{source}")
        if parts:
            blocks.append("\n".join(parts))
    return blocks


def split_context_text(context_text: str) -> List[str]:
    normalized = normalize_eval_text(context_text)
    if not normalized:
        return []

    blocks = [block.strip() for block in normalized.split("\n\n") if block.strip()]
    seen = set()
    deduped: List[str] = []
    for block in blocks:
        signature = re.sub(r"\s+", " ", block)
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(block)
    return deduped


def collect_rag_contexts(
    chatbot: ChatBot,
    question: str,
    role_type: str,
    user_id: int,
    conversation_id: int,
) -> List[str]:
    rag_chain = chatbot.rag_chain
    retrieval_query = rag_chain._build_retrieval_query(question, history_messages=None)

    blocks: List[str] = []
    pdf_context = rag_chain.retrieve_pdf_context(retrieval_query, role_type, top_k=4)
    public_context = rag_chain.retrieve_public_context(retrieval_query, role_type, top_k=3)
    private_context = rag_chain.retrieve_user_file_context(
        query=retrieval_query,
        user_id=user_id,
        conversation_id=conversation_id,
        top_k=4,
        include_other_conversations=False,
    )

    for context_text in (pdf_context, private_context, public_context):
        blocks.extend(split_context_text(context_text))

    if blocks:
        return blocks

    fallback_hits = chatbot.rag_chain.vector_store.search(question, role_type, top_k=3)
    return format_context_blocks(fallback_hits)


def export_eval_inputs(records: List[Dict[str, object]]) -> None:
    INPUT_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INPUT_EXPORT_PATH.open("w", encoding="utf-8") as file_obj:
        for record in records:
            file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_eval_dataset(rows: List[Dict[str, str]]) -> Dataset:
    chatbot = ChatBot()
    user_id = get_or_create_eval_user()
    records: List[Dict[str, object]] = []

    try:
        for index, row in enumerate(rows, start=1):
            role_type = (row.get("role_type") or "").strip()
            question = normalize_eval_text(row.get("question") or "")
            ground_truth = normalize_eval_text(row.get("ground_truth") or "")

            if not role_type or not question:
                raise ValueError(f"第 {index} 条测试数据缺少 role_type 或 question")

            conversation = chatbot.create_conversation(
                user_id=user_id,
                role_type=role_type,
                title="RAGAS评测",
            )

            contexts = collect_rag_contexts(
                chatbot=chatbot,
                question=question,
                role_type=role_type,
                user_id=user_id,
                conversation_id=conversation.id,
            )

            result = chatbot.chat(conversation.id, question)
            answer = normalize_eval_text(result.get("reply") or "")

            records.append(
                {
                    "question": question,
                    "answer": answer,
                    "contexts": contexts,
                    "ground_truth": ground_truth,
                    "role_type": role_type,
                }
            )
    finally:
        chatbot.close()

    export_eval_inputs(records)
    features = Features(
        {
            "question": Value("string"),
            "answer": Value("string"),
            "contexts": Sequence(Value("string")),
            "ground_truth": Value("string"),
            "role_type": Value("string"),
        }
    )
    return Dataset.from_list(records, features=features)


def resolve_judge_config() -> Dict[str, object]:
    llm_config = load_llm_config()
    api_base = os.getenv("RAGAS_API_BASE") or llm_config["api_base"]
    model_name = os.getenv("RAGAS_MODEL") or llm_config["model_name"]
    api_key = os.getenv("RAGAS_API_KEY") or llm_config["api_key"]
    temperature = float(os.getenv("RAGAS_TEMPERATURE") or 0)
    max_tokens = int(os.getenv("RAGAS_MAX_TOKENS") or 2048)

    if not api_key and is_non_openai_base(api_base):
        api_key = "placeholder-api-key"

    return {
        "api_base": api_base,
        "model_name": model_name,
        "api_key": api_key,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def build_judge_llm() -> LangchainLLMWrapper:
    judge_config = resolve_judge_config()
    chat_model_cls = DeepSeekCompatibleChatOpenAI if is_deepseek_base(str(judge_config["api_base"])) else ChatOpenAI
    chat_llm = chat_model_cls(
        model=judge_config["model_name"],
        base_url=judge_config["api_base"],
        api_key=judge_config["api_key"],
        temperature=judge_config["temperature"],
        max_tokens=judge_config["max_tokens"],
    )
    return LangchainLLMWrapper(chat_llm)


def resolve_embedding_model_path() -> Optional[Path]:
    env_path = os.getenv("EMBEDDING_MODEL_PATH", "").strip()
    candidates: List[Path] = []

    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(LINUX_EMBEDDING_CANDIDATES)
    candidates.append(WINDOWS_EMBEDDING_PATH)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_embeddings():
    model_path = resolve_embedding_model_path()
    if model_path is None:
        return None

    embeddings = HuggingFaceEmbeddings(model_name=str(model_path))
    return LangchainEmbeddingsWrapper(embeddings)


def call_ragas_evaluate(
    dataset: Dataset,
    metrics: List[Any],
    llm: LangchainLLMWrapper,
    embeddings: Optional[LangchainEmbeddingsWrapper],
    use_async: bool,
    max_workers: int,
):
    evaluate_kwargs: Dict[str, object] = {
        "dataset": dataset,
        "metrics": metrics,
        "llm": llm,
        "embeddings": embeddings,
        "raise_exceptions": False,
        "is_async": use_async,
        "run_config": RunConfig(timeout=180, max_workers=max_workers),
    }

    supported = inspect.signature(evaluate).parameters
    filtered_kwargs = {
        key: value
        for key, value in evaluate_kwargs.items()
        if key in supported and value is not None
    }
    return evaluate(**filtered_kwargs)


def result_to_csv(result: Any, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(result, "to_pandas"):
        dataframe = result.to_pandas()
    else:  # pragma: no cover - compatibility fallback
        import pandas as pd

        if isinstance(result, dict):
            dataframe = pd.DataFrame([result])
        else:
            dataframe = pd.DataFrame(result)
    dataframe.to_csv(output_path, index=False, encoding="utf-8-sig")


def main() -> None:
    init_database()
    testset_path = resolve_testset_path()
    rows = load_testset(testset_path)
    dataset = build_eval_dataset(rows)

    llm = build_judge_llm()
    use_async = str(os.getenv("RAGAS_ASYNC", "0")).strip().lower() in {"1", "true", "yes", "on"}
    metrics_mode = resolve_metrics_mode()
    max_workers = resolve_max_workers()

    metrics = [faithfulness, context_precision]
    embeddings = None
    if metrics_mode != "minimal":
        embeddings = build_embeddings()
        if embeddings is not None:
            metrics.append(answer_relevancy)

        if all((row.get("ground_truth") or "").strip() for row in rows):
            metrics.append(context_recall)

    result = call_ragas_evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        use_async=use_async,
        max_workers=max_workers,
    )

    result_to_csv(result, RESULT_PATH)


if __name__ == "__main__":
    main()
