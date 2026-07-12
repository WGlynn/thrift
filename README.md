# Thrift — a token-efficiency layer for Claude Code

Thrift is a small Claude Code plugin that cuts token burn with deterministic hooks.
No model is ever called by the plugin itself: **it never costs tokens to save tokens.**

## Why

If you audit where Claude Code spend actually goes (Thrift ships the tool to do it —
`/thrift:token-audit`), the pattern is almost always the same: the large majority of
cost is the model **re-reading conversation history**, and that cost scales with how
big the context has grown, on every single turn. Two other leaks compound it: bulk
work runs on the most expensive model instead of a cheaper one, and multi-step tool
sequences re-read the whole context once per round-trip.

Thrift attacks those three, and nothing else.

## What it does

- **Context rotation (the money lever).** A Stop hook watches live context size and,
  at configurable tiers, writes a portable handoff and *recommends* rotating to a
  fresh session (where per-turn cost resets). It is elastic: it warns and says "clear
  to continue" while a thread is live and valuable, and only urges rotation when the
  thread is winding down or past a ceiling. It never forces you out of critical work.
- **Code-mode gate.** After a burst of same-tool calls (Read/Bash/Grep/Glob) it
  suggests replacing the round-trips with one script that returns the result once.
- **Tier routing.** When clearly-mechanical work is delegated to a subagent on the
  expensive tier, it recommends a cheaper model (`haiku`/`sonnet`). Opt-in strict mode
  blocks until you choose a tier.
- **Usage audit.** `/thrift:token-audit` parses your local transcripts and shows your
  real burn — weekly/daily, by model, by session — so you can measure your own
  before/after. Nothing leaves your machine.
- **Reusable triage helper** (`hooks/triage_lib.py`) for your own loops/crons: a free
  predicate decides whether to wake the model at all.

## Install

```bash
# add this repo as a marketplace (local path or git URL both work)
claude plugin marketplace add <path-to-this-repo-or-git-url>

# install + enable
claude plugin install thrift@thrift
```

Then configure (it **asks** you, including whether to opt into Remem):

```
/thrift:setup
```

Restart Claude Code so the hooks load.

## Configure

`/thrift:setup` writes `~/.claude/.thrift/config.json`. You can also edit that file
directly (copy `thrift.config.example.json`) or set any key via `THRIFT_<KEY>` env var.
Defaults are tuned for a 200k window; on the 1M-context variant, raise the `rotate_*`
tiers. To pause Thrift entirely: `touch ~/.claude/.thrift/DISABLE`.

## Remem (optional, opt-in)

[Remem](https://github.com/darks0l/remem) is a recall module — fetch a specific fact
instead of re-carrying full history. Thrift can use it, but it is **off by default**;
`/thrift:setup` asks whether you want to opt in, and it requires installing Remem
separately. Thrift is fully functional without it.

## Honest limits

- The plugin can gate the tier of *delegated* work; it cannot re-tier the main
  interactive thread. Context rotation is what shrinks the main thread.
- No savings number is promised. Run `/thrift:token-audit` before and after and judge
  for yourself — that is the whole point of shipping the audit tool with it.
- Hooks fail open: any error returns silently and never breaks your session.

MIT licensed.
