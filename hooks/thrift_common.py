#!/usr/bin/env python3
"""Thrift — shared helpers for the token-efficiency plugin.

Design law: it must not cost tokens to save tokens. Everything here is pure,
deterministic, and dependency-free (stdlib only). No model is ever invoked.

Config resolution order (first hit wins), per key:
  1. environment variable  (THRIFT_*)
  2. ~/.claude/.thrift/config.json   (user override, friend-editable)
  3. built-in DEFAULTS below

State (logs, handoffs, markers) lives under ~/.claude/.thrift/ so the plugin is
fully self-contained and leaves no trace in the host project.
"""
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".claude", ".thrift")
HANDOFF_DIR = os.path.join(STATE_DIR, "handoff")
LOG_DIR = os.path.join(STATE_DIR, "logs")

# Defaults tuned for a 200k standard context window. Users on the 1M-context
# variant should raise the rotation tiers (env or config). Everything overridable.
DEFAULTS = {
    # Lever 2 — context rotation (elastic; warn low, recommend-with-override high)
    "rotate_warn": 120_000,      # C1: handoff saved, CLEAR TO CONTINUE
    "rotate_deliberate": 160_000,  # C2: continue only for high-value, +value-check
    "rotate_ceiling": 185_000,   # C3: recommend rotate even mid-thread (override honored)
    "rotate_step": 30_000,       # re-surface every N tokens within a tier
    # Lever 3 — code-mode gate
    "codemode_window_s": 120,
    "codemode_threshold": 4,     # >= N same-tool calls in window -> nudge
    "codemode_cooldown_s": 300,
    # Lever 1 — tier routing
    "tier_route_enabled": True,  # recommend a cheaper model for mechanical delegated work
    # master switch
    "enabled": True,
}

_CONFIG_CACHE = None


def _load_config_file():
    p = os.path.join(STATE_DIR, "config.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def cfg(key):
    """Resolve one config value: env > user config.json > DEFAULTS."""
    global _CONFIG_CACHE
    env = os.environ.get("THRIFT_" + key.upper())
    if env is not None:
        default = DEFAULTS.get(key)
        if isinstance(default, bool):
            return env.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            try:
                return int(env)
            except ValueError:
                pass
        return env
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = _load_config_file()
    if key in _CONFIG_CACHE:
        return _CONFIG_CACHE[key]
    return DEFAULTS.get(key)


def enabled():
    """Master kill-switch. A file named DISABLE in the state dir also halts."""
    if os.path.exists(os.path.join(STATE_DIR, "DISABLE")):
        return False
    return bool(cfg("enabled"))


def ensure_dirs():
    for d in (STATE_DIR, HANDOFF_DIR, LOG_DIR):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def read_stdin_json():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def emit(obj=None):
    """Print a hook response (JSON) or an empty object (no-op)."""
    print(json.dumps(obj) if obj else "{}")


def context_tokens(transcript_path):
    """Current context size = the last assistant turn's total input footprint
    (input + cache_read + cache_creation). Reads only the tail of the transcript
    JSONL, so it is O(1)-ish regardless of session length. Returns 0 on any error
    (fail-open: never break the session to save tokens).

    Generalized from the proven JARVIS context-rotation hook.
    """
    if not transcript_path:
        return 0
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 250_000))
            chunk = f.read().decode("utf-8", "replace")
        for line in reversed(chunk.splitlines()):
            if '"usage"' not in line:
                continue
            try:
                j = json.loads(line)
            except Exception:
                continue
            if j.get("type") != "assistant":
                continue
            u = (j.get("message") or {}).get("usage") or {}
            return (
                (u.get("input_tokens") or 0)
                + (u.get("cache_read_input_tokens") or 0)
                + (u.get("cache_creation_input_tokens") or 0)
            )
    except Exception:
        pass
    return 0


def log_event(name, rec):
    """Append a JSONL telemetry line under logs/<name>.jsonl (best-effort)."""
    ensure_dirs()
    rec = dict(rec)
    rec.setdefault("ts", time.time())
    try:
        with open(os.path.join(LOG_DIR, name + ".jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass
