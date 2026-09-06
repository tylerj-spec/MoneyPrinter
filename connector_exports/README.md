# OptionsCalc connector exports

These JSON files preserve the values returned by the OptionsCalc connector for
local inspection. They are intentionally separate from `data/chains/` because
the connector output does not include the two-sided quotes, volume, open
interest, and observation timestamps required by MoneyPrinter's option-chain
adapter and risk screens.

Inspect the current export from the repository root:

```powershell
Get-Content .\connector_exports\optionscalc_spy_20260906.json | ConvertFrom-Json | Format-List
```

Or load it in Python:

```powershell
python -c "import json; from pathlib import Path; p=Path('connector_exports/optionscalc_spy_20260906.json'); d=json.loads(p.read_text()); print(json.dumps(d, indent=2))"
```

Do not copy this file into `data/chains/` or treat its refreshed marks as bid/ask
quotes. Use `fetch_data.py --chains` for a compatible forward snapshot, or the
Massive adapter when the API key proves access to all required fields.
