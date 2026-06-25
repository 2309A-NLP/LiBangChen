from enum import StrEnum


class RetrievalMode(StrEnum):
    HYBRID = "hybrid"
    FULLTEXT = "fulltext"
    VECTOR = "vector"
    KEYWORD = "keyword"
    LIGHTRAG_MIX = "lightrag_mix"
    LIGHTRAG_LOCAL = "lightrag_local"
    LIGHTRAG_GLOBAL = "lightrag_global"
    LIGHTRAG_HYBRID = "lightrag_hybrid"


LIGHTRAG_MODES = frozenset(
    {
        RetrievalMode.LIGHTRAG_MIX,
        RetrievalMode.LIGHTRAG_LOCAL,
        RetrievalMode.LIGHTRAG_GLOBAL,
        RetrievalMode.LIGHTRAG_HYBRID,
    }
)

DEFAULT_RETRIEVAL_MODE = RetrievalMode.HYBRID
