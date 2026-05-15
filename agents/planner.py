"""
ProbeAI — Planner agent.

Takes a research question and produces:
- Sub-questions
- Initial search queries
- Research strategy reasoning
"""

from __future__ import annotations

from models.schemas import ResearchPlan, SubQuestion
from utils import call_ollama_json, load_prompt, log


def plan_research(question: str) -> ResearchPlan:
    """
    Break a research question into sub-questions and initial search queries.
    """
    log.info(f"📋 Planning research for: {question}")

    prompt_template = load_prompt("planner_prompt.txt")
    prompt = prompt_template.replace("{question}", question)

    result = call_ollama_json(
        prompt=prompt,
        system="You are a research planning expert. Always respond with valid JSON only.",
    )

    # Parse sub-questions
    subquestions = []
    for sq in result.get("subquestions", []):
        subquestions.append(
            SubQuestion(
                question=sq.get("question", ""),
                priority=sq.get("priority", 3),
            )
        )

    # Sort by priority (1 = highest)
    subquestions.sort(key=lambda sq: sq.priority)

    plan = ResearchPlan(
        main_question=question,
        subquestions=subquestions,
        initial_search_queries=result.get("initial_search_queries", []),
        reasoning=result.get("reasoning", "No reasoning provided."),
    )

    log.info(f"   → {len(plan.subquestions)} sub-questions, {len(plan.initial_search_queries)} queries")
    for sq in plan.subquestions:
        log.info(f"   → [P{sq.priority}] {sq.question}")

    return plan
