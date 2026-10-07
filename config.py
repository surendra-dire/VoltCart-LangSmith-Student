"""Student settings. Edit this file, save it, and restart the server.

No environment variables or api_credentials.json are needed.
Keep your edited copy private: this file will contain your personal API keys.
"""
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

# 1. Model connection: use the values supplied by your instructor.

OPENAI_API_KEY = "ollama"  # Ollama does not require a real key, but OpenAI SDK expects a non-empty string
OPENAI_BASE_URL = "http://localhost:11434/v1"  # Ollama's local OpenAI-compatible endpoint
OPENAI_MODEL = "qwen2.5:1.5b"  # Or any model name you have downloaded in Ollama (e.g., mistral, gemma, phi3)
OPENAI_API_MODE = "chat_completions"
OPENAI_AUTH_HEADER = "Authorization"  # Standard Bearer auth header


# 2. LangSmith: paste your separate LangSmith key, then enable tracing.
LANGSMITH_ENABLED = False
LANGSMITH_API_KEY = "PASTE_YOUR_LANGSMITH_API_KEY_HERE"
LANGSMITH_PROJECT = "voltcart-student-demo"  # Choose your own project name
LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
# EU workspaces: https://eu.api.smith.langchain.com
LANGSMITH_WORKSPACE_ID = ""  # Optional; needed for keys scoped to multiple workspaces

# True sends prompts, replies and tool results to your LangSmith workspace.
# False keeps timing/metadata but omits input/output content.
LANGSMITH_CAPTURE_CONTENT = True

# Remaining classroom defaults normally do not need changing.
OPENAI_TIMEOUT_SECONDS = 180

# Chat request settings based on the supplied working Postman request.
OPENAI_CHAT_MAX_TOKENS = 384
OPENAI_CHAT_TEMPERATURE = 0.2
OPENAI_CHAT_TOP_P = 0.9
OPENAI_CHAT_SEED = 42

# Retained only for the optional Responses API implementation.
OPENAI_REASONING_EFFORT = "low"

# If the key is missing or the remote API is unavailable, the site uses a small
# deterministic local agent. This keeps the classroom demo fully runnable.
ENABLE_LOCAL_FALLBACK = True
MAX_AGENT_TOOL_ROUNDS = 6

# Human-in-the-loop and post-delivery demo policies.
PURCHASE_APPROVAL_THRESHOLD = 50_000
APPROVAL_TTL_MINUTES = 15
MAX_BUNDLE_PRODUCTS = 5
RETURN_WINDOW_DAYS = 7


# ---------------------------------------------------------------------------
# Local web app
# ---------------------------------------------------------------------------
APP_NAME = "VoltCart"
HOST = "127.0.0.1"
PORT = 8000

DEMO_USER = {
    "id": "USR-1001",
    "name": "Aarav Sharma",
    "first_name": "Aarav",
    "email": "aarav@example.test",
    "address": "42 Learning Lane, Bengaluru 560001",
    "payment_method": "Demo cash on delivery",
}

STATIC_DIR = ROOT_DIR / "static"
DATA_DIR = ROOT_DIR / "data"
DB_FILE = DATA_DIR / "voltcart.db"
# Backwards-compatible name used by OrderStore and older teaching material.
ORDERS_FILE = DB_FILE


def openai_is_configured() -> bool:
    """Return True only when the classroom placeholder was replaced."""

    key = OPENAI_API_KEY.strip()
    url = OPENAI_BASE_URL.strip()
    return bool(
        key
        and not key.startswith("PASTE_")
        and "YOUR_API_KEY" not in key
        and url
        and "YOUR-AZURE-RESOURCE" not in url
    )
