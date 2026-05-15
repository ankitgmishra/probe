"""
ProbeAI — Synthesizer agent.

Generates the final cited research report from all collected evidence.
"""

from __future__ import annotations

from models.schemas import Evidence, FinalReport, SubQuestion
from services.evaluator import format_evidence_for_prompt
from utils import call_ollama_json, load_prompt, log


def _build_source_index(evidence: list[Evidence]) -> dict[str, int]:
    """
    Build a deduplicated, numbered source index from evidence URLs.
    Returns a dict mapping URL -> 1-based index number.
    """
    seen: dict[str, int] = {}
    counter = 1
    for e in evidence:
        if e.source_url and e.source_url not in seen:
            seen[e.source_url] = counter
            counter += 1
    return seen


def _format_source_index(source_map: dict[str, int]) -> str:
    """Format the source index as a numbered list for the prompt."""
    lines = []
    for url, num in sorted(source_map.items(), key=lambda x: x[1]):
        lines.append(f"[S{num}] {url}")
    return "\n".join(lines)


def _format_evidence_with_refs(
    evidence: list[Evidence],
    source_map: dict[str, int],
    max_items: int = 50,
) -> str:
    """
    Format evidence for the synthesizer prompt with E# and S# references.
    Each evidence row gets a stable E-number and its source's S-number.
    """
    if not evidence:
        return "No evidence collected."

    lines = []
    for i, e in enumerate(evidence[:max_items], 1):
        s_num = source_map.get(e.source_url, 0)
        s_ref = f"[S{s_num}]" if s_num else ""

        line = f"E{i}. [{e.strength.value.upper()}] {e.claim} {s_ref}"
        if e.quote:
            line += f'\n     Quote: "{e.quote}"'
        line += f"\n     Source: {e.source_url}"
        lines.append(line)

    if len(evidence) > max_items:
        lines.append(f"\n... and {len(evidence) - max_items} more pieces of evidence")

    return "\n\n".join(lines)


def synthesize_report(
    question: str,
    subquestions: list[SubQuestion],
    evidence: list[Evidence],
    gaps: list[str],
) -> FinalReport:
    """
    Generate a final cited research report.
    """
    log.info(f"📝 Synthesizing report from {len(evidence)} pieces of evidence...")

    # Build numbered source index
    source_map = _build_source_index(evidence)
    source_index_text = _format_source_index(source_map)
    log.info(f"   → {len(source_map)} unique sources indexed")

    # Format evidence with E# / S# references for the LLM
    evidence_text = _format_evidence_with_refs(evidence, source_map, max_items=50)

    sq_text = "\n".join(
        f"- {'✅' if sq.answered else '❌'} {sq.question}"
        for sq in subquestions
    )
    gaps_text = "\n".join(f"- {g}" for g in gaps) if gaps else "No major gaps identified."

    prompt_template = load_prompt("synthesizer_prompt.txt")
    prompt = (
        prompt_template
        .replace("{question}", question)
        .replace("{evidence}", evidence_text)
        .replace("{evidence_count}", str(len(evidence)))
        .replace("{subquestions}", sq_text)
        .replace("{gaps}", gaps_text)
        .replace("{source_index}", source_index_text)
    )

    result = call_ollama_json(
        prompt=prompt,
        system="You are a research report writer. Always respond with valid JSON only.",
        temperature=0.3,
    )

    # ── Robust type coercion ──────────────────────────────────────
    # LLMs sometimes return wrong types (dict for string, string for list, etc.)

    # executive_summary: must be a string
    raw_summary = result.get("executive_summary", "")
    if isinstance(raw_summary, dict):
        # Model returned {"paragraph": "text"} or {"text": "...", "source": "..."}
        raw_summary = " ".join(str(v) for v in raw_summary.values() if v)
        log.warning("Coerced executive_summary from dict to string")
    elif isinstance(raw_summary, list):
        raw_summary = "\n\n".join(str(p) for p in raw_summary)
        log.warning("Coerced executive_summary from list to string")
    raw_summary = str(raw_summary).strip() if raw_summary else ""

    # key_findings: must be a list of strings
    raw_findings = result.get("key_findings", [])
    if isinstance(raw_findings, str):
        raw_findings = [f.strip() for f in raw_findings.split("\n") if f.strip()]
        log.warning("Coerced key_findings from string to list")
    elif isinstance(raw_findings, dict):
        raw_findings = [f"{k}: {v}" for k, v in raw_findings.items()]
        log.warning("Coerced key_findings from dict to list")

    report = FinalReport(
        title=result.get("title", f"Research Report: {question}"),
        executive_summary=raw_summary,
        key_findings=raw_findings,
        evidence_table=evidence,
        strong_evidence=result.get("strong_evidence", []),
        weak_evidence=result.get("weak_evidence", []),
        open_questions=result.get("open_questions", []),
        sources=result.get("sources", list(source_map.keys())),
    )

    log.info(f"   → Report: '{report.title}'")
    log.info(f"   → {len(report.key_findings)} key findings, {len(report.sources)} sources")
    return report


