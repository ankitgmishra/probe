"""
ProbeAI — Reflector agent.

Evaluates research progress and decides:
- Continue researching (with new queries)
- Stop (sufficient evidence)
- Declare unanswerable
"""

from __future__ import annotations

from models.schemas import (
    Evidence,
    ReflectionDecision,
    ReflectionResult,
    SubQuestion,
)
from services.evaluator import format_evidence_for_prompt, check_evidence_coverage
from utils import call_ollama_json, load_prompt, log
import config


def reflect(
    question: str,
    subquestions: list[SubQuestion],
    evidence: list[Evidence],
    current_iteration: int,
    total_sources: int,
) -> ReflectionResult:
    """
    Evaluate research progress and decide next action.
    """
    log.info(f"🤔 Reflecting on iteration {current_iteration}...")

    # Format inputs
    sq_text = "\n".join(
        f"- [{sq.id}] {'✅' if sq.answered else '❌'} {sq.question}"
        for sq in subquestions
    )
    evidence_summary = format_evidence_for_prompt(evidence)

    # Check per-claim evidence coverage
    coverage = check_evidence_coverage(
        evidence, subquestions, config.MIN_EVIDENCE_PER_CLAIM
    )

    # Build a coverage note for the LLM
    if coverage["under_covered"]:
        coverage_note = (
            f"MINIMUM EVIDENCE THRESHOLD: Each subquestion requires at least "
            f"{config.MIN_EVIDENCE_PER_CLAIM} pieces of evidence.\n"
            f"The following subquestions are UNDER-COVERED:\n"
        )
        for uc in coverage["under_covered"]:
            coverage_note += (
                f"  - [{uc['id']}] has {uc['count']}/{uc['needed']} evidence: "
                f"{uc['question']}\n"
            )
        coverage_note += (
            "Do NOT mark research as 'sufficient' until all subquestions "
            "meet this minimum threshold."
        )
    else:
        coverage_note = (
            f"MINIMUM EVIDENCE THRESHOLD: {config.MIN_EVIDENCE_PER_CLAIM} per subquestion — "
            f"ALL subquestions meet this threshold."
        )

    prompt_template = load_prompt("reflector_prompt.txt")
    prompt = (
        prompt_template
        .replace("{question}", question)
        .replace("{subquestions}", sq_text)
        .replace("{evidence_summary}", evidence_summary)
        .replace("{evidence_count}", str(len(evidence)))
        .replace("{current_iteration}", str(current_iteration))
        .replace("{max_iterations}", str(config.MAX_ITERATIONS))
        .replace("{total_sources}", str(total_sources))
        .replace("{max_sources}", str(config.MAX_SOURCES))
        .replace("{min_evidence_per_claim}", str(config.MIN_EVIDENCE_PER_CLAIM))
        .replace("{coverage_note}", coverage_note)
    )

    result = call_ollama_json(
        prompt=prompt,
        system="You are a research evaluation expert. Always respond with valid JSON only.",
    )

    # Parse decision
    decision_str = result.get("decision", "continue").lower()
    try:
        decision = ReflectionDecision(decision_str)
    except ValueError:
        decision = ReflectionDecision.CONTINUE

    # ── Enforce MIN_EVIDENCE_PER_CLAIM ─────────────────────────────
    # If the LLM says "sufficient" but subquestions are under-covered
    # and we still have iterations left, override to "continue".
    if (
        decision == ReflectionDecision.SUFFICIENT
        and not coverage["all_met"]
        and current_iteration < config.MAX_ITERATIONS
    ):
        log.warning(
            f"   ⚠ Overriding 'sufficient' → 'continue': "
            f"{len(coverage['under_covered'])} subquestions below "
            f"min evidence threshold ({config.MIN_EVIDENCE_PER_CLAIM})"
        )
        decision = ReflectionDecision.CONTINUE

        # Generate targeted queries for under-covered subquestions
        gap_queries = [
            f"{uc['question']}"
            for uc in coverage["under_covered"][:config.MAX_QUERIES_PER_ITERATION]
        ]
        # Merge with any LLM-suggested queries, deduplicating
        existing = result.get("new_search_queries", [])
        merged = list(dict.fromkeys(gap_queries + existing))
        result["new_search_queries"] = merged[:config.MAX_QUERIES_PER_ITERATION]

    reflection = ReflectionResult(
        decision=decision,
        coverage_summary=result.get("coverage_summary", ""),
        gaps=result.get("gaps", []),
        weak_claims=result.get("weak_claims", []),
        new_search_queries=result.get("new_search_queries", []),
        reasoning=result.get("reasoning", ""),
    )

    log.info(f"   → Decision: {reflection.decision.value}")
    if reflection.gaps:
        log.info(f"   → Gaps: {len(reflection.gaps)} identified")
    if reflection.new_search_queries:
        log.info(f"   → New queries: {reflection.new_search_queries}")

    return reflection
