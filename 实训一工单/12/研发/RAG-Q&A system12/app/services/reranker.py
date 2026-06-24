"""重排序服务模块。"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace
import json
import logging
import math
from pathlib import Path
import re
import socket
from urllib import error, request

from app.services.retrievers.base import RetrievedChunk

logger = logging.getLogger(__name__)

_MIN_SAFE_TORCH_LOAD_VERSION = (2, 6)
_UNSAFE_TORCH_WEIGHT_SUFFIXES = {".bin", ".pt", ".pth", ".ckpt"}


def _parse_major_minor(version: object) -> tuple[int, int] | None:
    match = re.match(r"^\s*(\d+)\.(\d+)", str(version))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _is_safe_torch_load_version(version: object) -> bool:
    parsed = _parse_major_minor(version)
    return parsed is not None and parsed >= _MIN_SAFE_TORCH_LOAD_VERSION


def _uses_safetensors_only(model_path: str) -> bool:
    path = Path(model_path).expanduser()
    if path.is_file():
        return path.suffix.lower() == ".safetensors"
    if not path.is_dir():
        return False

    has_safetensors = False
    for candidate in path.rglob("*"):
        if not candidate.is_file():
            continue
        suffix = candidate.suffix.lower()
        if suffix == ".safetensors":
            has_safetensors = True
        if suffix in _UNSAFE_TORCH_WEIGHT_SUFFIXES:
            return False
    return has_safetensors


def _ensure_safe_torch_model_loading(torch_module: object, model_path: str) -> None:
    if _is_safe_torch_load_version(getattr(torch_module, "__version__", "")):
        return
    if _uses_safetensors_only(model_path):
        return

    raise RuntimeError(
        "PyTorch >=2.6 is required when loading non-safetensors model weights "
        "because CVE-2025-32434 affects torch.load, including weights_only=True. "
        "Upgrade torch or provide a safetensors-only model path."
    )


class BaseChunkReranker:
    name = "base"

    def rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        raise NotImplementedError


class CrossEncoderReranker(BaseChunkReranker):
    """Cross-encoder reranker using bge-reranker-base."""

    name = "cross_encoder"

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        max_length: int = 512,
        top_n: int | None = None,
    ) -> None:
        self.model_path = model_path
        self.device = device
        self.max_length = max_length
        self.top_n = top_n
        self._model = None
        self._tokenizer = None

    def _load_model(self) -> None:
        if self._model is not None:
            return

        logger.info("Loading reranker model from %s", self.model_path)
        import torch

        _ensure_safe_torch_model_loading(torch, self.model_path)
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_path)
        self._model.to(self.device)
        self._model.eval()
        logger.info("Reranker model loaded successfully on %s", self.device)

    def rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        self._load_model()
        pairs = [(question, chunk.chunk.text) for chunk in chunks]

        import torch

        scores = []
        batch_size = 32
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            inputs = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits.squeeze(-1)
                batch_scores = logits.cpu().tolist()
                if isinstance(batch_scores, float):
                    batch_scores = [batch_scores]
                scores.extend(batch_scores)

        reranked = []
        for chunk, score in zip(chunks, scores):
            reranked.append(
                RetrievedChunk(
                    chunk=chunk.chunk,
                    score=round(float(score), 4),
                    metadata={
                        **chunk.metadata,
                        "reranker": self.name,
                        "cross_encoder_score": round(float(score), 4),
                    },
                )
            )

        reranked.sort(key=lambda item: item.score, reverse=True)
        limit = top_n if top_n is not None else self.top_n
        return reranked[:limit] if limit else reranked


class TFIDFReranker(BaseChunkReranker):
    name = "tfidf"

    def rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        question_terms = self._tokenize(question)
        if not question_terms:
            return chunks[:top_n] if top_n else chunks

        candidate_term_sets = [
            Counter(self._tokenize(f"{item.chunk.source_id} {item.chunk.text}"))
            for item in chunks
        ]
        doc_freq = Counter()
        for terms in candidate_term_sets:
            doc_freq.update(terms.keys())

        reranked = []
        total_docs = max(len(chunks), 1)
        query_counts = Counter(question_terms)
        for item, chunk_terms in zip(chunks, candidate_term_sets):
            numerator = 0.0
            doc_norm = 0.0
            query_norm = 0.0
            for term, query_tf in query_counts.items():
                idf = math.log(1 + total_docs / max(doc_freq.get(term, 1), 1))
                chunk_tf = chunk_terms.get(term, 0)
                numerator += query_tf * chunk_tf * idf * idf
                query_norm += (query_tf * idf) ** 2
            for term, chunk_tf in chunk_terms.items():
                idf = math.log(1 + total_docs / max(doc_freq.get(term, 1), 1))
                doc_norm += (chunk_tf * idf) ** 2
            tfidf_score = numerator / max(math.sqrt(query_norm) * math.sqrt(doc_norm), 1e-6)
            reranked.append(
                RetrievedChunk(
                    chunk=item.chunk,
                    score=round(tfidf_score, 6),
                    metadata={
                        **item.metadata,
                        "reranker": self.name,
                        "tfidf_score": round(tfidf_score, 6),
                    },
                )
            )

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_n] if top_n else reranked

    def _tokenize(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", "", text).lower()
        if not normalized:
            return []
        raw_tokens = [
            token
            for token in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", normalized)
            if token
        ]
        tokens: list[str] = []
        for token in raw_tokens:
            if len(token) >= 2:
                tokens.append(token)
            if re.search(r"[\u4e00-\u9fff]", token):
                for size in (2, 3):
                    if len(token) < size:
                        continue
                    for index in range(0, len(token) - size + 1):
                        tokens.append(token[index : index + size])
        return tokens


class FeedbackAdaptiveReranker(BaseChunkReranker):
    name = "feedback"

    def __init__(self, store_path: Path, positive_rating_threshold: int = 4) -> None:
        self.store_path = store_path
        self.positive_rating_threshold = positive_rating_threshold
        self._profile_signature: tuple[int, float] | None = None
        self._term_weights: dict[str, float] = {}

    def rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        self._ensure_profile()

        question_terms = set(self._tokenize(question))
        reranked = []
        for item in chunks:
            chunk_terms = set(self._tokenize(f"{item.chunk.source_id} {item.chunk.text}"))
            adaptive_score = 0.0
            for term in question_terms & chunk_terms:
                adaptive_score += self._term_weights.get(term, 0.0)
            for term in chunk_terms:
                adaptive_score += self._term_weights.get(term, 0.0) * 0.05
            combined_score = item.score + adaptive_score
            reranked.append(
                RetrievedChunk(
                    chunk=item.chunk,
                    score=round(combined_score, 6),
                    metadata={
                        **item.metadata,
                        "reranker": self.name,
                        "feedback_delta": round(adaptive_score, 6),
                    },
                )
            )
        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked[:top_n] if top_n else reranked

    def _ensure_profile(self) -> None:
        if not self.store_path.exists():
            self._term_weights = {}
            self._profile_signature = None
            return

        stat = self.store_path.stat()
        signature = (stat.st_size, stat.st_mtime)
        if signature == self._profile_signature:
            return

        weights: dict[str, float] = {}
        try:
            records = self.store_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            records = []

        for line in records:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            rating = payload.get("rating")
            question = payload.get("question", "")
            comment = payload.get("comment", "")
            if not isinstance(rating, int):
                continue
            signal = 1.0 if rating >= self.positive_rating_threshold else -0.4
            for term in self._tokenize(f"{question} {comment}"):
                weights[term] = weights.get(term, 0.0) + signal

        self._term_weights = weights
        self._profile_signature = signature

    def _tokenize(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", "", text).lower()
        if not normalized:
            return []
        raw_tokens = [
            token
            for token in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", normalized)
            if token
        ]
        tokens: list[str] = []
        for token in raw_tokens:
            if len(token) >= 2:
                tokens.append(token)
            if re.search(r"[\u4e00-\u9fff]", token):
                for size in (2, 3, 4):
                    if len(token) < size:
                        continue
                    for index in range(0, len(token) - size + 1):
                        tokens.append(token[index : index + size])
        return tokens


class LLMReranker(BaseChunkReranker):
    name = "llm"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        if self.api_key and self.base_url and self.model:
            try:
                return self._remote_rerank(question, chunks, top_n)
            except Exception:
                logger.warning("LLM reranker failed, falling back to heuristic scoring.", exc_info=True)
        return self._fallback_rerank(question, chunks, top_n)

    def _remote_rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None,
    ) -> list[RetrievedChunk]:
        prompt_lines = [
            "You are a reranker for retrieved document passages.",
            "Return a JSON object with a single key `scores`, whose value is a list of objects.",
            '{"scores":[{"chunk_id":"...", "score": 0-100}]}',
            f"Question: {question}",
            "Passages:",
        ]
        for item in chunks:
            prompt_lines.append(
                json.dumps(
                    {
                        "chunk_id": item.chunk.chunk_id,
                        "source_id": item.chunk.source_id,
                        "page_number": item.chunk.page_number,
                        "text": item.chunk.text[:480],
                    },
                    ensure_ascii=False,
                )
            )

        payload = {
            "model": self.model,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": "\n".join(prompt_lines)},
            ],
        }
        endpoint = f"{self.base_url}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        req = request.Request(endpoint, data=body, headers=headers, method="POST")

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM reranker HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"LLM reranker connection failed: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError("LLM reranker timed out.") from exc

        parsed = json.loads(raw)
        choices = parsed.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("LLM reranker response is missing choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
            )
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM reranker response does not contain content.")
        score_payload = json.loads(content)
        items = score_payload.get("scores", [])
        if not isinstance(items, list):
            raise RuntimeError("LLM reranker JSON schema is invalid.")

        score_map = {
            str(item.get("chunk_id")): float(item.get("score"))
            for item in items
            if isinstance(item, dict) and item.get("chunk_id") is not None and item.get("score") is not None
        }

        reranked = []
        for item in chunks:
            llm_score = score_map.get(item.chunk.chunk_id, 0.0)
            reranked.append(
                RetrievedChunk(
                    chunk=item.chunk,
                    score=round(llm_score, 6),
                    metadata={
                        **item.metadata,
                        "reranker": self.name,
                        "llm_score": round(llm_score, 6),
                    },
                )
            )
        reranked.sort(key=lambda entry: entry.score, reverse=True)
        return reranked[:top_n] if top_n else reranked

    def _fallback_rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None,
    ) -> list[RetrievedChunk]:
        question_terms = set(self._tokenize(question))
        compact_question = question.replace(" ", "")
        reranked = []
        for item in chunks:
            chunk_text = f"{item.chunk.source_id} {item.chunk.text}"
            chunk_terms = set(self._tokenize(chunk_text))
            overlap = len(question_terms & chunk_terms)
            phrase_bonus = 2.0 if compact_question and compact_question[:12] in chunk_text.replace(" ", "") else 0.0
            score = overlap * 1.5 + phrase_bonus + item.score * 0.05
            reranked.append(
                RetrievedChunk(
                    chunk=item.chunk,
                    score=round(score, 6),
                    metadata={
                        **item.metadata,
                        "reranker": self.name,
                        "llm_mode": "heuristic_fallback",
                        "llm_score": round(score, 6),
                    },
                )
            )
        reranked.sort(key=lambda entry: entry.score, reverse=True)
        return reranked[:top_n] if top_n else reranked

    def _tokenize(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", "", text).lower()
        if not normalized:
            return []
        return [
            token
            for token in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", normalized)
            if len(token) >= 2
        ]


class RerankerService:
    """可组合的重排服务。"""

    def __init__(self, rerankers: list[BaseChunkReranker], top_n: int | None = None) -> None:
        self.rerankers = rerankers
        self.top_n = top_n

    @property
    def strategy_names(self) -> list[str]:
        return [reranker.name for reranker in self.rerankers]

    def rerank(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []

        reranked = [replace(item, metadata=dict(item.metadata)) for item in chunks]
        limit = top_n if top_n is not None else self.top_n
        for reranker in self.rerankers:
            reranked = reranker.rerank(question=question, chunks=reranked, top_n=None)
        return reranked[:limit] if limit else reranked

    def clone_with_strategy_names(
        self,
        strategy_names: list[str],
        available_rerankers: dict[str, BaseChunkReranker],
    ) -> "RerankerService":
        rerankers: list[BaseChunkReranker] = []
        for name in strategy_names:
            normalized = name.strip().lower()
            if not normalized:
                continue
            reranker = available_rerankers.get(normalized)
            if reranker is not None:
                rerankers.append(reranker)
        return RerankerService(rerankers=rerankers, top_n=self.top_n)
