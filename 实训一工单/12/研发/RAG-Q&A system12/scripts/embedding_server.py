"""
Minimal OpenAI-compatible embedding server using local bge-m3.

Usage:
    python scripts/embedding_server.py --port 9622

LightRAG Server then uses:
    --embedding-binding openai
    --embedding-binding-host http://localhost:9622/v1
    --embedding-binding-api-key not-needed
    --embedding-model BAAI/bge-m3
"""

import argparse
import logging
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("embedding_server")


# ── Lifespan: load model once ──────────────────────────────

embedding_model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global embedding_model
    from sentence_transformers import SentenceTransformer

    logger.info("Loading bge-m3 embedding model ...")
    t0 = time.perf_counter()
    embedding_model = SentenceTransformer(
        app.state.model_path,
        device=app.state.device,
    )
    elapsed = time.perf_counter() - t0
    logger.info("bge-m3 loaded in %.1f s on %s", elapsed, app.state.device)
    yield
    embedding_model = None


# ── Pydantic schemas ───────────────────────────────────────

class EmbeddingRequest(BaseModel):
    input: str | list[str] = Field(...)
    model: str = "bge-m3"


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float]


class Usage(BaseModel):
    prompt_tokens: int = 0
    total_tokens: int = 0


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[EmbeddingData]
    model: str
    usage: Usage = Usage()


# ── App ────────────────────────────────────────────────────

app = FastAPI(title="bge-m3 Embedding Server", lifespan=lifespan)


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest, raw: Request):
    global embedding_model
    if embedding_model is None:
        return JSONResponse({"error": "model not loaded"}, status_code=503)

    texts = [request.input] if isinstance(request.input, str) else request.input
    vectors = embedding_model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    data = [
        EmbeddingData(index=i, embedding=vec.tolist())
        for i, vec in enumerate(vectors)
    ]
    return EmbeddingResponse(
        data=data,
        model=request.model,
        usage=Usage(prompt_tokens=sum(len(t) for t in texts)),
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": embedding_model is not None}


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9622)
    parser.add_argument(
        "--model-path",
        default=r"C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-m3",
    )
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    app.state.model_path = args.model_path
    app.state.device = args.device

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
