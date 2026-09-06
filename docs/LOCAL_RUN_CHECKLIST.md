# Windows local-run checklist

Review the stacked drafts in order 11 -> 12 -> 13 -> 14 -> 15. Merge the lower PR first, then retarget the next PR to main and wait for its new checks. Nothing is merged automatically. Do not force-reset your checkout or overwrite private data.

## 1. Back up your data and update the checkout

Close MoneyPrinter and copy the complete output folder to a private backup. Include data_store, picks, external, paper, replays and experiments when present. Keep raw vendor data out of GitHub. SQLite must be closed before copying.

Open PowerShell:

```powershell
Set-Location 'C:\Users\tyler\OneDrive\Documents\GitHub\MoneyPrinter'
git status --short
git fetch origin
```

If status lists changes, preserve them before switching. After all merges, run `git switch main` and `git pull --ff-only`. To test the unmerged stack, first check out `git switch --track origin/review/pr15-predictive-refinement`. If the local review branch already exists, use `git switch review/pr15-predictive-refinement` followed by `git pull --ff-only` instead. Stop rather than forcing a diverged branch.

## 2. One Python environment

```powershell
py -3 -m venv .venv
$Py = Join-Path (Get-Location) '.venv\Scripts\python.exe'
& $Py -m pip install --upgrade pip
& $Py -m pip install yfinance openpyxl tzdata
& $Py -c "from app_paths import get_paths; print(get_paths().root)"
```

Keep the printed data root unless intentionally migrating. Defaults/saved settings are honored. `MONEYPRINTER_HOME` is an optional environment override, not an automatic migration. The new app uses local files outside the code checkout; do not assume the legacy folder-change helper copies every new runtime directory.

## 3. Run the tests, preserving the result

```powershell
$DataHome = & $Py -c "from app_paths import get_paths; print(get_paths().root)"
New-Item -ItemType Directory -Force (Join-Path $DataHome 'logs') | Out-Null
$env:MONEYPRINTER_REQUIRE_GUI_TESTS = '1'
& $Py -X utf8 .\run_tests.py 2>&1 | Tee-Object -FilePath (Join-Path $DataHome 'logs\local-tests.log')
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; keep the log and stop.' }
```

GUI test windows may appear briefly. Do not close them. CI also exercises Windows Python 3.14, Windows 3.12, and Linux 3.10/3.11/3.12.

## 4. Check the offline research tools

```powershell
& $Py -X utf8 .\replay_options.py --demo
& $Py -X utf8 .\refine_model.py --demo
```

These are synthetic tests, not historical market performance. Open the replay's `review.html` and `review_1.html` to inspect short justifications, weighted indicators, contract alternatives and exact decision-time input files. Synthetic runs do not qualify a model for promotion and do not change active weights.

## 5. Open the integrated app

```powershell
& $Py -X utf8 .\app.py
```

Use **Data and review -> Data sources and API keys**. New source credentials are masked and session-only. Massive retains its existing main-window key box. Do not paste keys into chat, GitHub, screenshots or logs. `run_gui.bat` also starts the integrated app; `gui.py` alone is the older base interface.

## 6. Start free and without accounts

```powershell
& $Py -X utf8 .\collect_data.py public
& $Py -X utf8 .\collect_data.py status
```

This requests BLS release-calendar data, Fed monetary-policy RSS, and one BLS CPI series. Every successful response creates a new raw/normalized local vintage. Network failures preserve old data. Do not repeatedly retry rate limits or run collectors concurrently with the same key.

## 7. Add optional credentials locally

| Provider | Enter | Scope/default | Limit |
|---|---|---|---|
| SEC | SEC_USER_AGENT: your name and contact email, not an API key | Numeric CIK, default 0000320193 | Recent submissions only |
| FRED/ALFRED | FRED_API_KEY from a free account | DGS10, optionally explicit vintage date | A vintage is not proof of intraday release availability |
| Tradier | TRADIER_API_KEY | SPY or a provider contract symbol | Sandbox delayed; production needs brokerage access |
| Alpaca | APCA_API_KEY_ID and APCA_API_SECRET_KEY | SPY | Explicitly indicative, bounded first page, not executable OPRA quotes |
| Massive | MASSIVE_API_KEY in existing box | Existing diagnostic | Reference access does not establish historical quote entitlement |

A terminal alternative for the new providers is `collect_data.py fred --scope DGS10 --prompt-keys`. The hidden prompt refuses echo fallback. For Massive:

```powershell
& $Py -X utf8 .\fetch_massive.py --diagnose --tickers SPY --as-of 2025-08-01 --prompt-key
```

No subscription is purchased by the app. Paid ThetaData, ORATS, Massive quote history and Alpaca consolidated feeds remain future evaluation notes.

## 8. Generate and inspect picks

Use the existing fetch -> generate -> score buttons. A forward pick requires a same-day chain already available by the 15:45 Eastern cutoff. Weekends/stale snapshots should abstain; do not backdate a forward pick to force a result.

Use **Why this pick?** to review the latest frozen file or choose a historical replay record. The explanation gives a short summary, actual indicator contributions, contract economics, selection policy, failed gates and source identities. It describes the rule, not a guaranteed profit or causal explanation.

Historical replay requires a separately supplied, schema-valid local quote dataset. The free collectors do not magically provide complete historical NBBO. Replay uses scheduled exits and separate one-contract policy comparisons; it is not a combined portfolio or intraday stop/target backtest.

## 9. Persistent paper account

```powershell
& $Py -X utf8 .\paper_trading.py init --cash 1000
& $Py -X utf8 .\paper_trading.py status
```

Initialization never resets an existing ledger. Orders/quotes are explicit local simulation commands, not broker submissions. Cash reservations, fees, partial fills, duplicate protection and strict risk limits apply. A $1,000 account may be too small for many contracts under a 2% limit; the app does not relax limits automatically.

## 10. Prepare outputs to send back

```powershell
& $Py -X utf8 .\export_research.py
& $Py -X utf8 .\feedback_bundle.py
```

Review the feedback ZIP before attaching it. It includes version and counts, not raw data or credentials, and nothing uploads automatically. Send that ZIP and the reviewed local test log first. For strategy refinement, separately review/share a frozen pick JSON and research inputs.jsonl, outcomes.jsonl and manifest.json. Detailed records may include local paths and licensed prices: check privacy and sharing rights before uploading. Never send the whole output folder by default.

Downloaded current data and manual imports are not silently backdated to their observation period. Keep modelled/untimed outcomes separate from observed quote evidence. New data collection does not automatically change prediction weights. These changes remain paper/research tools, not demonstrated profitable trading software.
