#!/usr/bin/env python3
"""Thrift Lever 1 — tier routing (PreToolUse, matcher Agent).

Measured gap: on the audited machine the model mix was ~96% opus / 0% subagent
offload -- cheap, mechanical work was never routed to a cheaper tier. This hook
classifies each delegated task (deterministic keyword heuristic, no model call)
and, for clearly-mechanical work spawned without a cheaper model, surfaces a
routing recommendation on the Agent spawn.

Two modes (config `tier_route_strict`, default false):
  - default (recommend): inject additionalContext suggesting `model: "haiku"` or
    `"sonnet"`. Never blocks -- the model/human keeps the call.
  - strict: DENY the spawn with a reason, forcing an explicit tier choice. Opt-in
    for users who want hard enforcement (e.g. friends on shared limits).

Only fires on CLEARLY mechanical work. Ambiguous or reasoning-heavy tasks pass
silently -- no nagging, no false positives on work that genuinely needs opus.
Fail-open: any error allows the call.

PreToolUse contract: emit {"hookSpecificOutput":{"permissionDecision":"deny",
"permissionDecisionReason":...}} to block; or additionalContext to advise; or {}.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from thrift_common import cfg, enabled, read_stdin_json, emit, log_event  # noqa: E402

# Deterministic signal. Mechanical = pattern-work a cheaper tier does as well.
MECHANICAL = (
    "rename", "move ", "copy ", "format", "lint", "reformat", "boilerplate",
    "scaffold", "list all", "count ", "grep", "find all", "search for",
    "bulk", "sweep", "mechanical", "migrate the string", "rename the", "stub out",
    "run the test", "run tests", "collect the", "gather the", "tally", "inventory",
    "extract the list", "enumerate", "glob", "fetch the", "download",
)
# Reasoning = keep on the strong tier; presence here vetoes a mechanical match.
REASONING = (
    "design", "architect", "prove", "root cause", "why does", "debug ",
    "security", "vulnerab", "mechanism", "trade-off", "tradeoff", "analyze whether",
    "review the", "audit ", "reason about", "strategy", "decide ", "evaluate whether",
    "refactor safely", "correctness", "edge case", "adversar",
)


def classify(text):
    t = (text or "").lower()
    if any(k in t for k in REASONING):
        return "reasoning"
    if any(k in t for k in MECHANICAL):
        return "mechanical"
    return "ambiguous"


def main():
    if not enabled() or not cfg("tier_route_enabled"):
        return emit()
    data = read_stdin_json()
    if (data.get("tool_name") or "") != "Agent":
        return emit()
    ti = data.get("tool_input") or {}
    prompt = " ".join(str(ti.get(k, "")) for k in ("prompt", "description"))
    model = str(ti.get("model", "")).lower()

    # already cheap, or empty -> nothing to do
    if model in ("haiku", "sonnet") or not prompt.strip():
        return emit()

    kind = classify(prompt)
    if kind != "mechanical":
        return emit()

    log_event("tier_route", {"kind": kind, "model": model or "(default)",
                             "strict": bool(cfg("tier_route_strict"))})

    if cfg("tier_route_strict"):
        return emit({"hookSpecificOutput": {
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "[THRIFT strict] This looks like mechanical/bulk work but is being "
                "delegated on the default (opus) tier. Re-spawn with model: \"haiku\" "
                "(or \"sonnet\") -- cheaper tiers do pattern-work as well and keep opus "
                "off bulk tasks. If it genuinely needs opus reasoning, set model: "
                "\"opus\" explicitly to override."
            )}})

    return emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": (
            "[THRIFT] This delegated task reads as mechanical/bulk. Consider spawning "
            "it with model: \"haiku\" or \"sonnet\" -- the audit showed ~0% work offloaded "
            "to cheaper tiers, and mechanical work does not need opus. Keep opus only if "
            "the task genuinely needs reasoning."
        )}})


if __name__ == "__main__":
    main()
