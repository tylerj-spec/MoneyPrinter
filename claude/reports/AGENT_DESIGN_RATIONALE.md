# Agent Design — what actually reduces hallucination

You said the design goal is agent-specific roles to reduce hallucination. That instinct is right, but the mechanism isn't quite what it looks like, and getting it precise changes the roster.

---

## The uncomfortable part: more agents does not reduce hallucination

Narrow roles help in one specific way — a constrained domain plus a constrained output schema leaves less room to freelance. That part of your instinct is correct and it's working.

But agent *count* is roughly orthogonal to hallucination rate, and past a point it makes things worse:

**Each agent is an independent hallucination source.** Ten agents produce ten opportunities to invent something. Aggregate error goes up with headcount, not down.

**Agents reading each other's output propagate errors.** You saw this exact failure in ORCH-SMOKE-002 last night: the coordinator answered its own delegated question, labeled itself `"agent": "data_lineage"`, and published it as if a specialist had responded. Nothing caught it. That's not a hallucination in the usual sense — it's worse, because it wore the costume of verification.

**Agreement between personas on one model is not verification.** Your six specialists share a base model. When they agree, that's correlated error, not corroboration. It *looks* exactly like independent confirmation, which is precisely the failure mode your evidence-lineage rules were designed to prevent for news sources. The same logic applies to your agents: six personas on one model is one information source, not six.

That last point is the important one. You already built the right principle into the data layer — syndicated copies collapse to one information event. The roster needs the same rule applied to itself.

---

## What actually reduced hallucination last night

Four things, none of which were "more agents":

**1. Forced structured abstention.** Your specialists have mandatory `unknowns` fields and a `BLOCKED` status. When I posted a review request without inlining the document, all six *refused to review it* and said so explicitly. That is the single most valuable behavior in your entire setup. An agent that will say "I cannot see the thing you're asking about" will not invent the thing.

**2. Deterministic code as final authority.** The risk gates are pure functions. No model output can move them. A 95%-confident model still gets PASS on negative post-cost edge — verified by test. Hallucination becomes harmless when it cannot reach a decision.

**3. Cross-*model* checking.** Codex and I are different base models with genuinely uncorrelated failure modes. When Codex and I agree, that means something. When two ChatGPT personas agree, much less.

**4. Fail-closed defaults.** Missing data yields PASS, not a guess. Unknown lineage counts as zero corroboration. Tested.

**The design principle that follows:** hallucination is controlled by *structure* — schemas, abstention, deterministic authority, model diversity — not by headcount. Add agents for **coverage**, add *models* for **verification**.

---

## Coverage map — do we have enough chefs?

The right test isn't "how many agents." It's "is every pipeline stage owned, and is every stage that can produce a wrong number checked by something that isn't its author?"

| Pipeline stage | Owner | Independent check | Gap? |
|---|---|---|---|
| Source permitting / licensing | data_lineage | Claude review | OK |
| Ingestion / fetching | **NOBODY** | — | **REAL GAP** |
| Normalization → records | data_lineage (spec only) | deterministic schema validation | OK |
| Evidence / lineage mapping | data_lineage | bear_audit | OK |
| Point-in-time queries | Claude (implemented) | 14 passing tests | OK |
| Label construction | quant_research (spec) + Claude (built) | 13 passing tests | OK |
| Feature engineering | **NOBODY** | — | **GAP** |
| Stock ranking / forecast | quant_research | Devil's advocate *(to create)* | Partial |
| Calibration | **NOBODY** | — | **REAL GAP** |
| Options economics | options_research **(silent)** | — | **BROKEN** |
| Cost / fill modeling | Claude (implemented) | 19 passing tests | OK |
| Adversarial evidence audit | bear_audit **(silent)** | — | **BROKEN** |
| Risk gating | deterministic code | tests | OK — and correctly outside all models |
| Reproducibility / manifests | test_repro | Claude | OK |
| Results skepticism | **NOBODY** | — | **GAP** |

**Five gaps, two of them from agents that exist but aren't responding.** That's the honest answer to "do we have enough" — you have roughly the right roster on paper, with a hole where ingestion should be, and two chefs who've walked out of the kitchen.

---

## Revised roster — coverage-driven, not count-driven

**Keep (4):** data_lineage, quant_research, options_research, bear_audit
**Fix first:** options_research and bear_audit are silent across three rounds. Diagnose before replacing.
**Park (2):** sector_intelligence (no sector in a three-instrument slice), coordinator (orchestration moved to the API relay)
**Create (3):** Ingestion (Codex), Calibration, Results Devil's Advocate

That's 7 active roles across 3 base models — versus 6 personas on 1 model today. Fewer redundant chefs, more genuine independence, and every gap above closed.

**The structural rule to hold onto:** any stage that produces a number someone might act on gets checked by a *different model*, not a different persona of the same one.

---

## On leveraging ChatGPT properly

You're right that I should be using Codex rather than working around it. Concretely, the division that plays to each:

**Codex should own** anything requiring the local machine: ingestion jobs, long-running downloads, filesystem-heavy normalization, and running the pipeline against real data. It has Full access and persistent local execution. I have neither — my shell is an isolated Linux VM with no path to your machine.

**I should own** architecture, specification, adversarial review of Codex's output, and orchestrating the Slack specialists — because I hold the API relay and because the reviewer must not be the builder.

**The ChatGPT specialists should own** domain judgment within their narrow schemas, which is what they're good at and where the structured-abstention behavior pays off.

This isn't me deferring work I'd rather keep. Ingestion genuinely cannot be done from where I sit, and the review separation genuinely matters more than either of us doing more.
