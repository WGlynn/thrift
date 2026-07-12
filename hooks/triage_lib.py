#!/usr/bin/env python3
"""Thrift crown jewel — deterministic triage-before-LLM (reusable helper).

The single cheapest token-saver: before an autonomous loop or cron wakes the model,
a free Python predicate decides whether there is anything to do. If not, it logs one
line and hard-stops -- zero model tokens spent on an empty fire. Measured on the
Moltbook loop this cycle: half of all fires skipped the model entirely.

This module makes the pattern reusable. Register named checks (each returns truthy
when work exists); `decide()` prints a JSON manifest + an `LLM-NEEDED: yes|no` line
and returns the manifest. Your loop reads that line and only proceeds on `yes`.

Usage in a cron/loop entrypoint (e.g. my_triage.py):

    from triage_lib import Triage
    t = Triage("myloop")
    t.check("inbox", lambda: count_unread() > 0)
    t.check("queue_low", lambda: stamped_drafts() < 2)
    m = t.decide()          # prints manifest + "LLM-NEEDED: yes|no", returns dict
    # exits 0 either way; your loop prompt inspects the printed line.

A check may return a bool, or an (bool, detail) tuple to enrich the manifest's
`do` map. Any check that raises is treated as "work exists" (fail-safe: never skip
real work to save tokens -- the asymmetry favors doing the work).
"""
import json
import sys


class Triage:
    def __init__(self, name="loop"):
        self.name = name
        self._checks = []

    def check(self, key, fn):
        """Register a named predicate. fn() -> bool | (bool, detail)."""
        self._checks.append((key, fn))
        return self

    def _run_one(self, fn):
        try:
            r = fn()
        except Exception as e:
            return True, f"error:{type(e).__name__} (treated as work-exists)"
        if isinstance(r, tuple):
            return bool(r[0]), r[1]
        return bool(r), None

    def decide(self, emit=True):
        do = {}
        detail = {}
        for key, fn in self._checks:
            hit, det = self._run_one(fn)
            do[key] = hit
            if det is not None:
                detail[key] = det
        needed = any(do.values())
        manifest = {"loop": self.name, "llm_needed": needed, "do": do}
        if detail:
            manifest["detail"] = detail
        if emit:
            print(f"LLM-NEEDED: {'yes' if needed else 'no'}")
            print(json.dumps(manifest))
        return manifest


def _demo():
    # Runnable self-test: no real work -> LLM-NEEDED: no.
    t = Triage("demo")
    t.check("inbox", lambda: False)
    t.check("queue_low", lambda: False)
    m = t.decide()
    sys.exit(0 if m["llm_needed"] is False else 1)


if __name__ == "__main__":
    _demo()
