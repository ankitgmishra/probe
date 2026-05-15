"""
ProbeAI — Configuration.

All configurable limits and settings live here.
Adjust these to control research depth, speed, and cost.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
RUNS_DIR = PROJECT_ROOT / "runs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

# ── API Keys ───────────────────────────────────────────────────────

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# ── Ollama Settings ────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

# ── Research Limits ────────────────────────────────────────────────

MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "3"))
MAX_SOURCES = int(os.getenv("MAX_SOURCES", "20"))
MAX_RUNTIME_SECONDS = int(os.getenv("MAX_RUNTIME_SECONDS", "300"))
MIN_EVIDENCE_PER_CLAIM = int(os.getenv("MIN_EVIDENCE_PER_CLAIM", "2"))

# ── Search Settings ────────────────────────────────────────────────

SEARCH_RESULTS_PER_QUERY = 5
MAX_QUERIES_PER_ITERATION = 3
EXTRACTION_BATCH_SIZE = 2

# ── Logging ────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
