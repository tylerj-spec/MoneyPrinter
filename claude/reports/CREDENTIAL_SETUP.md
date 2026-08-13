# Credential Setup — do this first thing

## Rotate the EODHD token

You pasted an API token into the chat window. It's now in that conversation's transcript. I did not write it to any file, Slack message, or scheduled task, and it does not appear anywhere in the codebase.

**Rotate it in your EODHD dashboard anyway.** Rotation is free. A leaked key on a paid account is not, and you have no way to know where a transcript ends up. This is also your own project rule — *"Secrets stay in environment variables or a secret manager and never appear in prompts, logs, or reports"* — and it's a good one.

Not a scolding, just the cheap fix: rotate, then use the method below and the new token never touches a chat window.

## Store the new token properly

Windows, one time:

```
setx EODHD_API_TOKEN "your-new-token-here"
```

Then **open a new terminal** — `setx` only affects sessions started after it runs.

Verify it's set without printing it:

```
python -c "import os;print('token set:', bool(os.environ.get('EODHD_API_TOKEN')))"
```

That prints `True` or `False`, never the value. Get in the habit — a token echoed into a terminal ends up in shell history, and shell history ends up in screenshots.

## What the code does with it

`src/adapters/eodhd_options.py` reads `EODHD_API_TOKEN` from the environment and nothing else. Specifically:

- The token is never a function argument, so it can't surface in a traceback
- Never written to a manifest, log, or report
- A `redact()` function scrubs it from any string before it can be logged — **this matters more than it sounds.** HTTP libraries routinely include the full request URL in exception messages, and the token is a URL query parameter. An unhandled error would otherwise print your key straight into a log file.
- Redaction also catches `api_token=`, `token=`, `apikey=`, and `key=` parameters generically, so it still works if the API changes parameter names

Six tests cover this, including one that deliberately plants the token in a fake error message and asserts it comes out redacted.

If the variable isn't set, the code raises with setup instructions rather than falling back to an empty string and producing a confusing 401.

## Note on what EODHD buys you

Since you already have it: EODHD's option history begins around **Q4 2023** — roughly 2.5 years, which is broadly one market regime. No 2022 bear market, no 2020 volatility shock.

That's genuinely sufficient to **build and validate** the pipeline, which is the current phase. It is **not** sufficient to claim regime robustness, and any result from this window should carry a `single_regime` label until it's tested against deeper history. Worth knowing before a promising-looking backtest tempts anyone to conclude more than the data supports.

The stock-thesis layer still costs nothing — Yahoo daily bars are free and adequate for the entire forecasting layer. EODHD becomes load-bearing only once a stock-level edge exists and you need to price contracts against it.
