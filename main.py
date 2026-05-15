"""
ProbeAI — Main orchestration loop.

This is the heart of the system. It manually orchestrates the
research cycle: Plan → Search → Extract → Reflect → (loop) → Synthesize.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from models.schemas import (
    IterationSummary,
    ReflectionDecision,
    RunState,
)
from agents.planner import plan_research
from agents.extractor import extract_evidence
from agents.reflector import reflect
from agents.synthesizer import synthesize_report, format_report_markdown
from services.search import batch_search
from services.evaluator import evaluate_evidence, check_evidence_coverage, run_full_evaluation
from utils import log, save_run_state, save_report, save_evals, Timer


def run_research(question: str) -> RunState:
    """
    Execute a full research run.

    Orchestration loop:
      1. Plan — break question into subquestions
      2. Loop:
         a. Search — run queries via Tavily
         b. Extract — pull structured evidence
         c. Reflect — assess coverage, decide continue/stop
      3. Synthesize — compile final report
    """
    log.info("=" * 60)
    log.info(f"🚀 ProbeAI — Starting research")
    log.info(f"   Question: {question}")
    log.info(f"   Limits: {config.MAX_ITERATIONS} iterations, "
             f"{config.MAX_SOURCES} sources, "
             f"{config.MAX_RUNTIME_SECONDS}s runtime")
    log.info("=" * 60)

    # Initialize state
    state = RunState(question=question)
    run_dir = config.RUNS_DIR / state.run_id
    start_time = time.time()

    try:
        # ── Step 1: Planning ───────────────────────────────────────
        log.info("\n" + "─" * 40)
        log.info("PHASE 1: PLANNING")
        log.info("─" * 40)

        with Timer() as plan_timer:
            state.plan = plan_research(question)

        save_run_state(state, run_dir)

        # ── Step 2: Iterative Research Loop ────────────────────────
        queries = state.plan.initial_search_queries
        all_gaps: list[str] = []

        for iteration in range(1, config.MAX_ITERATIONS + 1):
            state.current_iteration = iteration

            log.info(f"\n{'─' * 40}")
            log.info(f"ITERATION {iteration} / {config.MAX_ITERATIONS}")
            log.info(f"{'─' * 40}")

            with Timer() as iter_timer:
                # ── Check runtime limit ────────────────────────────
                elapsed = time.time() - start_time
                if elapsed > config.MAX_RUNTIME_SECONDS:
                    log.warning(f"⏰ Runtime limit reached ({elapsed:.0f}s)")
                    state.stop_reason = "runtime_limit"
                    break

                # ── Check source limit ─────────────────────────────
                if state.total_sources >= config.MAX_SOURCES:
                    log.warning(f"📚 Source limit reached ({state.total_sources})")
                    state.stop_reason = "source_limit"
                    break

                # ── 2a: Search ─────────────────────────────────────
                log.info(f"\n  🔍 Searching with {len(queries)} queries...")
                state.queries_log.extend(queries)
                search_results = batch_search(queries)
                state.all_search_results.extend(search_results)
                state.total_sources += len(search_results)

                if not search_results:
                    log.warning("  No search results found. Skipping extraction.")
                    queries = []
                    continue

                # ── 2b: Extract ────────────────────────────────────
                log.info(f"\n  🔬 Extracting evidence...")
                new_evidence = extract_evidence(
                    question=question,
                    subquestions=state.plan.subquestions,
                    search_results=search_results,
                )
                state.all_evidence.extend(new_evidence)

                # ── 2c: Reflect ────────────────────────────────────
                log.info(f"\n  🤔 Reflecting...")
                reflection = reflect(
                    question=question,
                    subquestions=state.plan.subquestions,
                    evidence=state.all_evidence,
                    current_iteration=iteration,
                    total_sources=state.total_sources,
                )
                state.reflections.append(reflection)
                all_gaps = reflection.gaps

                # Record iteration summary
                state.iteration_summaries.append(
                    IterationSummary(
                        iteration=iteration,
                        queries_used=queries,
                        sources_found=len(search_results),
                        evidence_extracted=len(new_evidence),
                        reflection_decision=reflection.decision,
                        gaps_identified=reflection.gaps,
                        duration_seconds=iter_timer.seconds if iter_timer.elapsed > 0 else 0,
                    )
                )

                # Save intermediate state
                save_run_state(state, run_dir)

                # ── Check reflection decision ──────────────────────
                if reflection.decision == ReflectionDecision.SUFFICIENT:
                    log.info("  ✅ Reflector says: evidence is sufficient!")
                    state.stop_reason = "sufficient_evidence"
                    break

                if reflection.decision == ReflectionDecision.UNANSWERABLE:
                    log.info("  ❌ Reflector says: question is unanswerable.")
                    state.stop_reason = "unanswerable"
                    break

                # ── Prepare next iteration queries ─────────────────
                queries = reflection.new_search_queries
                if not queries:
                    log.info("  No new queries generated. Stopping.")
                    state.stop_reason = "no_new_queries"
                    break

        else:
            # Loop completed without break — hit iteration limit
            state.stop_reason = "iteration_limit"
            log.info(f"\n  ⏳ Max iterations ({config.MAX_ITERATIONS}) reached.")

        # ── Step 3: Synthesis ──────────────────────────────────────
        log.info(f"\n{'─' * 40}")
        log.info("PHASE 3: SYNTHESIS")
        log.info(f"{'─' * 40}")

        eval_summary = evaluate_evidence(state.all_evidence)
        log.info(f"  Evidence summary: {eval_summary}")

        # Check per-claim evidence coverage
        coverage = check_evidence_coverage(
            state.all_evidence,
            state.plan.subquestions,
            config.MIN_EVIDENCE_PER_CLAIM,
        )

        report = synthesize_report(
            question=question,
            subquestions=state.plan.subquestions,
            evidence=state.all_evidence,
            gaps=all_gaps,
        )
        state.report = report

        # Save final report as markdown
        report_md = format_report_markdown(report)
        save_report(report_md, run_dir)

        # ── Step 4: Evaluation ────────────────────────────────────
        elapsed_so_far = time.time() - start_time
        evals = run_full_evaluation(state, runtime_seconds=elapsed_so_far)
        save_evals(evals, run_dir)

    except Exception as e:
        log.error(f"❗ Research failed: {e}")
        state.stop_reason = f"error: {str(e)}"
        raise

    finally:
        # Finalize state
        state.finished_at = datetime.now(timezone.utc)
        save_run_state(state, run_dir)

        # Print summary
        elapsed = time.time() - start_time
        log.info("\n" + "=" * 60)
        log.info("🏁 RESEARCH COMPLETE")
        log.info(f"   Run ID:     {state.run_id}")
        log.info(f"   Duration:   {elapsed:.1f}s")
        log.info(f"   Iterations: {state.current_iteration}")
        log.info(f"   Sources:    {state.total_sources}")
        log.info(f"   Evidence:   {len(state.all_evidence)} pieces")
        log.info(f"   Min evidence/claim: {config.MIN_EVIDENCE_PER_CLAIM}")
        log.info(f"   Stop reason: {state.stop_reason}")
        log.info(f"   Output:     {run_dir}/")
        log.info(f"   Files:      state.json, report.md, evals.json")
        log.info("=" * 60)

    return state


# ── CLI Entry Point ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ProbeAI — Minimal Deep Research Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py "What are the latest advances in quantum computing?"
  python main.py "Compare React vs Vue in 2025" --max-iterations 5
  python main.py "Impact of AI on jobs" --model llama3.1:8b
        """,
    )
    parser.add_argument(
        "question",
        type=str,
        help="The research question to investigate",
    )
    parser.add_argument(
        "--max-iterations", "-i",
        type=int,
        default=None,
        help=f"Maximum research iterations (default: {config.MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--max-sources", "-s",
        type=int,
        default=None,
        help=f"Maximum sources to collect (default: {config.MAX_SOURCES})",
    )
    parser.add_argument(
        "--max-runtime", "-t",
        type=int,
        default=None,
        help=f"Maximum runtime in seconds (default: {config.MAX_RUNTIME_SECONDS})",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help=f"Ollama model to use (default: {config.OLLAMA_MODEL})",
    )
    parser.add_argument(
        "--min-evidence", "-e",
        type=int,
        default=None,
        help=f"Minimum evidence pieces per claim (default: {config.MIN_EVIDENCE_PER_CLAIM})",
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=None,
        help=f"Batch size for evidence extraction (default: {config.EXTRACTION_BATCH_SIZE})",
    )

    args = parser.parse_args()

    # Override config from CLI args
    if args.max_iterations is not None:
        config.MAX_ITERATIONS = args.max_iterations
    if args.max_sources is not None:
        config.MAX_SOURCES = args.max_sources
    if args.max_runtime is not None:
        config.MAX_RUNTIME_SECONDS = args.max_runtime
    if args.model is not None:
        config.OLLAMA_MODEL = args.model
    if args.min_evidence is not None:
        config.MIN_EVIDENCE_PER_CLAIM = args.min_evidence
    if args.batch_size is not None:
        config.EXTRACTION_BATCH_SIZE = args.batch_size

    try:
        state = run_research(args.question)
        if state.report:
            print(f"\n📄 Report saved to: runs/{state.run_id}/report.md")
        sys.exit(0)
    except KeyboardInterrupt:
        log.info("\n⛔ Research interrupted by user.")
        sys.exit(1)
    except Exception as e:
        log.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
