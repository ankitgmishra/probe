"""
ProbeAI — Extractor agent.

Takes search results and extracts structured evidence:
- Claims, facts, dates, quotes
- Source attribution
- Strength assessment
"""

from __future__ import annotations

import config
from models.schemas import Evidence, EvidenceStrength, SearchResult, SubQuestion
from utils import call_ollama_json, load_prompt, log


def extract_evidence(
    question: str,
    subquestions: list[SubQuestion],
    search_results: list[SearchResult],
) -> list[Evidence]:
    """
    Extract structured evidence from search results in batches.
    """
    if not search_results:
        log.warning("No search results to extract evidence from.")
        return []

    batch_size = config.EXTRACTION_BATCH_SIZE
    log.info(f"🔬 Extracting evidence from {len(search_results)} results (batch size: {batch_size})...")

    # Format subquestions (same for all batches)
    sq_text = "\n".join(
        f"- [{sq.id}] {sq.question}" for sq in subquestions
    )
    
    prompt_template = load_prompt("extractor_prompt.txt")
    all_evidence: list[Evidence] = []

    # Process in batches
    for i in range(0, len(search_results), batch_size):
        batch = search_results[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(search_results) + batch_size - 1) // batch_size
        
        log.info(f"   📦 Batch {batch_num}/{total_batches} ({len(batch)} results)")

        sr_text = "\n\n".join(
            f"Title: {r.title}\nURL: {r.url}\nContent: {r.snippet}"
            for r in batch
        )

        prompt = (
            prompt_template
            .replace("{question}", question)
            .replace("{subquestions}", sq_text)
            .replace("{search_results}", sr_text)
        )

        result = call_ollama_json(
            prompt=prompt,
            system="You are an evidence extraction expert. Always respond with valid JSON only.",
        )

        # Parse evidence from this batch
        batch_evidence_count = 0
        for item in result.get("evidence", []):
            strength_str = item.get("strength", "moderate").lower()
            try:
                strength = EvidenceStrength(strength_str)
            except ValueError:
                strength = EvidenceStrength.MODERATE

            all_evidence.append(
                Evidence(
                    claim=item.get("claim") or "",
                    source_url=item.get("source_url") or "",
                    source_title=item.get("source_title") or "",
                    quote=item.get("quote"),
                    date_mentioned=str(item["date_mentioned"]) if item.get("date_mentioned") is not None else None,
                    strength=strength,
                    subquestion_id=_parse_subquestion_id(item.get("subquestion_id")),
                )
            )
            batch_evidence_count += 1
        
        log.info(f"      → Extracted {batch_evidence_count} pieces")

    # Post-extraction filtering
    before_count = len(all_evidence)
    all_evidence = _deduplicate_evidence(all_evidence)
    all_evidence = [e for e in all_evidence if not _is_vague_claim(e.claim)]
    filtered = before_count - len(all_evidence)
    if filtered > 0:
        log.info(f"   🧹 Filtered {filtered} low-quality/duplicate items")

    log.info(f"   ✅ Finished extraction: {len(all_evidence)} total pieces")
    return all_evidence


def _parse_subquestion_id(val: any) -> str | None:
    """Robustly parse a subquestion ID from various LLM output types."""
    if val is None:
        return None
    if isinstance(val, list):
        if not val:
            return None
        val = val[0]
    
    s_val = str(val).strip()
    if s_val.lower() in ("none", "null", "false", ""):
        return None
    return s_val


def _deduplicate_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Remove near-duplicate evidence claims (>70% word overlap)."""
    if len(evidence) <= 1:
        return evidence

    kept: list[Evidence] = []
    seen_word_sets: list[set[str]] = []

    for e in evidence:
        words = set(e.claim.lower().split())
        if len(words) < 3:
            continue  # skip extremely short claims

        is_dup = False
        for seen in seen_word_sets:
            if not seen or not words:
                continue
            overlap = len(words & seen) / min(len(words), len(seen))
            if overlap > 0.7:
                is_dup = True
                break

        if not is_dup:
            kept.append(e)
            seen_word_sets.append(words)

    return kept


# Phrases that signal a vague, low-signal claim
_VAGUE_PHRASES = [
    "is a tool", "is a platform", "is a framework", "is useful",
    "has many features", "is designed to", "can be used for",
    "offers a variety", "provides various", "is important",
    "plays a role", "is widely used", "is an open-source",
]


def _is_vague_claim(claim: str) -> bool:
    """Check if a claim is too vague or generic to be useful."""
    if len(claim) < 30:
        return True

    claim_lower = claim.lower()
    # Flag if the claim is mostly a generic descriptor
    for phrase in _VAGUE_PHRASES:
        if phrase in claim_lower and len(claim) < 80:
            return True

    return False
