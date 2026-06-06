# AgentFlow eval shortcuts. Override any default via env or CLI flags, e.g.
#   make eval EVAL_CONCURRENCY=2 EVAL_TIMEOUT=240
# All provider keys are read from the environment / .env by backend/llm.py.

PYTHON ?= python

.PHONY: eval eval-smoke eval-mock eval-report

## Full dataset, live agent, then render REPORT.md
eval:
	$(PYTHON) -m eval.runner --report

## 3-task CI smoke subset (live), serial, then render REPORT.md
eval-smoke:
	$(PYTHON) -m eval.runner --smoke --concurrency 1 --timeout 240 --report

## Harness self-test — no API keys, no browser, no network
eval-mock:
	$(PYTHON) -m eval.runner --mock --report

## Re-render REPORT.md from the last results without re-running
eval-report:
	$(PYTHON) -m eval.report
