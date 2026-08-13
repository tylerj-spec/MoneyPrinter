# Morning Actions — Tyler

Rewritten 2026-08-13 ~00:50 CDT, replacing the earlier version — enough changed since 23:45 (fetch script, EODHD, credential handling, token discipline) that patching it would've been confusing. This is current.

Everything here is something **only you can do.** I've excluded anything I could do myself.

---

## Do these, in order

### 1. Rotate the EODHD token (2 min)
You pasted it into chat. Low actual risk on a free market-data key, but free tiers become paid tiers with the same string attached, so do it next time you're in the dashboard. Not urgent — just don't skip it.

### 2. Set the token properly, once (2 min)
```
setx EODHD_API_TOKEN "your-new-token"
```
Open a **new** terminal after (`setx` doesn't affect the current one). Verify without printing it:
```
python -c "import os;print('set:', bool(os.environ.get('EODHD_API_TOKEN')))"
```

### 3. Run the free data fetch (5 min)
```
pip install yfinance
cd mp_v01
python fetch_data.py --chains
```
Pulls free SPY/QQQ/MSFT daily bars back to 2019, plus a snapshot of today's option chain. Costs nothing, no account needed. Re-run `--chains` daily if you want — that's the only way to build point-in-time options history for free, since Yahoo has no historical chains.

### 4. Run the test suite (2 min) — your QC of my work
```
python run_all.py
```
Expect passing, `ALL GREEN`. If anything fails, that's the first thing to tell me.

### 5. Check overnight progress (5 min)
Read `STATE.md` → `## Run log` section at the bottom for what each hourly run actually did. Read any new `AGENT_ROUND_*.md` files. Don't reread the older docs — STATE.md is now the current source of truth.

### 6. Delete or disable the overnight schedule (1 min)
It runs hourly 1–11 AM **and recurs daily** since it's a cron schedule. If you don't want it firing again tonight, delete it from the Scheduled sidebar, or ask me to when you're back.

### 7. Read `MODEL_TIERING.md` and confirm the assignment (5 min)
New doc — maps every remaining task to Haiku/Sonnet/Opus and an effort level, with the reasoning. Worth five minutes because it's the thing that'll keep future sessions from burning credits on mechanical work the way tonight's Codex session did.

### 8. Diagnose the two silent specialists (10 min)
`options_research` and `bear_audit` haven't answered in 4 rounds. Post in `#all-money-printer` mentioning only the options subteam tag with a trivial question. If it answers, my multi-tag rounds were the problem. If not, the persona or the app quota is.

---

## Don't do yet
Buy deep historical options data, buy hardware, add Grok or a third model, open a brokerage account, or fund the $1,000 — all previously covered, nothing's changed on these.

---

## Where things actually stand

76 tests passing. Point-in-time store, label contract v1.0, cost model, walk-forward, a noise-floor harness validated against both random data and a planted signal, deterministic risk gates, free and paid data adapters. No real data ingested yet (waiting on you running the fetch script — my sandbox has no network), no strategy, no alpha.

The honest gate ahead: run the fetch script, then have a session evaluate the noise floor on *real* SPY/QQQ/MSFT bars instead of synthetic data. That result — not another spec round — is what tells you whether there's anything here worth spending more money on.
