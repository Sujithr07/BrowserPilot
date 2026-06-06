"""
Async eval harness for AgentFlow (WebVoyager-style).

Runs `AgentFlowCrew` over a JSONL dataset with bounded concurrency, a per-task
timeout and step cap, scores each result with the LLM-as-judge, and writes
results to <results-dir>/results.jsonl (+ meta.json). Pass --report to also
render REPORT.md.

Everything is configurable by env or CLI flag (CLI wins):
    EVAL_DATASET       dataset path            (--dataset)
    EVAL_CONCURRENCY   max simultaneous tasks  (--concurrency)
    EVAL_TIMEOUT       per-task seconds        (--timeout)
    EVAL_MAX_STEPS     executor step cap       (--max-steps)
    EVAL_RESULTS_DIR   output directory        (--results-dir)
    JUDGE_MODELS       judge model chain (see eval/judge.py)
All provider API keys are read from the environment by backend/llm.py.

Examples:
    python -m eval.runner                      # full dataset, live
    python -m eval.runner --smoke --report     # 3-task CI smoke subset
    python -m eval.runner --mock --report      # harness self-test (no keys/browser)
"""
import os
import sys
import json
import time
import uuid
import asyncio
import argparse
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

# Progress bar: prefer tqdm, but degrade to a tiny stderr bar so the harness has
# zero hard dependency beyond the app's own requirements.
try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - fallback only when tqdm is absent
    class tqdm:  # type: ignore
        def __init__(self, total=0, desc="", unit="", **_):
            self.total, self.n, self.desc = total, 0, desc
            sys.stderr.write(f"{desc}: 0/{total}\n")

        def update(self, k=1):
            self.n += k
            sys.stderr.write(f"\r{self.desc}: {self.n}/{self.total}")
            sys.stderr.flush()

        def set_postfix_str(self, s):
            pass

        def close(self):
            sys.stderr.write("\n")

from backend.crew import AgentFlowCrew
from backend.db import init_db
from eval.judge import judge, JUDGE_MODELS

# ── Defaults (env first, CLI overrides at parse time) ───────────────────────────
DEFAULT_DATASET = os.getenv("EVAL_DATASET", "eval/dataset.jsonl")
DEFAULT_CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "4"))
DEFAULT_TIMEOUT = float(os.getenv("EVAL_TIMEOUT", "180"))
DEFAULT_MAX_STEPS = int(os.getenv("EVAL_MAX_STEPS", "15"))
DEFAULT_RESULTS_DIR = os.getenv("EVAL_RESULTS_DIR", "eval/results")

# The 3-task CI smoke subset — one each from Wikipedia, GitHub, arXiv, chosen for
# stable reference answers.
SMOKE_IDS = ["wiki_01", "github_01", "arxiv_01"]


@dataclass
class EvalResult:
    id: str
    web_name: str
    question: str
    success: bool          # judge verdict
    steps_taken: int       # report.total_steps
    latency_s: float       # wall-clock for the whole task
    status: str            # crew status | 'timeout' | 'error'
    final_answer: str
    judge_reason: str
    error: str | None