def format_report_markdown(report: FinalReport) -> str:
    """Convert a FinalReport to a clean, research-oriented markdown document."""

    # ── Build stable source index from evidence table ──────────────
    source_map: dict[str, int] = {}
    counter = 1
    for e in report.evidence_table:
        if e.source_url and e.source_url not in source_map:
            source_map[e.source_url] = counter
            counter += 1
    for url in report.sources:
        if url not in source_map:
            source_map[url] = counter
            counter += 1

    lines: list[str] = []

    # ── Title & metadata ──────────────────────────────────────────
    lines.extend([
        f"# {report.title}",
        "",
        f"*Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}*  ",
        f"*Evidence: {len(report.evidence_table)} pieces · Sources: {len(source_map)}*",
        "",
        "---",
        "",
    ])

    # ── 1. Executive Summary ──────────────────────────────────────
    lines.extend([
        "## Executive Summary",
        "",
        report.executive_summary,
        "",
        "---",
        "",
    ])

    # ── 2. Key Findings ───────────────────────────────────────────
    lines.extend([
        "## Key Findings",
        "",
    ])
    for i, finding in enumerate(report.key_findings, 1):
        lines.append(f"{i}. {finding}")
    lines.append("")

    # Add inline annotations for evidence quality
    if report.strong_evidence:
        lines.extend(["", "**Strong evidence supports:**", ""])
        for item in report.strong_evidence:
            lines.append(f"- ✅ {item}")

    if report.weak_evidence:
        lines.extend(["", "**Limited evidence (requires further validation):**", ""])
        for item in report.weak_evidence:
            lines.append(f"- ⚠️ {item}")

    lines.extend(["", "---", ""])

    # ── 3. Evidence Table ─────────────────────────────────────────
    lines.extend([
        "## Evidence Table",
        "",
        "| E# | Claim | Strength | Source |",
        "|:---:|-------|:--------:|:------:|",
    ])
    for i, e in enumerate(report.evidence_table, 1):
        claim_display = e.claim[:100] + "…" if len(e.claim) > 100 else e.claim
        claim_display = claim_display.replace("|", "\\|")
        s_num = source_map.get(e.source_url, 0)
        strength_badge = _strength_badge(e.strength.value)
        source_ref = f"[S{s_num}]({e.source_url})" if s_num else f"[Link]({e.source_url})"
        lines.append(f"| E{i} | {claim_display} | {strength_badge} | {source_ref} |")
    lines.extend(["", "---", ""])

    # ── 4. Open Questions & Uncertainty ───────────────────────────
    if report.open_questions:
        lines.extend([
            "## Open Questions & Uncertainty",
            "",
            "> Areas where evidence was insufficient, mixed, or questions remain unresolved.",
            "",
        ])
        for item in report.open_questions:
            lines.append(f"- ❓ {item}")
        lines.extend(["", "---", ""])

    # ── 5. Sources ────────────────────────────────────────────────
    lines.extend([
        "## Sources",
        "",
    ])
    for url, num in sorted(source_map.items(), key=lambda x: x[1]):
        lines.append(f"{num}. [S{num}] {url}")
    lines.append("")

    return "\n".join(lines)


def _strength_badge(strength: str) -> str:
    """Return a visual badge for evidence strength."""
    badges = {
        "strong": "🟢 Strong",
        "moderate": "🟡 Moderate",
        "weak": "🟠 Weak",
        "speculative": "🔴 Speculative",
    }
    return badges.get(strength.lower(), strength)
