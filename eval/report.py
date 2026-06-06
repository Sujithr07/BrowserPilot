"""
Render eval/results/REPORT.md from a results.jsonl produced by eval.runner.

Overall success rate, per-site breakdown, average steps & latency, and a full
results table. Pure I/O on the results files — no model calls.

    python -m eval.report [results-dir]
"""
import os
import sys
import json
from datetime import datetime, timezone
from collections import defaultdict


def _load_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_meta(results_dir: str) -> dict:
    path = os.path.join(results_dir, "meta.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _avg(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _esc(text: str) -> str:
    """Make a string safe for a Markdown table cell."""
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def build_report(results_dir: str = "eval/results") -> str:
    rows = _load_jsonl(os.path.join(results_dir, "results.jsonl"))
    meta = _load_meta(results_dir)

    n = len(rows)
    ok = sum(1 for r in rows if r["success"])
    rate = (ok / n) if n else 0.0
    avg_steps = _avg([r["steps_taken"] for r in rows])
    avg_lat = _avg([r["latency_s"] for r in rows])

    by_site: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_site[r["web_name"]].append(r)

    mode = "mock (harness self-test — NOT a real eval)" if meta.get("mock") else "live"
    L: list[str] = []
    L.append("# AgentFlow Eval Report")
    L.append("")
    L.append(f"- **Generated:** {datetime.now(timezone.utc).isoformat()}")
    L.append(f"- **Mode:** {mode}")
    L.append(f"- **Tasks:** {n}")
    L.append(f"- **Overall success rate:** {ok}/{n} = **{rate * 100:.1f}%**")
    L.append(f"- **Avg steps:** {avg_steps:.1f} &nbsp;|&nbsp; **Avg latency:** {avg_lat:.1f}s")
    if meta:
        L.append(
            f"- **Config:** concurrency={meta.get('concurrency')}, "
            f"timeout={meta.get('timeout_s')}s, max_steps={meta.get('max_steps')}"
        )
        L.append(f"- **Judge models:** {', '.join(meta.get('judge_models', [])) or 'n/a'}")
    L.append("")

    # Per-site breakdown
    L.append("## Per-site breakdown")
    L.append("")
    L.append("| Site | Success | Rate | Avg steps | Avg latency (s) |")
    L.append("|------|---------|------|-----------|-----------------|")
    for site in sorted(by_site):
        rs = by_site[site]
        sok = sum(1 for r in rs if r["success"])
        L.append(
            f"| {site} | {sok}/{len(rs)} | {sok / len(rs) * 100:.0f}% | "
            f"{_avg([r['steps_taken'] for r in rs]):.1f} | "
            f"{_avg([r['latency_s'] for r in rs]):.1f} |"
        )
    L.append("")

    # Full results table
    L.append("## Results")
    L.append("")
    L.append("| ID | Site | Result | Steps | Latency (s) | Status | Reason |")
    L.append("|----|------|--------|-------|-------------|--------|--------|")
    for r in sorted(rows, key=lambda x: x["id"]):
        mark = "✅" if r["success"] else "❌"
        reason = _esc(r.get("judge_reason") or r.get("error") or "")[:90]
        L.append(
            f"| {r['id']} | {r['web_name']} | {mark} | {r['steps_taken']} | "
            f"{r['latency_s']:.1f} | {r['status']} | {reason} |"
        )
    L.append("")

    os.makedirs(results_dir, exist_ok=True)
    out = os.path.join(results_dir, "REPORT.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    return out


if __name__ == "__main__":
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "eval/results"
    print(build_report(results_dir))
