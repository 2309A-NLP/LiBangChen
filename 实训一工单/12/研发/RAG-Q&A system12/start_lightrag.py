"""Launch LightRAG server with the project's configuration."""
import sys
import os

# On Windows, fix Unicode encoding so LightRAG splash screen emojis don't crash
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# On Windows, use SelectorEventLoop to avoid uvicorn binding issues
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ── Load LightRAG .env BEFORE importing LightRAG ──
# LightRAG calls load_dotenv(dotenv_path=".env") at import time, reading from CWD.
# We need our SiliconFlow config loaded into os.environ before that import happens.
from dotenv import load_dotenv
_project_root = os.path.dirname(os.path.abspath(__file__))
_lightrag_env = os.path.join(_project_root, "data", "lightrag", ".env")
load_dotenv(dotenv_path=_lightrag_env, override=True)

# Set working dir so LightRAG puts its data in the right place
os.environ["WORKING_DIR"] = os.path.join(_project_root, "data", "lightrag")
os.chdir(_project_root)

# Patch sys.argv so LightRAG's arg parser picks up our args
sys.argv = [
    "lightrag",
    "--working-dir", os.path.join(_project_root, "data", "lightrag"),
    "--host", "127.0.0.1",
    "--port", "9621",
]

# Now safe to import — LightRAG will see the SiliconFlow env vars
from lightrag.api.lightrag_server import main
main()
