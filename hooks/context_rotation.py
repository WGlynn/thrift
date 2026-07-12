#!/usr/bin/env python3
"""Thrift Lever 2 — context rotation (Stop hook). THE money lever.

The measured fact: ~96% of Claude Code spend is the model re-reading conversation
history, and cost scales with context size every turn. A session that drifts to
700k-900k pays that on every message. This hook watches the live context size and,
at configurable tiers, writes a portable handoff and RECOMMENDS rotating to a fresh
session -- where the cost per turn resets.

Elastic, never coercive (this is the load-bearing design choice):
  WARN tier        -> handoff saved, "CLEAR TO CONTINUE". Rotate only if low-value.
  DELIBERATE tier  -> continue only for high-value live work; state a value-check.
  CEILING tier     -> recommend rotating even mid-thread; honor an explicit override.

It never forces a rotation out of a critical thread -- it makes the cheap path
visible and easy, and leaves the value judgment to the human/model. Fail-open:
any error returns silently and never breaks the session.

Stop-hook contract (confirmed): emit {"decision":"block","reason":...} to inject a
message, or {} for silent. additionalContext is NOT allowed on Stop (schema reject).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from thrift_common import (  # noqa: E402
    cfg, enabled, ensure_dirs, read_stdin_json, emit, context_tokens,
    HANDOFF_DIR, STATE_DIR, log_event,
)

SKIP_MARKERS = (
    "hook additional context", "system-reminder", "stop_hook_active",
    "[CLOCK]", "[DEEP RECALL", "[ANTICIPATION", "[ARCHIVE RECALL",
)


def recent_user_turns(tp, n=6):
    out = []
    try:
        import json
        with open(tp, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 500_000))
            chunk = f.read().decode("utf-8", "replace")
        for line in reversed(chunk.splitlines()):
            if '"user"' not in line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("type") != "user":
                continue
            c = (j.get("message") or {}).get("content")
            text = c if isinstance(c, str) else ""
            if isinstance(c, list):
                text = "".join(
                    p.get("text", "") for p in c
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            text = text.strip()
            if not text or text[0] in "<{" or any(m in text for m in SKIP_MARKERS):
                continue
            out.append(text[:280])
            if len(out) >= n:
                break
    except Exception:
        pass
    return list(reversed(out))


def write_handoff(sid, ctx, cwd, tier, tp):
    ensure_dirs()
    turns = recent_user_turns(tp)
    lines = [
        "# Thrift auto-handoff (deterministic, machine-written)",
        "",
        "> Written by Thrift Lever 2 so a fresh session can resume with a small",
        "> context footprint. Paste this (or just its next-steps) into a new chat.",
        "",
        f"- session: {sid}",
        f"- context at write: ~{ctx // 1000}k tokens (tier {tier})",
        f"- cwd: {cwd or '(unknown)'}",
        "",
        "## Recent user turns (oldest -> newest)",
    ]
    lines += [f"{i+1}. {t}" for i, t in enumerate(turns)] or ["(none extractable)"]
    txt = "\n".join(lines) + "\n"
    for name in ("LATEST.md", f"{sid}.md"):
        try:
            with open(os.path.join(HANDOFF_DIR, name), "w", encoding="utf-8") as f:
                f.write(txt)
        except Exception:
            pass


HANDOFF_NOTE = (
    "A portable handoff was saved to ~/.claude/.thrift/handoff/LATEST.md. "
    "Never put secrets/tokens/PII in a handoff."
)


def reason_for(tier, k, warn, deliberate, ceiling):
    if tier == "warn":
        return (
            f"[THRIFT] Context ~{k}k (>= {warn // 1000}k warn tier). {HANDOFF_NOTE} "
            "You are CLEAR TO CONTINUE -- rotation is available, not required. If this "
            "thread is winding down or cleanly resumable, tell the user context is "
            f"~{k}k and a fresh session would cost far less per turn. If it is a live, "
            "high-value thread, keep going; do not yank the user out of critical work."
        )
    if tier == "deliberate":
        return (
            f"[THRIFT] Context ~{k}k (>= {deliberate // 1000}k deliberate tier). "
            f"{HANDOFF_NOTE} Continue only for genuinely high-value live work, and state "
            "a one-line value-check when you do. If routine/resumable, recommend rotating "
            "now: every turn re-reads ~{k}k, so a fresh session is materially cheaper."
        )
    return (
        f"[THRIFT] Context ~{k}k (>= {ceiling // 1000}k ceiling). {HANDOFF_NOTE} "
        "Recommend the user rotate to a fresh session even mid-thread -- per-turn cost "
        "and coherence both degrade here. Continue only on an explicit override."
    )


def main():
    if not enabled():
        return emit()
    data = read_stdin_json()
    sid = data.get("session_id") or ""
    tp = data.get("transcript_path") or ""
    cwd = data.get("cwd") or ""
    if not sid or not tp:
        return emit()

    warn = int(cfg("rotate_warn"))
    deliberate = int(cfg("rotate_deliberate"))
    ceiling = int(cfg("rotate_ceiling"))
    step = int(cfg("rotate_step"))

    ctx = context_tokens(tp)
    if ctx < warn:
        return emit()

    tier = "ceiling" if ctx >= ceiling else "deliberate" if ctx >= deliberate else "warn"
    ensure_dirs()

    # Deterministic handoff refresh every >= one step of growth (never starved).
    lw = os.path.join(STATE_DIR, f"{sid}.lastwrite")
    try:
        last = int(open(lw).read().strip())
    except Exception:
        last = 0
    if last == 0 or (ctx - last) >= step:
        write_handoff(sid, ctx, cwd, tier, tp)
        try:
            open(lw, "w").write(str(ctx))
        except Exception:
            pass

    # Respect the continuation loop; surface the model-facing note once per step.
    if data.get("stop_hook_active"):
        return emit()
    marker = os.path.join(STATE_DIR, f"{sid}.step{ctx // step}")
    if os.path.exists(marker):
        return emit()
    try:
        open(marker, "w").write(str(ctx))
    except Exception:
        pass

    log_event("rotation", {"sid": sid, "ctx": ctx, "tier": tier})
    emit({"decision": "block", "reason": reason_for(tier, ctx // 1000, warn, deliberate, ceiling)})


if __name__ == "__main__":
    main()
