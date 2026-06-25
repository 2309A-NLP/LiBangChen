import os

import uvicorn


def _is_reload_enabled() -> bool:
    return os.getenv("UVICORN_RELOAD", "").strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=_is_reload_enabled(),
    )
