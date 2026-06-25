import os
import socket

# 修复 Torch + sentence-transformers OpenMP DLL 冲突
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import uvicorn  # noqa: E402


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PORT_SEARCH_LIMIT = 20


def _find_available_port(host: str, preferred_port: int, attempts: int = PORT_SEARCH_LIMIT) -> int:
    """Return the first bindable port, starting from the preferred port."""
    for port in range(preferred_port, preferred_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
        return port
    raise RuntimeError(
        f"No available port found in range {preferred_port}-{preferred_port + attempts - 1}."
    )


if __name__ == "__main__":
    host = os.getenv("HOST", DEFAULT_HOST)
    preferred_port = int(os.getenv("PORT", str(DEFAULT_PORT)))
    reload_enabled = os.getenv("RELOAD", "false").lower() in {"1", "true", "yes", "on"}

    port = _find_available_port(host, preferred_port)
    if port != preferred_port:
        print(f"Port {preferred_port} is unavailable, starting this server on http://{host}:{port}")

    uvicorn.run("app.main:app", host=host, port=port, reload=reload_enabled)
