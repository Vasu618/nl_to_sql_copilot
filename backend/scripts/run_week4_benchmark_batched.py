"""
Week 4 benchmark runner — batched version.

Runs the 28 benchmark questions in batches of 5-6 questions per invocation,
saving intermediate results to disk between batches. This lets us run the
full benchmark across multiple bash tool calls without any single call
timing out.

Usage:
    .venv/bin/python -m scripts.run_week4_benchmark_batched --start 0 --end 5
    .venv/bin/python -m scripts.run_week4_benchmark_batched --start 5 --end 10
    ...
    .venv/bin/python -m scripts.run_week4_benchmark_batched --summary  # final aggregation
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from app.pipeline import run_pipeline
from app.explainer import explain

from scripts.run_week4_benchmark import (
    BenchmarkResult,
    INTER_QUESTION_DELAY_S,
    run_one,
    verify_first_try,
    verify_result,
)
from scripts.week4_benchmark_questions import (
    ADVERSARIAL_QUESTIONS,
    BENCHMARK_QUESTIONS,
)


STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "week4_state"
STATE_DIR.mkdir(parents=True, exist_ok=True)


def run_batch(start: int, end: int) -> None:
    """Run questions BENCHMARK_QUESTIONS[start:end] and save each result."""
    batch = BENCHMARK_QUESTIONS[start:end]
    print(f"[batch] Running questions {start+1}-{end} ({len(batch)} questions)")
    for i, q in enumerate(batch, start + 1):
        idx = start + (i - start - 1)
        print(f"  [{i:02d}/{len(BENCHMARK_QUESTIONS)}] ({q['difficulty']}) {q['question'][:60]}...")
        try:
            r = run_one(q)
            marker = {
                "success": "OK" if r.answer_correct else "WRONG",
                "no_answer": "NO_ANSWER" if r.answer_correct else "WRONG_NA",
                "validation_failed": "VAL_FAIL",
                "execution_failed": "EXEC_FAIL",
                "llm_failed": "LLM_FAIL",
            }.get(r.final_status, "??")
            corr = f"+{r.correction_attempts}corr" if r.correction_attempts > 0 else "first-try"
            print(f"          -> [{marker}] rows={r.row_count} {corr} {r.total_elapsed_s:.1f}s")
            if r.first_try_correct:
                print(f"             first-try: CORRECT")
            if r.error:
                print(f"             error: {r.error[:100]}")
            # Save this question's result
            out_file = STATE_DIR / f"{q['id']}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(asdict(r), f, indent=2, default=str)
            print(f"             saved: {out_file.name}")
        except Exception as e:
            print(f"          -> EXCEPTION: {type(e).__name__}: {e}")
            # Save error state
            err_result = BenchmarkResult(
                id=q["id"], question=q["question"], difficulty=q["difficulty"],
                category=q["category"], expected_answer_summary=q.get("expected_answer_summary", ""),
                final_status="llm_failed", correction_attempts=0,
                first_try_validation_ok=False, first_try_execution_ok=False,
                answer_correct=False, first_try_correct=False,
                verify_explanation=bool(q.get("verify_explanation", False)),
                error=f"Exception: {e}",
            )
            out_file = STATE_DIR / f"{q['id']}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(asdict(err_result), f, indent=2, default=str)
        if i < end:
            time.sleep(INTER_QUESTION_DELAY_S)


def run_adversarial() -> None:
    """Run the 4 adversarial questions and save results."""
    print(f"\n[adversarial] Running {len(ADVERSARIAL_QUESTIONS)} adversarial questions")
    for i, q in enumerate(ADVERSARIAL_QUESTIONS):
        print(f"  [{q['id']}] {q['question']}")
        try:
            pr = run_pipeline(q["question"], question_id=q["id"])
            llm_refused = (pr.final_status == "success")
            validator_caught = pr.final_status in ("validation_failed", "execution_failed") and \
                pr.attempts and not pr.attempts[-1].validation_ok
            passed = llm_refused or validator_caught
            result = {
                "id": q["id"],
                "question": q["question"],
                "final_status": pr.final_status,
                "final_sql": pr.final_sql,
                "final_error": pr.final_error,
                "llm_refused": llm_refused,
                "validator_caught": validator_caught,
                "passed": passed,
            }
            outcome = "LLM refused" if llm_refused else ("Validator caught" if validator_caught else "FAIL(allowed!)")
            print(f"          -> {outcome}")
        except Exception as e:
            result = {
                "id": q["id"], "question": q["question"],
                "error": str(e), "passed": False,
            }
            print(f"          -> ERROR: {e}")
        out_file = STATE_DIR / f"{q['id']}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        if i < len(ADVERSARIAL_QUESTIONS) - 1:
            time.sleep(INTER_QUESTION_DELAY_S)


def aggregate() -> None:
    """Load all saved per-question results and compute summary stats."""
    results: list[dict] = []
    adv_results: list[dict] = []
    for q in BENCHMARK_QUESTIONS:
        f = STATE_DIR / f"{q['id']}.json"
        if f.exists():
            with open(f) as fh:
                results.append(json.load(fh))
        else:
            print(f"  WARNING: {f.name} missing")
    for q in ADVERSARIAL_QUESTIONS:
        f = STATE_DIR / f"{q['id']}.json"
        if f.exists():
            with open(f) as fh:
                adv_results.append(json.load(fh))

    n = len(results)
    n_success = sum(1 for r in results if r["final_status"] == "success")
    n_no_answer = sum(1 for r in results if r["final_status"] == "no_answer")
    n_failed = n - n_success - n_no_answer
    n_correct = sum(1 for r in results if r["answer_correct"])
    n_first_try_correct = sum(1 for r in results if r["first_try_correct"])
    total_corr = sum(r["correction_attempts"] for r in results)
    avg_corr = total_corr / n if n else 0
    avg_latency = sum(r["total_elapsed_s"] for r in results) / n if n else 0

    print("\n" + "=" * 78)
    print("WEEK 4 BENCHMARK RESULTS (aggregated)")
    print("=" * 78)
    print(f"\nOverall (n={n}):")
    print(f"  First-try correct:           {n_first_try_correct}/{n}  ({n_first_try_correct/n*100:.1f}%)")
    print(f"  Post-correction correct:     {n_correct}/{n}  ({n_correct/n*100:.1f}%)")
    print(f"  Honest no_answer:            {n_no_answer}/{n}  ({n_no_answer/n*100:.1f}%)")
    print(f"  Failed (val/exec/llm):       {n_failed}/{n}  ({n_failed/n*100:.1f}%)")
    print(f"  Avg correction attempts:     {avg_corr:.2f}")
    print(f"  Avg latency per question:    {avg_latency:.2f}s")

    print(f"\nBy difficulty:")
    print(f"  {'Difficulty':<10} {'n':>3} {'1st-try':>10} {'post-corr':>10} {'no_answer':>10} {'failed':>8} {'avg_corr':>10} {'avg_lat':>10}")
    for diff in ("easy", "medium", "hard"):
        sub = [r for r in results if r["difficulty"] == diff]
        if not sub:
            continue
        n_d = len(sub)
        n_succ_d = sum(1 for r in sub if r["final_status"] == "success")
        n_no_d = sum(1 for r in sub if r["final_status"] == "no_answer")
        n_fail_d = n_d - n_succ_d - n_no_d
        n_corr_d = sum(1 for r in sub if r["answer_correct"])
        n_ft_d = sum(1 for r in sub if r["first_try_correct"])
        avg_corr_d = sum(r["correction_attempts"] for r in sub) / n_d
        avg_lat_d = sum(r["total_elapsed_s"] for r in sub) / n_d
        print(f"  {diff:<10} {n_d:>3} {n_ft_d:>3} ({n_ft_d/n_d*100:>4.0f}%) {n_corr_d:>3} ({n_corr_d/n_d*100:>4.0f}%) {n_no_d:>3} ({n_no_d/n_d*100:>4.0f}%) {n_fail_d:>5} ({n_fail_d/n_d*100:>4.0f}%) {avg_corr_d:>8.2f}  {avg_lat_d:>7.2f}s")

    print(f"\nAdversarial ({len(adv_results)} cases):")
    adv_pass = sum(1 for a in adv_results if a.get("passed"))
    print(f"  {adv_pass}/{len(adv_results)} correctly handled (refused or blocked)")
    for a in adv_results:
        outcome = "PASS" if a.get("passed") else "FAIL"
        reason = "LLM refused" if a.get("llm_refused") else ("Validator caught" if a.get("validator_caught") else "allowed!")
        print(f"    [{outcome}] {a['id']}: {a['question']}  ({reason})")

    print(f"\nPer-question detail:")
    print(f"  {'ID':<5} {'Diff':<7} {'Status':<14} {'1st-try':<9} {'Final':<7} {'Corr':<5} {'Lat':<6} Question")
    for r in results:
        status = r["final_status"][:13]
        ft = "Y" if r["first_try_correct"] else "N"
        fin = "Y" if r["answer_correct"] else "N"
        print(f"  {r['id']:<5} {r['difficulty']:<7} {status:<14} {ft:<9} {fin:<7} {r['correction_attempts']:<5} {r['total_elapsed_s']:>5.1f}s {r['question'][:50]}")

    # Save full results
    out_path = Path(__file__).resolve().parent.parent / "data" / "week4_benchmark_results.json"
    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "n_questions": n,
        "n_adversarial": len(ADVERSARIAL_QUESTIONS),
        "first_try_correct": n_first_try_correct,
        "first_try_correct_pct": n_first_try_correct / n * 100 if n else 0,
        "post_correction_correct": n_correct,
        "post_correction_correct_pct": n_correct / n * 100 if n else 0,
        "no_answer_count": n_no_answer,
        "no_answer_pct": n_no_answer / n * 100 if n else 0,
        "failed_count": n_failed,
        "failed_pct": n_failed / n * 100 if n else 0,
        "avg_correction_attempts": avg_corr,
        "avg_latency_s": avg_latency,
        "adversarial_pass_rate": adv_pass / len(ADVERSARIAL_QUESTIONS) if ADVERSARIAL_QUESTIONS else 0,
        "by_difficulty": {
            diff: {
                "n": len([r for r in results if r["difficulty"] == diff]),
                "first_try_correct": sum(1 for r in results if r["difficulty"] == diff and r["first_try_correct"]),
                "post_correction_correct": sum(1 for r in results if r["difficulty"] == diff and r["answer_correct"]),
                "no_answer": sum(1 for r in results if r["difficulty"] == diff and r["final_status"] == "no_answer"),
                "failed": sum(1 for r in results if r["difficulty"] == diff and r["final_status"] not in ("success", "no_answer")),
                "avg_correction_attempts": (sum(r["correction_attempts"] for r in results if r["difficulty"] == diff) / max(1, len([r for r in results if r["difficulty"] == diff]))),
                "avg_latency_s": (sum(r["total_elapsed_s"] for r in results if r["difficulty"] == diff) / max(1, len([r for r in results if r["difficulty"] == diff]))),
            }
            for diff in ("easy", "medium", "hard")
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": summary,
            "results": results,
            "adversarial": adv_results,
        }, f, indent=2, default=str)
    print(f"\n[aggregate] Full results saved to: {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=None, help="Start index (inclusive)")
    parser.add_argument("--end", type=int, default=None, help="End index (exclusive)")
    parser.add_argument("--adversarial", action="store_true", help="Run adversarial questions")
    parser.add_argument("--summary", action="store_true", help="Aggregate saved results and print summary")
    args = parser.parse_args()

    if args.summary:
        aggregate()
        return 0
    if args.adversarial:
        run_adversarial()
        return 0
    if args.start is not None and args.end is not None:
        run_batch(args.start, args.end)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
