from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LightRAGQueryMode(StrEnum):
    LOCAL = "local"
    GLOBAL = "global"
    HYBRID = "hybrid"
    MIX = "mix"


class LightRAGInsertRequest(BaseModel):
    text: str = Field(..., min_length=1)
    file_id: str = Field(..., min_length=1)
    entity_types: list[str] | None = None
    relation_types: list[str] | None = None


class LightRAGQueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    mode: LightRAGQueryMode = LightRAGQueryMode.MIX
    top_k: int = Field(default=20, ge=1, le=100)
    file_ids: list[str] | None = None
    include_references: bool = True


class LightRAGChunk(BaseModel):
    chunk_id: str
    content: str
    score: float = 0.0
    file_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LightRAGQueryResponse(BaseModel):
    query: str = ""
    mode: LightRAGQueryMode = LightRAGQueryMode.MIX
    answer: str | None = None
    chunks: list[LightRAGChunk] = Field(default_factory=list)
    total_tokens: int = 0


class IndexStatus(BaseModel):
    working_dir: str
    total_documents: int = 0
    total_chunks: int = 0
    total_entities: int = 0
    total_relations: int = 0
    last_indexed_at: str | None = None
    errors: list[str] = Field(default_factory=list)
