class LightRAGError(Exception):
    """Base class for LightRAG sidecar errors."""


class LightRAGUnavailableError(LightRAGError):
    """Raised when the LightRAG sidecar cannot be reached."""

    def __init__(self, base_url: str) -> None:
        super().__init__(
            f"LightRAG Server unavailable ({base_url}). "
            "Please start the sidecar or switch retrieval_mode to hybrid/fulltext/vector/keyword."
        )


class LightRAGQueryError(LightRAGError):
    """Raised when a LightRAG query request fails."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"LightRAG query failed: {detail}. Try retrieval_mode=hybrid.")


class LightRAGInsertError(LightRAGError):
    """Raised when graph-building insertion fails."""

    def __init__(self, file_id: str, detail: str) -> None:
        super().__init__(f"LightRAG insert failed [{file_id}]: {detail}")


class LightRAGConfigError(LightRAGError):
    """Raised when LightRAG configuration is invalid."""
