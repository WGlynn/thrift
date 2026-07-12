#!/usr/bin/env python3
"""Thrift Lever 3 — code-mode gate (PostToolUse).

Every tool round-trip re-reads the full context. N separate Read/Bash/Grep calls
that could be one script pay that re-read N times. This hook detects a burst of
same-tool calls in a sliding window and surfaces one nudge: replace the round-trips
with a single script that returns the filtered result once.

Empirical anchor: Anthropic's Nov-2025 "code execution with MCP" trace reports
150k -> 2k tokens (98.7%) on a multi-file aggregation by doing it in one script.

Augmentation, not a block -- the model still decides; a script is genuinely wrong
for streaming UX, per-call human approval, or partial-failure recovery. Cooldown
prevents nagging. Fail-open and self-contained (state under ~/.claude/.thrift/).

PostToolUse contract: emit {"hookSpecificOutput":{"hookEventName":"PostToolUse",
"additionalContext": "..."}} to add context, or {} for no-op.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from thrift_common import cfg, enabled, ensure_dirs, read_stdin_json, emit, LOG_DIR  # noqa: E402

WATCH_TOOLS = {"Bash", "Read", "Grep", "Glob"}
CALLS = os.path.join(LOG_DIR, "codemode_calls.jsonl")
FIRES = os.path.join(LOG_DIR, "codemode_fires.jsonl")


def _tail_json(path, keep=200):
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(l) for l in f.readlines()[-keep:] if l.strip()]
    except Exception:
        return []


def _append(path, rec):
    ensure_dirs()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def main():
    if not enabled():
        return emit()
    data = read_stdin_json()
    tool = data.get("tool_name") or data.get("toolName") or ""
    if tool not in WATCH_TOOLS:
        return emit()

    now = time.time()
    window = int(cfg("codemode_window_s"))
    threshold = int(cfg("codemode_threshold"))
    cooldown = int(cfg("codemode_cooldown_s"))

    _append(CALLS, {"ts": now, "tool": tool})

    recent = [r for r in _tail_json(CALLS) if r.get("ts", 0) >= now - window]
    counts = {}
    for r in recent:
        counts[r.get("tool", "")] = counts.get(r.get("tool", ""), 0) + 1
    over = [(t, c) for t, c in counts.items() if c >= threshold]
    if not over:
        return emit()

    # cooldown: skip if we nudged recently
    fires = _tail_json(FIRES, keep=1)
    if fires and now - fires[-1].get("ts", 0) < cooldown:
        return emit()

    worst_tool, worst_count = max(over, key=lambda x: x[1])
    _append(FIRES, {"ts": now, "tool": worst_tool, "count": worst_count})

    msg = (
        "[THRIFT code-mode] "
        f"{worst_count} {worst_tool} calls in the last {window}s (threshold {threshold}). "
        "Each round-trip re-reads the full context. Consider ONE Bash/Python script that "
        f"does the {worst_tool} work and returns the filtered result in a single tool "
        "result (Anthropic trace: 150k -> 2k tokens on a similar aggregation). "
        "Proceed as-is if a script is wrong-shape here (streaming, per-call approval, "
        "partial-failure recovery)."
    )
    emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}})


if __name__ == "__main__":
    main()
