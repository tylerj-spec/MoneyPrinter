# Model & Effort Tiering — Money Printer

The principle from tonight's Codex incident: **reasoning cost should track judgment content, not task importance.** A task can be critical and still be mechanical (fetching data correctly matters enormously; deciding *how* to fetch it requires no judgment). Assign by the second property, not the first.

Two axes: **model** (capability ceiling) and **effort** (how hard it reasons within that model). Getting effort right often matters more than model choice — Opus at low effort can underperform Sonnet at high effort on a genuinely hard problem, and Opus at high effort on a mechanical task is pure waste.

---

## Tier definitions

| Tier | Model | Effort | Use when |
|---|---|---|---|
| **Cheap** | Haiku, or no model at all (plain script) | Low / none | Right answer is defined by a spec, not judgment. Errors are cheap to catch (tests fail loudly). |
| **Mid** | Sonnet | Medium | Implementing an already-designed contract. Some local judgment (edge cases, naming) but no architectural decisions. |
| **Expensive** | Opus | High | Design under ambiguity, adversarial review, catching a failure mode nobody specified, anything where a wrong answer is *quiet* rather than loud. |

The dangerous category is the last one: **Opus-worthy problems often look Sonnet-sized until they aren't.** The noise-floor harness looked like "write a permutation test" — Sonnet-sized — until the actual question became "how do I know this instrument doesn't lie to me," which is Opus-sized. When in doubt, spend the tier that fails loudly if wrong; that's usually the higher one for anything touching correctness of the risk gates or the no-lookahead guarantees.

---

## Task-by-task assignment

### Cheap — Haiku or plain script, no meaningful reasoning
- Running `fetch_data.py`, `run_all.py` — these are scripts, not reasoning tasks. Zero model needed.
- Downloading/normalizing bars and chains into the existing schema (schema is fixed; this is transcription)
- Formatting, renaming, moving files within agreed directory ownership
- Posting a pre-written Slack message
- Checking whether a scheduled run's test count matches expectation (diff two numbers)

### Mid — Sonnet, medium effort
- Implementing the 4-way train/tune/calibration/test split — the split *logic* is specified in V0.2; this is coding to spec
- Implementing the DISPUTED lineage state machine — schema is already fully specified in V0.2 §3
- Writing tests for either of the above, once the shape of the code exists
- Wiring the Yahoo adapter output into the point-in-time store — mechanical integration of two already-tested pieces
- Drafting a first-pass Slack message to the specialists when the ask is well-defined (I did this tonight at high effort; most of it didn't need to be)
- Codex's day-to-day ingestion and normalization work, generally — this is where last night's spend was misallocated

### Expensive — Opus, high effort
- **Option valuation/exit contract (D)** — genuine modeling choice under real uncertainty (which spot/IV path model, why it's defensible with thin data). This is why it's stalled for four rounds; it's the hardest open item and shouldn't be rushed at a lower tier just to close it.
- **Audit packet design (F)** — designing what "genuinely blind round 1" means is a judgment call with a failure mode that's invisible until someone tries to cheat it.
- Calibration methodology — deciding whether stated probabilities are honest is exactly the kind of quiet-failure problem this tier exists for.
- **Results devil's advocate** — by design, must be a different model than whatever produced the result, and needs to be as strong as the model it's checking, or it'll rubber-stamp.
- Architecture and blueprint revisions
- Anything touching the risk gates, the no-lookahead guarantees, or position sizing — these are the load-bearing walls. A quiet bug here is the whole project's failure mode.
- Reviewing a backtest result before believing it. This is the highest-value place to spend tokens in the entire pipeline — a good-looking number is exactly when the temptation to under-scrutinize is strongest.

---

## For the scheduled overnight runs specifically

Since the scheduler can't be assigned a model per-task, the overnight hourly runs will execute on whatever model the desktop app is set to. Practical guidance:

- **If left on Sonnet:** appropriate for most of the "Mid" list above — the 4-way split, the lineage state machine, wiring adapters. Not appropriate for D or F; if a run reaches one of those with nothing else to do, it should say so honestly in the STATE.md run log rather than force a design decision at the wrong tier.
- **Reserve Opus for when you're back**, specifically for: reviewing what the overnight runs produced, D and F if the specialists are still silent, and anything the run log flags as "needed Tyler" or "needed a harder call than this session should make."

---

## The one-line rule to keep

**If a wrong answer would be caught by a test failing, it's Cheap or Mid. If a wrong answer would look fine and be wrong, it's Expensive.** Everything in this project's risk gates, no-lookahead store, and option economics falls in the second category by design — that's not an accident, it's why those specific things got built carefully tonight instead of fast.
