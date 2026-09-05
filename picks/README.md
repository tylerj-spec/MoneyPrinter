# Frozen paper picks

Records now live in `~/MoneyPrinterData/picks/` (or your configured output
folder), outside the code checkout. Each file is one run of `generate_picks.py`: a set of predictions, hashed at
the moment they were written.

**Back up the output folder.** Frozen records cannot be regenerated. The GUI
copies legacy files from this directory on startup, preserving the originals.
CLI users can run `python migrate_outputs.py`.

These files are also the source of the `Pick_History`, `Pick_Justifications`,
`Pick_Performance` and `Pick_Abstentions` tabs in the Excel workbook. That history is
a view over this directory — rebuild the workbook whenever you like and nothing is
lost, but delete a file here and its picks leave the record.

Score one with:

```
python resolve_picks.py ~/MoneyPrinterData/picks/<file>.json
```

The resolver re-hashes the picks first. If the digest does not match, the file
was edited after generation and the record is void — which is the entire reason
the hash is there.

Nothing in a pick file is advice, and none is gate-approved: `gate_decision` reads
`PASS` — do nothing — on every one, because no component in use has a measured
rank information coefficient against forward excess return. They are hypotheses
logged for measurement.
