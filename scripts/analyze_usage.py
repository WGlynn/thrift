#!/usr/bin/env python3
"""Analyze Claude Code token usage from local session transcripts."""
import json, os, glob, sys
from datetime import datetime, timedelta, timezone
from collections import defaultdict

ROOT = os.path.expanduser("~/.claude/projects")
files = glob.glob(ROOT + "/*/*.jsonl")

# pricing per 1M tokens: (input, output, cache_write, cache_read)
def price(model):
    m = model or ""
    if "fable" in m:            return (10, 50, 12.5, 1.0)
    if "opus-4-1" in m or "opus-4-2" in m or "claude-3-opus" in m: return (15, 75, 18.75, 1.5)
    if "opus" in m:             return (5, 25, 6.25, 0.5)
    if "sonnet" in m:           return (3, 15, 3.75, 0.30)
    if "haiku" in m:            return (1, 5, 1.25, 0.10)
    return (5, 25, 6.25, 0.5)

def fam(model):
    m = model or "?"
    if "fable" in m: return "fable-5"
    if "opus" in m:
        for v in ("4-8","4-7","4-6","4-5","4-1"):
            if "opus-"+v in m: return "opus-"+v
        return "opus-?"
    if "sonnet" in m: return "sonnet"
    if "haiku" in m: return "haiku"
    return m[:20]

seen = set()
rows = []  # per unique assistant message
sess = {}  # sessionId -> stats
parse_errors = 0

for f in files:
    project = os.path.basename(os.path.dirname(f)).replace("-Users-a420-", "")
    with open(f, errors="replace") as fh:
        for line in fh:
            try:
                j = json.loads(line)
            except Exception:
                parse_errors += 1
                continue
            if j.get("type") != "assistant":
                continue
            msg = j.get("message") or {}
            u = msg.get("usage")
            model = msg.get("model", "")
            if not u or model == "<synthetic>":
                continue
            mid = msg.get("id") or j.get("requestId") or j.get("uuid")
            if mid in seen:
                continue
            seen.add(mid)
            ts = j.get("timestamp")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
            except Exception:
                continue
            inp = u.get("input_tokens", 0) or 0
            cc = u.get("cache_creation_input_tokens", 0) or 0
            cr = u.get("cache_read_input_tokens", 0) or 0
            out = u.get("output_tokens", 0) or 0
            p = price(model)
            cost = (inp*p[0] + out*p[1] + cc*p[2] + cr*p[3]) / 1e6
            side = bool(j.get("isSidechain"))
            sid = j.get("sessionId") or os.path.basename(f)[:-6]
            rows.append((dt, project, sid, fam(model), inp, cc, cr, out, cost, side))
            s = sess.setdefault(sid, dict(project=project, first=dt, last=dt, n=0,
                                          cost=0.0, peak_ctx=0, first_ctx=None,
                                          side_n=0, models=set()))
            s["first"] = min(s["first"], dt); s["last"] = max(s["last"], dt)
            s["n"] += 1; s["cost"] += cost
            ctx = inp + cc + cr
            s["peak_ctx"] = max(s["peak_ctx"], ctx)
            if not side and s["first_ctx"] is None:
                s["first_ctx"] = ctx
            if side: s["side_n"] += 1
            s["models"].add(fam(model))

rows.sort(key=lambda r: r[0])
now = datetime.now().astimezone()
print(f"=== PARSED: {len(rows)} unique API calls across {len(sess)} sessions, {len(files)} files (parse_errors={parse_errors}) ===")
if not rows:
    sys.exit(0)
print(f"date range: {rows[0][0]:%Y-%m-%d} .. {rows[-1][0]:%Y-%m-%d}\n")

def agg(rs):
    inp = sum(r[4] for r in rs); cc = sum(r[5] for r in rs)
    cr = sum(r[6] for r in rs); out = sum(r[7] for r in rs)
    cost = sum(r[8] for r in rs)
    return inp, cc, cr, out, cost

# ---- weekly aggregates (ISO week, all time) ----
print("=== WEEKLY (all traffic; $ = API-equivalent value, the proxy for plan-limit burn) ===")
wk = defaultdict(list)
for r in rows:
    wk[r[0].strftime("%G-W%V")].append(r)
print(f"{'week':<10}{'calls':>7}{'input':>10}{'cache_wr':>11}{'cache_rd':>13}{'output':>9}{'est$':>9}")
for k in sorted(wk):
    i,c,cr,o,cost = agg(wk[k])
    print(f"{k:<10}{len(wk[k]):>7}{i:>10,}{c:>11,}{cr:>13,}{o:>9,}{cost:>9.2f}")

# ---- last 30 days daily ----
print("\n=== DAILY, LAST 21 DAYS ===")
cutoff = now - timedelta(days=21)
day = defaultdict(list)
for r in rows:
    if r[0] >= cutoff: day[r[0].strftime("%Y-%m-%d %a")].append(r)
print(f"{'day':<15}{'calls':>7}{'sess':>6}{'cache_rd':>13}{'cache_wr':>11}{'output':>9}{'est$':>9}")
for k in sorted(day):
    rs = day[k]
    i,c,cr,o,cost = agg(rs)
    ns = len(set(r[2] for r in rs))
    print(f"{k:<15}{len(rs):>7}{ns:>6}{cr:>13,}{c:>11,}{o:>9,}{cost:>9.2f}")

