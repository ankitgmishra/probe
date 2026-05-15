"""
ProbeAI — Utilities.

Ollama client, JSON persistence, prompt loading, and logging.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

import config

# ── Logging Setup ──────────────────────────────────────────────────

def setup_logger(name: str = "probeai") -> logging.Logger:
    """Create a configured logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))
    return logger


log = setup_logger()


# ── Ollama Client ──────────────────────────────────────────────────

# ── Ollama Client ──────────────────────────────────────────────────

def call_ollama(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    max_retries: int = 2,
) -> str:
    """
    Call Ollama's /api/generate endpoint.
    Returns the raw text response.
    """

    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }

    if system:
        payload["system"] = system

    url = f"{config.OLLAMA_BASE_URL}/api/generate"

    for attempt in range(max_retries + 1):
        try:
            log.debug(f"Ollama call (attempt {attempt + 1}): {prompt[:80]}...")

            resp = requests.post(
                url,
                json=payload,
                timeout=120,
            )

            # Temporary debugging
            print("STATUS:", resp.status_code)
            print("RESPONSE:", resp.text[:500])

            resp.raise_for_status()

            data = resp.json()

            return data.get("response", "")

        except requests.exceptions.RequestException as e:
            log.warning(f"Ollama request failed (attempt {attempt + 1}): {e}")

            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                raise RuntimeError(
                    f"Ollama unreachable after {max_retries + 1} attempts: {e}"
                )

    return ""

def call_ollama_json(
    prompt: str,
    system: str = "",
    temperature: float = 0.2,
) -> dict:
    """
    Call Ollama and parse the response as JSON.
    Attempts to extract JSON from the response even if wrapped in markdown.
    """
    raw = call_ollama(prompt, system=system, temperature=temperature)
    return parse_json_response(raw)


# ── JSON Parsing ───────────────────────────────────────────────────

def _ensure_list(val: any) -> list:
    """
    Ensure a value is a list.
    Handles comma-separated strings or existing lists.
    """
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        if not val.strip():
            return []
        # Handle "[id1], [id2]" or "query1, query2"
        items = [i.strip().strip("'\"[]") for i in val.split(",")]
        return [i for i in items if i]
    return []


def _ensure_dict(parsed: any) -> dict:
    """
    Ensure the parsed JSON is a dict.
    If the LLM returned a bare list, wrap it as {"evidence": [...]}.
    Also coerces common list fields that LLMs often get wrong.
    """
    if not isinstance(parsed, dict):
        if isinstance(parsed, list):
            log.warning("LLM returned a JSON array instead of object — wrapping as {'evidence': [...]}")
            return {"evidence": parsed}
        return {}

    # Self-heal common list fields
    list_fields = ["gaps", "weak_claims", "new_search_queries", "key_findings", "sources", "subquestions", "initial_search_queries"]
    for field in list_fields:
        if field in parsed and not isinstance(parsed[field], list):
            log.warning(f"Coercing '{field}' from {type(parsed[field]).__name__} to list")
            parsed[field] = _ensure_list(parsed[field])

    return parsed


def parse_json_response(text: str) -> dict:
    """
    Extract and parse JSON from LLM output.
    Handles markdown code fences, bare arrays, and other wrapping.
    """
    # Try direct parse first
    try:
        parsed = json.loads(text)
        return _ensure_dict(parsed)
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences or bare JSON
    patterns = [
        r"```json\s*\n(.*?)\n\s*```",
        r"```\s*\n(.*?)\n\s*```",
        r"\{.*\}",
        r"\[.*\]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                candidate = match.group(1) if match.lastindex else match.group(0)
                parsed = json.loads(candidate)
                return _ensure_dict(parsed)
            except (json.JSONDecodeError, IndexError):
                continue

    log.error(f"Failed to parse JSON from response: {text[:200]}...")
    return {}


# ── Prompt Loading ─────────────────────────────────────────────────

def load_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    path = config.PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


# ── JSON Persistence ──────────────────────────────────────────────

def save_run_state(state: Any, run_dir: Path) -> Path:
    """Save RunState to a JSON file in the run directory."""
    run_dir.mkdir(parents=True, exist_ok=True)
    filepath = run_dir / "state.json"
    filepath.write_text(
        state.model_dump_json(indent=2),
        encoding="utf-8",
    )
    log.info(f"State saved → {filepath}")
    return filepath


def save_report(report_text: str, run_dir: Path) -> Path:
    """Save the final report as a markdown file."""
    run_dir.mkdir(parents=True, exist_ok=True)
    filepath = run_dir / "report.md"
    filepath.write_text(report_text, encoding="utf-8")
    log.info(f"Report saved → {filepath}")
    return filepath


def save_evals(evals: dict, run_dir: Path) -> Path:
    """Save the evaluation metrics as a JSON file."""
    run_dir.mkdir(parents=True, exist_ok=True)
    filepath = run_dir / "evals.json"
    filepath.write_text(
        json.dumps(evals, indent=2, default=str),
        encoding="utf-8",
    )
    log.info(f"Evals saved → {filepath}")
    return filepath


# ── Timing ─────────────────────────────────────────────────────────

class Timer:
    """Simple context-manager timer."""

    def __init__(self):
        self.start_time = 0.0
        self.elapsed = 0.0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, *args):
        self.elapsed = time.time() - self.start_time

    @property
    def seconds(self) -> float:
        return round(self.elapsed, 2)
