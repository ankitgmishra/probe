"""
ProbeAI — Pydantic schemas for all data structures.

Every piece of data flowing through the system is typed here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────

class EvidenceStrength(str, Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    SPECULATIVE = "speculative"


class ReflectionDecision(str, Enum):
    CONTINUE = "continue"           # more research needed
    SUFFICIENT = "sufficient"       # enough evidence collected
    UNANSWERABLE = "unanswerable"   # question cannot be answered


# ── Core Data Models ───────────────────────────────────────────────

class SubQuestion(BaseModel):
    """A single sub-question derived from the main research question."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    question: str
    priority: int = Field(default=1, ge=1, le=5, description="1=highest priority")
    answered: bool = False


class ResearchPlan(BaseModel):
    """Output of the Planner agent."""
    main_question: str
    subquestions: list[SubQuestion]
    initial_search_queries: list[str]
    reasoning: str


class SearchResult(BaseModel):
    """A single search result from Tavily."""
    title: str
    url: str
    snippet: str
    score: float = 0.0
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Evidence(BaseModel):
    """A single piece of extracted evidence."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    claim: str = ""
    source_url: str = ""
    source_title: Optional[str] = None
    quote: Optional[str] = None
    date_mentioned: Optional[str] = None
    strength: EvidenceStrength = EvidenceStrength.MODERATE
    subquestion_id: Optional[str] = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReflectionResult(BaseModel):
    """Output of the Reflector agent."""
    decision: ReflectionDecision
    coverage_summary: str
    gaps: list[str] = Field(default_factory=list)
    weak_claims: list[str] = Field(default_factory=list)
    new_search_queries: list[str] = Field(default_factory=list)
    reasoning: str


class IterationSummary(BaseModel):
    """Summary of a single research iteration."""
    iteration: int
    queries_used: list[str]
    sources_found: int
    evidence_extracted: int
    reflection_decision: ReflectionDecision
    gaps_identified: list[str]
    duration_seconds: float


class FinalReport(BaseModel):
    """The synthesized research report."""
    title: str
    executive_summary: str
    key_findings: list[str]
    evidence_table: list[Evidence]
    strong_evidence: list[str]
    weak_evidence: list[str]
    open_questions: list[str]
    sources: list[str]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Run State ──────────────────────────────────────────────────────

class RunState(BaseModel):
    """
    Complete state of a research run.
    Persisted to JSON after every iteration for inspectability.
    """
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    question: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None

    # Agent outputs
    plan: Optional[ResearchPlan] = None
    all_search_results: list[SearchResult] = Field(default_factory=list)
    all_evidence: list[Evidence] = Field(default_factory=list)
    reflections: list[ReflectionResult] = Field(default_factory=list)
    iteration_summaries: list[IterationSummary] = Field(default_factory=list)
    report: Optional[FinalReport] = None

    # Tracking
    current_iteration: int = 0
    total_sources: int = 0
    queries_log: list[str] = Field(default_factory=list)
    stop_reason: Optional[str] = None
