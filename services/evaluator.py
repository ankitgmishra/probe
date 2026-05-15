"""
ProbeAI — Evaluation & observability module.

Heuristic-based, deterministic metrics for research quality assessment.
No LLM judging. No external frameworks. Just straightforward scoring.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from models.schemas import (
    Evidence,
    EvidenceStrength,
    FinalReport,
    ReflectionDecision,
    RunState,
    SubQuestion,
)
from utils import log


# ── Constants ──────────────────────────────────────────────────────

STRENGTH_WEIGHTS = {
    EvidenceStrength.STRONG: 1.0,
    EvidenceStrength.MODERATE: 0.7,
    EvidenceStrength.WEAK: 0.3,
    EvidenceStrength.SPECULATIVE: 0.1,
}

HIGH_AUTHORITY_DOMAINS = [
    ".gov", ".edu", "nature.com", "science.org", "arxiv.org",
    "openai.com", "anthropic.com", "google.com", "microsoft.com",
    "ieee.org", "acm.org", "who.int", "nih.gov", "nist.gov",
]

MEDIUM_AUTHORITY_DOMAINS = [
    "techcrunch.com", "arstechnica.com", "theverge.com", "wired.com",
    "medium.com", "substack.com", "bloomberg.com", "reuters.com",
    "nytimes.com", "washingtonpost.com", "bbc.com", "wikipedia.org",
    "stackoverflow.com", "github.com",
]

LOW_AUTHORITY_DOMAINS = [
    "reddit.com", "linkedin.com", "twitter.com", "x.com",
    "facebook.com", "quora.com", "forum", "forums",
]

HEDGING_PHRASES = [
    "uncertain", "unclear", "limited evidence", "speculative",
    "likely", "unlikely", "appears to", "suggests", "may",
    "might", "could", "possibly", "preliminary", "tentative",
    "insufficient", "inconclusive", "conflicting", "mixed evidence",
    "not enough data", "further research", "remains to be seen",
]

# ── Existing functions (preserved) ─────────────────────────────────

def evaluate_evidence(evidence_list: list[Evidence]) -> dict:
    """
    Evaluate and summarize the quality of collected evidence.
    Returns a summary dict with counts and quality metrics.
    """
    if not evidence_list:
        return {
            "total": 0,
            "strong": 0,
            "moderate": 0,
            "weak": 0,
            "speculative": 0,
            "unique_sources": 0,
            "quality_score": 0.0,
        }

    strength_counts = {
        EvidenceStrength.STRONG: 0,
        EvidenceStrength.MODERATE: 0,
        EvidenceStrength.WEAK: 0,
        EvidenceStrength.SPECULATIVE: 0,
    }

    for e in evidence_list:
        strength_counts[e.strength] = strength_counts.get(e.strength, 0) + 1

    unique_sources = len(set(e.source_url for e in evidence_list))

    weights = STRENGTH_WEIGHTS
    total_weight = sum(weights[e.strength] for e in evidence_list)
    quality_score = round(total_weight / len(evidence_list), 2)

    summary = {
        "total": len(evidence_list),
        "strong": strength_counts[EvidenceStrength.STRONG],
        "moderate": strength_counts[EvidenceStrength.MODERATE],
        "weak": strength_counts[EvidenceStrength.WEAK],
        "speculative": strength_counts[EvidenceStrength.SPECULATIVE],
        "unique_sources": unique_sources,
        "quality_score": quality_score,
    }

    log.info(
        f"📈 Evidence quality: {summary['total']} pieces, "
        f"score={summary['quality_score']}, "
        f"sources={summary['unique_sources']}"
    )
    return summary


def check_evidence_coverage(
    evidence_list: list[Evidence],
    subquestions: list["SubQuestion"],
    min_per_claim: int,
) -> dict:
    """
    Check whether each subquestion has at least `min_per_claim` pieces
    of supporting evidence.

    Returns a dict with:
      - covered: list of subquestion IDs that meet the threshold
      - under_covered: list of dicts {id, question, count, needed}
      - all_met: bool — True only if every subquestion meets the threshold
    """
    from models.schemas import SubQuestion  # avoid circular import at module level

    # Count evidence per subquestion
    counts: dict[str, int] = {}
    for sq in subquestions:
        counts[sq.id] = 0
    for e in evidence_list:
        if e.subquestion_id and e.subquestion_id in counts:
            counts[e.subquestion_id] += 1

    covered = []
    under_covered = []

    for sq in subquestions:
        count = counts.get(sq.id, 0)
        if count >= min_per_claim:
            covered.append(sq.id)
        else:
            under_covered.append({
                "id": sq.id,
                "question": sq.question,
                "count": count,
                "needed": min_per_claim,
            })

    all_met = len(under_covered) == 0

    if under_covered:
        log.info(
            f"📉 Evidence coverage: {len(covered)}/{len(subquestions)} subquestions "
            f"meet minimum of {min_per_claim} evidence pieces"
        )
        for uc in under_covered:
            log.info(f"   ⚠ [{uc['id']}] has {uc['count']}/{uc['needed']}: {uc['question']}")
    else:
        log.info(
            f"📊 Evidence coverage: all {len(subquestions)} subquestions "
            f"meet minimum of {min_per_claim} evidence pieces ✅"
        )

    return {
        "covered": covered,
        "under_covered": under_covered,
        "all_met": all_met,
    }


def format_evidence_for_prompt(evidence_list: list[Evidence], max_items: int = 30) -> str:
    """Format evidence list as a readable string for LLM prompts."""
    if not evidence_list:
        return "No evidence collected yet."

    lines = []
    for i, e in enumerate(evidence_list[:max_items], 1):
        line = f"{i}. [{e.strength.value.upper()}] {e.claim}"
        if e.quote:
            line += f'\n   Quote: "{e.quote}"'
        line += f"\n   Source: {e.source_url}"
        lines.append(line)

    if len(evidence_list) > max_items:
        lines.append(f"\n... and {len(evidence_list) - max_items} more pieces of evidence")

    return "\n\n".join(lines)


# ══════════════════════════════════════════════════════════════════
#  NEW: Heuristic evaluation metrics
# ══════════════════════════════════════════════════════════════════


def compute_factuality_score(evidence_list: list[Evidence]) -> float:
    """Weighted average of evidence strength. Higher = more factual."""
    if not evidence_list:
        return 0.0
    total = sum(STRENGTH_WEIGHTS[e.strength] for e in evidence_list)
    return round(total / len(evidence_list), 2)



def compute_source_diversity(evidence_list: list[Evidence]) -> dict:
    """Count unique domains and classify them by category."""
    domains: set[str] = set()
    categories: dict[str, int] = {
        "government": 0, "academic": 0, "news": 0, "tech": 0,
        "social": 0, "forum": 0, "blog": 0, "other": 0,
    }

    for e in evidence_list:
        try:
            domain = urlparse(e.source_url).netloc.lower()
        except Exception:
            continue
        if not domain:
            continue
        domains.add(domain)
        categories[_classify_domain(domain)] += 1

    return {
        "unique_domains": len(domains),
        "categories": {k: v for k, v in categories.items() if v > 0},
    }


def _classify_domain(domain: str) -> str:
    """Simple rule-based domain classification."""
    if ".gov" in domain:
        return "government"
    if ".edu" in domain or "arxiv" in domain or "ieee" in domain or "acm.org" in domain:
        return "academic"
    news = ["nytimes", "bbc", "reuters", "bloomberg", "washingtonpost", "theverge", "wired", "arstechnica"]
    if any(n in domain for n in news):
        return "news"
    tech = ["techcrunch", "github", "stackoverflow", "medium", "substack", "dev.to"]
    if any(t in domain for t in tech):
        return "tech"
    social = ["reddit", "linkedin", "twitter", "x.com", "facebook"]
    if any(s in domain for s in social):
        return "social"
    if "forum" in domain:
        return "forum"
    if "blog" in domain or "wordpress" in domain:
        return "blog"
    return "other"


def compute_source_authority(evidence_list: list[Evidence]) -> float:
    """Average authority score based on domain classification."""
    if not evidence_list:
        return 0.0

    scores: list[float] = []
    for e in evidence_list:
        try:
            domain = urlparse(e.source_url).netloc.lower()
        except Exception:
            scores.append(0.3)
            continue
        scores.append(_domain_authority(domain))

    return round(sum(scores) / len(scores), 2)


def _domain_authority(domain: str) -> float:
    """Score a domain 0.0-1.0 based on simple rules."""
    for pattern in HIGH_AUTHORITY_DOMAINS:
        if pattern in domain:
            return 1.0
    for pattern in MEDIUM_AUTHORITY_DOMAINS:
        if pattern in domain:
            return 0.6
    for pattern in LOW_AUTHORITY_DOMAINS:
        if pattern in domain:
            return 0.3
    return 0.5  # unknown domains get a neutral score


def compute_uncertainty_calibration(report: FinalReport) -> float:
    """
    Score how well the report acknowledges uncertainty.
    Checks for hedging phrases, weak evidence sections, and open questions.
    """
    score = 0.0
    total_checks = 3

    # 1. Report text contains hedging phrases
    full_text = (
        report.executive_summary + " "
        + " ".join(report.key_findings)
    ).lower()
    hedging_count = sum(1 for phrase in HEDGING_PHRASES if phrase in full_text)
    if hedging_count >= 3:
        score += 1.0
    elif hedging_count >= 1:
        score += 0.5

    # 2. Weak evidence section exists and is non-empty
    if report.weak_evidence:
        score += 1.0

    # 3. Open questions section exists and is non-empty
    if report.open_questions:
        score += 1.0

    return round(score / total_checks, 2)


def detect_redundancy(evidence_list: list[Evidence]) -> int:
    """Count evidence pairs with very similar claims from different sources."""
    redundant = 0
    claims = [(e.claim.lower().split(), e.source_url) for e in evidence_list]

    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            words_a, url_a = claims[i]
            words_b, url_b = claims[j]
            if url_a == url_b:
                continue  # same source doesn't count
            # Simple word overlap ratio
            set_a, set_b = set(words_a), set(words_b)
            if not set_a or not set_b:
                continue
            overlap = len(set_a & set_b) / min(len(set_a), len(set_b))
            if overlap > 0.7:
                redundant += 1

    return redundant


def compute_freshness(evidence_list: list[Evidence]) -> float:
    """
    Estimate evidence freshness from date_mentioned fields
    and year references in claims.
    """
    if not evidence_list:
        return 0.0

    current_year = datetime.now(timezone.utc).year
    year_scores: list[float] = []

    for e in evidence_list:
        year = _extract_year(e)
        if year:
            age = current_year - year
            if age <= 0:
                year_scores.append(1.0)
            elif age == 1:
                year_scores.append(0.8)
            elif age == 2:
                year_scores.append(0.6)
            elif age <= 4:
                year_scores.append(0.3)
            else:
                year_scores.append(0.1)

    if not year_scores:
        return 0.5  # no date info — neutral

    return round(sum(year_scores) / len(year_scores), 2)


def _extract_year(evidence: Evidence) -> int | None:
    """Try to extract a year from evidence metadata or claim text."""
    # Try date_mentioned first
    if evidence.date_mentioned:
        match = re.search(r"(20\d{2})", evidence.date_mentioned)
        if match:
            return int(match.group(1))

    # Fallback: scan claim text for year mentions
    match = re.search(r"\b(20[12]\d)\b", evidence.claim)
    if match:
        return int(match.group(1))

    return None



def compute_reflection_quality(state: RunState) -> dict:
    """Measure whether reflections drove meaningful iteration."""
    if not state.reflections:
        return {
            "total_reflections": 0,
            "continue_decisions": 0,
            "new_queries_generated": 0,
            "gaps_identified": 0,
            "iterative_behavior": False,
        }

    continue_count = sum(
        1 for r in state.reflections
        if r.decision == ReflectionDecision.CONTINUE
    )
    total_new_queries = sum(len(r.new_search_queries) for r in state.reflections)
    total_gaps = sum(len(r.gaps) for r in state.reflections)

    return {
        "total_reflections": len(state.reflections),
        "continue_decisions": continue_count,
        "new_queries_generated": total_new_queries,
        "gaps_identified": total_gaps,
        "iterative_behavior": continue_count > 0 and total_new_queries > 0,
    }


def compute_avg_evidence_per_subquestion(
    evidence_list: list[Evidence],
    subquestions: list[SubQuestion],
) -> float:
    """Average evidence count per subquestion."""
    if not subquestions:
        return 0.0
    counts = {sq.id: 0 for sq in subquestions}
    for e in evidence_list:
        if e.subquestion_id and e.subquestion_id in counts:
            counts[e.subquestion_id] += 1
    total = sum(counts.values())
    return round(total / len(subquestions), 2)


# ══════════════════════════════════════════════════════════════════
#  Master evaluation: produces the evals.json dict
# ══════════════════════════════════════════════════════════════════


def run_full_evaluation(state: RunState, runtime_seconds: float) -> dict:
    """
    Run all heuristic evaluations on a completed research run.
    Returns a dict ready to be serialized to evals.json.
    """
    log.info("\n" + "─" * 40)
    log.info("PHASE 4: EVALUATION")
    log.info("─" * 40)

    evidence = state.all_evidence
    subquestions = state.plan.subquestions if state.plan else []
    report = state.report

    # ── Core metrics ──────────────────────────────────────────────
    factuality = compute_factuality_score(evidence)
    log.info(f"  📊 Factuality score: {factuality}")

    diversity = compute_source_diversity(evidence)
    log.info(f"  🌐 Source diversity: {diversity['unique_domains']} domains, categories: {diversity['categories']}")

    authority = compute_source_authority(evidence)
    log.info(f"  🏛️  Source authority: {authority}")

    calibration = compute_uncertainty_calibration(report) if report else 0.0
    log.info(f"  🎯 Uncertainty calibration: {calibration}")

    # ── Diagnostics ───────────────────────────────────────────────
    redundancy = detect_redundancy(evidence)
    log.info(f"  🔁 Redundant evidence pairs: {redundancy}")

    freshness = compute_freshness(evidence)
    log.info(f"  🕐 Freshness score: {freshness}")

    reflection_quality = compute_reflection_quality(state)
    log.info(f"  🔄 Reflection quality: {reflection_quality}")

    avg_evidence = compute_avg_evidence_per_subquestion(evidence, subquestions)
    log.info(f"  📋 Avg evidence per subquestion: {avg_evidence}")

    # ── Evidence breakdown ────────────────────────────────────────
    ev_summary = evaluate_evidence(evidence)

    # ── Assemble evals dict ───────────────────────────────────────
    evals = {
        # Core scores
        "factuality_score": factuality,
        "source_diversity": diversity["unique_domains"],
        "source_categories": diversity["categories"],
        "source_authority_score": authority,
        "uncertainty_calibration": calibration,

        # Execution metrics
        "iteration_depth": state.current_iteration,
        "runtime_seconds": round(runtime_seconds, 1),
        "sources_analyzed": state.total_sources,
        "stop_reason": state.stop_reason,

        # Evidence breakdown
        "total_evidence": ev_summary["total"],
        "strong_evidence_count": ev_summary["strong"],
        "moderate_evidence_count": ev_summary["moderate"],
        "weak_evidence_count": ev_summary["weak"],
        "speculative_evidence_count": ev_summary["speculative"],
        "avg_evidence_per_subquestion": avg_evidence,

        # Diagnostics
        "redundant_evidence_pairs": redundancy,
        "freshness_score": freshness,
        # Reflection quality
        "reflection_quality": reflection_quality,
    }

    log.info("─" * 40)
    log.info(f"📋 Evaluation complete — {len(evals)} metrics computed")

    return evals