# ---- model mix last 30d ----
print("\n=== MODEL MIX (last 30 days) ===")
cutoff30 = now - timedelta(days=30)
md = defaultdict(list)
for r in rows:
    if r[0] >= cutoff30: md[r[3]].append(r)
tot30 = sum(agg(v)[4] for v in md.values()) or 1
for k in sorted(md, key=lambda k: -agg(md[k])[4]):
    i,c,cr,o,cost = agg(md[k])
    print(f"{k:<12} calls={len(md[k]):>6}  est$={cost:>8.2f}  ({100*cost/tot30:4.1f}%)  out_tok={o:,}")

# ---- per-project last 30d ----
print("\n=== BY PROJECT (last 30 days) ===")
pj = defaultdict(list)
for r in rows:
    if r[0] >= cutoff30: pj[r[1]].append(r)
for k in sorted(pj, key=lambda k: -agg(pj[k])[4])[:8]:
    i,c,cr,o,cost = agg(pj[k])
    ns = len(set(r[2] for r in pj[k]))
    print(f"{k[:46]:<48} sess={ns:>4} calls={len(pj[k]):>6} est$={cost:>8.2f}")

# ---- sidechain share last 30d ----
side = [r for r in rows if r[0] >= cutoff30 and r[9]]
main = [r for r in rows if r[0] >= cutoff30 and not r[9]]
sc, mc = agg(side)[4], agg(main)[4]
print(f"\n=== SUBAGENT (sidechain) SHARE last 30d: ${sc:.2f} of ${sc+mc:.2f} ({100*sc/max(sc+mc,0.01):.1f}%) ===")

# ---- top sessions by cost ----
print("\n=== TOP 12 SESSIONS BY EST $ (all time) ===")
print(f"{'date':<11}{'project':<38}{'turns':>6}{'hrs':>6}{'peak_ctx':>10}{'side%':>7}{'est$':>9}")
for sid, s in sorted(sess.items(), key=lambda kv: -kv[1]["cost"])[:12]:
    hrs = (s["last"] - s["first"]).total_seconds()/3600
    sp = 100*s["side_n"]/max(s["n"],1)
    print(f"{s['first']:%Y-%m-%d } {s['project'][:36]:<38}{s['n']:>6}{hrs:>6.1f}{s['peak_ctx']:>10,}{sp:>6.0f}%{s['cost']:>9.2f}")

# ---- context size distribution last 30d (main chain only) ----
print("\n=== PER-CALL CONTEXT SIZE (input+cache_rd+cache_wr), last 30d main chain ===")
ctxs = sorted(r[4]+r[5]+r[6] for r in main)
if ctxs:
    def pct(p): return ctxs[min(int(p/100*len(ctxs)), len(ctxs)-1)]
    print(f"n={len(ctxs)}  p50={pct(50):,}  p75={pct(75):,}  p90={pct(90):,}  p99={pct(99):,}  max={ctxs[-1]:,}")
    big = sum(1 for c in ctxs if c > 100_000)
    print(f"calls with context >100k tokens: {big} ({100*big/len(ctxs):.1f}%)")

# ---- session startup context (first call of session) last 30d ----
fc = [s["first_ctx"] for s in sess.values() if s["first_ctx"] and s["first"] >= cutoff30]
fc.sort()
if fc:
    print(f"\n=== SESSION STARTUP CONTEXT (first call) last 30d: n={len(fc)} median={fc[len(fc)//2]:,} p90={fc[int(0.9*len(fc))-1]:,} ===")

# ---- hottest 5-hour windows last 30d (the 5h rolling limit) ----
print("\n=== HOTTEST 5-HOUR WINDOWS (last 30 days) ===")
hour = defaultdict(float)
for r in rows:
    if r[0] >= cutoff30:
        hour[r[0].replace(minute=0, second=0, microsecond=0)] += r[8]
hours = sorted(hour)
best = []
for h in hours:
    tot = sum(hour.get(h + timedelta(hours=k), 0) for k in range(5))
    best.append((tot, h))
best.sort(reverse=True)
shown = []
for tot, h in best:
    if any(abs((h - h2).total_seconds()) < 5*3600 for _, h2 in shown):
        continue
    shown.append((tot, h))
    if len(shown) >= 6: break
for tot, h in shown:
    print(f"{h:%Y-%m-%d %a %H:%M} → {(h+timedelta(hours=5)):%H:%M}   est ${tot:.2f}")

# ---- sessions per day with >1 concurrent ----
print("\n=== TOTALS ===")
i,c,cr,o,cost = agg(rows)
print(f"all-time: input={i:,} cache_wr={c:,} cache_rd={cr:,} output={o:,}  est ${cost:.2f}")
r30 = [r for r in rows if r[0] >= cutoff30]
i,c,cr,o,cost = agg(r30)
print(f"last 30d: input={i:,} cache_wr={c:,} cache_rd={cr:,} output={o:,}  est ${cost:.2f}")
r7 = [r for r in rows if r[0] >= now - timedelta(days=7)]
i,c,cr,o,cost = agg(r7)
print(f"last  7d: input={i:,} cache_wr={c:,} cache_rd={cr:,} output={o:,}  est ${cost:.2f}")