def load_dataset(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ── Mock mode: exercise the harness with no keys/browser/network ────────────────
async def _mock_run(task: dict, task_id: str):
    """Deterministic fake TaskReport so CI can test the harness wiring offline."""
    from backend.schemas import TaskReport, TaskPlan

    h = int(hashlib.md5(task["id"].encode()).hexdigest(), 16)
    await asyncio.sleep(0.01)  # let the event loop interleave like real tasks
    correct = (h % 10) < 7  # ~70% "succeed" so the report has a mix
    final = task["answer_reference"] if correct else "I could not determine the answer."
    return TaskReport(
        task_id=task_id,
        goal=task["question"],
        status="completed" if correct else "failed",
        plan=TaskPlan(goal=task["question"], steps=[], estimated_steps=3),
        step_results=[],
        final_answer=final,
        total_steps=(h % 5) + 2,
        successful_steps=(h % 5) + 2,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def _mock_judge(task: dict, final_answer: str) -> tuple[bool, str]:
    ok = final_answer.strip().lower() == task["answer_reference"].strip().lower()
    return ok, ("mock judge: matched reference" if ok else "mock judge: no match")


# ── Single task ─────────────────────────────────────────────────────────────────
async def _run_one(task: dict, timeout: float, mock: bool) -> EvalResult:
    start = time.perf_counter()
    task_id = f"eval-{task['id']}-{uuid.uuid4().hex[:4]}"
    final_answer, steps, status, error = "", 0, "error", None

    try:
        if mock:
            report = await _mock_run(task, task_id)
        else:
            # Fresh crew (and browser) per task; the timeout bounds the whole run.
            crew = AgentFlowCrew()
            report = await asyncio.wait_for(
                crew.run_task(task["question"], task_id), timeout=timeout
            )
        final_answer = report.final_answer or ""
        steps = report.total_steps
        status = report.status
    except asyncio.TimeoutError:
        status, error = "timeout", f"exceeded {timeout:.0f}s timeout"
    except Exception as e:  # browser launch, planner crash, etc.
        status, error = "error", str(e)

    latency = time.perf_counter() - start

    # Score. Judge only when we actually have an answer; otherwise it's a failure
    # by construction (and we avoid spending a judge call on empty input).
    if mock:
        success, reason = _mock_judge(task, final_answer)
    elif final_answer:
        # judge() is synchronous (reasoning_completion is sync) — run it off the
        # event loop so concurrent tasks keep progressing.
        success, reason = await asyncio.to_thread(
            judge, task["question"], task["answer_reference"], final_answer
        )
    else:
        success, reason = False, error or "agent produced no final answer"

    return EvalResult(
        id=task["id"],
        web_name=task["web_name"],
        question=task["question"],
        success=success,
        steps_taken=steps,
        latency_s=round(latency, 2),
        status=status,
        final_answer=final_answer,
        judge_reason=reason,
        error=error,
    )


# ── Full run ────────────────────────────────────────────────────────────────────
async def run_eval(
    dataset: list[dict],
    concurrency: int,
    timeout: float,
    results_dir: str,
    mock: bool = False,
) -> tuple[list[EvalResult], dict]:
    os.makedirs(results_dir, exist_ok=True)
    if not mock:
        await init_db()  # crew.run_task persists each report

    sem = asyncio.Semaphore(concurrency)
    results: list[EvalResult] = []
    pbar = tqdm(total=len(dataset), desc="eval", unit="task")

    async def worker(task: dict):
        async with sem:
            r = await _run_one(task, timeout, mock)
        results.append(r)
        ok = sum(1 for x in results if x.success)
        pbar.update(1)
        pbar.set_postfix_str(f"{ok}/{len(results)} ok")

    await asyncio.gather(*(worker(t) for t in dataset))
    pbar.close()

    results.sort(key=lambda r: r.id)
    with open(os.path.join(results_dir, "results.jsonl"), "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "count": len(results),
        "concurrency": concurrency,
        "timeout_s": timeout,
        "max_steps": int(os.getenv("EXECUTOR_MAX_STEPS", str(DEFAULT_MAX_STEPS))),
        "mock": mock,
        "judge_models": JUDGE_MODELS,
    }
    with open(os.path.join(results_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return results, meta


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="AgentFlow WebVoyager-style eval harness")
    p.add_argument("--dataset", default=DEFAULT_DATASET, help="path to JSONL dataset")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="per-task seconds")
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS, help="executor step cap")
    p.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    p.add_argument("--smoke", action="store_true", help="run only the 3-task smoke subset")
    p.add_argument("--limit", type=int, default=0, help="run only the first N tasks")
    p.add_argument("--mock", action="store_true", help="no real crew/LLM/browser (harness self-test)")
    p.add_argument("--report", action="store_true", help="render REPORT.md after the run")
    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    # Propagate the step cap to the executor (read from env per task).
    os.environ["EXECUTOR_MAX_STEPS"] = str(args.max_steps)

    dataset = load_dataset(args.dataset)
    if args.smoke:
        dataset = [t for t in dataset if t["id"] in SMOKE_IDS]
    elif args.limit:
        dataset = dataset[: args.limit]

    if not dataset:
        print("No tasks selected — check --dataset / --smoke / --limit", file=sys.stderr)
        return 1

    results, _ = asyncio.run(
        run_eval(dataset, args.concurrency, args.timeout, args.results_dir, mock=args.mock)
    )
    n = len(results)
    ok = sum(1 for r in results if r.success)
    print(f"\n{ok}/{n} success ({(ok / n * 100 if n else 0):.0f}%)  "
          f"-> {os.path.join(args.results_dir, 'results.jsonl')}")

    if args.report:
        from eval.report import build_report
        print(f"report -> {build_report(args.results_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
