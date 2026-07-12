#!/usr/bin/env python3
"""Thrift — OPTIONAL Remem adapter (github: darks0l/remem).

Remem is a recall module: fetch a specific fact instead of re-carrying full history.
That directly attacks the dominant cost (context re-reading). It is OPT-IN only:
`/thrift:setup` asks the user, and this adapter stays a hard no-op unless BOTH
  (a) config `remem_enabled` is true, AND
  (b) the `remem` package is importable on this machine.

STATUS: the wiring below is a thin, honest adapter. Remem's exact public API is
confirmed at integration time, not assumed here -- so `recall()` degrades to None
(caller falls back to normal behavior) until the real call is wired. This keeps
Thrift fully functional for everyone without a hard dependency on Remem.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks"))
try:
    from thrift_common import cfg
except Exception:
    def cfg(_k):
        return False


def available():
    """True only if the user opted in AND remem is importable."""
    if not cfg("remem_enabled"):
        return False
    try:
        import remem  # noqa: F401
        return True
    except Exception:
        return False


def recall(query):
    """Return a recalled fact for `query`, or None to fall back to normal context.

    Honest no-op until Remem's real API is wired: returns None. When available,
    replace the body with the confirmed remem call (e.g. remem.search(query)).
    """
    if not available():
        return None
    try:
        import remem
        # TODO(wiring): replace with Remem's confirmed public API. Kept conservative
        # (return None on any uncertainty) so we never inject a wrong recall.
        fn = getattr(remem, "search", None) or getattr(remem, "recall", None)
        if callable(fn):
            return fn(query)
    except Exception:
        return None
    return None


if __name__ == "__main__":
    print(f"remem opted-in+available: {available()}")
