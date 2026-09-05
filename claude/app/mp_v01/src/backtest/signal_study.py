"""
Walk-forward study of the score components against the label contract.

WHAT THIS BACKTESTS, AND WHAT IT CANNOT

It backtests the SIGNAL LAYER on the underlying: does a weighted combination of
the components in strategy/components.py predict the sign of 5-trading-day
forward excess return versus SPY, out of sample, better than chance?

It is NOT an options backtest and cannot become one from this data. Yahoo serves
only CURRENT option chains - see adapters/yahoo_daily - so there is no way to
ask what the SPY chain looked like on 2024-03-05. Any historical options P&L
curve built from this repository's data would be fabricated. The forward paper
record from generate_picks.py is the only honest options evidence available, and
it accumulates one day at a time.

That distinction matters more than it might look. The signal layer is where an
edge would have to come from: if the underlying forecast has no edge, no options
overlay rescues it - you would be selecting contracts on a coin flip.

TWO NUMBERS, NOT ONE

Accuracy alone is unreadable. 54% might be an edge or might be a coin flip with
this sample size, and it is definitely not an edge if 54% of the labels are 1s.
So every result carries:

  - the MAJORITY-CLASS RATE: what you get by always guessing the common answer
  - the NOISE FLOOR: what this exact procedure scores when the labels are
    block-permuted and the model refit, which prices in its capacity to
    overfit noise

The verdict comes from those, never from accuracy on its own.

RANK IC

Accuracy asks a yes/no question of a combination. Rank IC asks the sharper one,
of each component separately: does its RANKING of instruments line up with the
RANKING of their forward excess returns? That is the measurement the roadmap
calls Phase 4 and the one that would justify - or retire - each component on its
own merits rather than as part of a blend. It is computed out of sample, per
fold, and reported per component with the spread across folds, because a mean IC
whose fold-to-fold sign flips is not a finding.

Spearman rank correlation is used rather than Pearson: the components are
scaled by arbitrary constants and a monotone transform of one should not change
the answer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .evaluate import Fold, evaluate_walk_forward, EvalReport
from .walkforward import LeakageError, Split, TradingCalendar, make_splits


@dataclass(frozen=True)
class Observation:
    """One decision, its features, and how it turned out."""
    ticker: str
    decision_date: str
    features: dict[str, float]
    y: int
    excess_log_return: float


def build_observations(
    rows_by_ticker: dict[str, list[dict[str, Any]]],
    labels_by_ticker: dict[str, list[dict[str, Any]]],
    compute_fn: Callable[[Sequence[dict[str, Any]], str], dict[str, Any]],
    *,
    required: Sequence[str],
    exclude: Sequence[str] = (),
) -> list[Observation]:
    """Join point-in-time features to usable labels, dropping anything partial.

    `required` names the scaled components that must ALL be present. A component
    that is None means insufficient history, and filling it with a zero would
    invent a neutral reading the data never produced - the observation is
    dropped instead. Early bars therefore contribute nothing, which is correct:
    a 60-day momentum has no value on day 30.

    `exclude` drops instruments from the study. The benchmark belongs there: its
    own excess return against itself is identically zero, so including SPY would
    feed the model a column of labels that mean nothing.
    """
    skip = {t.upper() for t in exclude}
    out: list[Observation] = []
    for ticker, labels in sorted(labels_by_ticker.items()):
        if ticker.upper() in skip:
            continue
        bars = rows_by_ticker.get(ticker, [])
        for lab in labels:
            if not lab.get("usable") or lab.get("y") is None:
                continue
            excess = lab.get("excess_log_return")
            if not isinstance(excess, (int, float)) or excess != excess:
                continue
            scaled = compute_fn(bars, lab["decision_date"]).get("scaled", {})
            feats = {k: scaled.get(k) for k in required}
            if any(v is None or not isinstance(v, (int, float)) for v in feats.values()):
                continue
            out.append(Observation(ticker, lab["decision_date"],
                                   {k: float(v) for k, v in feats.items()},
                                   int(lab["y"]), float(excess)))
    out.sort(key=lambda o: (o.decision_date, o.ticker))
    return out


def folds_from_splits(observations: Sequence[Observation],
                      splits: Sequence[Split]) -> list[Fold]:
    """Cut observations into folds by decision date.

    Observations landing in the purge gap belong to neither half and are simply
    absent, which is what a purge IS - the walk-forward layout already placed
    the gap, this only honours it.
    """
    folds: list[Fold] = []
    for sp in splits:
        tr = [o for o in observations
              if sp.train_start.isoformat() <= o.decision_date <= sp.train_end.isoformat()]
        te = [o for o in observations
              if sp.test_start.isoformat() <= o.decision_date <= sp.test_end.isoformat()]
        if not tr or not te:
            continue
        folds.append(Fold(
            sp.index,
            [o.features for o in tr], [o.y for o in tr],
            [o.features for o in te], [o.y for o in te],
        ))
    return folds


def weighted_score(features: dict[str, float], weights: dict[str, float]) -> float:
    return sum(features.get(k, 0.0) * w for k, w in weights.items())


def make_threshold_learner(weights: dict[str, float]) -> Callable:
    """Fit the decision threshold on the TRAINING labels, predict on test.

    The weights are the variant's and are fixed - they are a hypothesis, not
    something to be fitted. What is fitted is where the score has to sit before
    the answer flips, chosen to maximise training accuracy.

    Something has to be fitted or the permutation null is decorative: a rule
    that ignores labels entirely returns the same predictions no matter how the
    labels are shuffled, so the noise floor would measure nothing about the
    procedure's capacity to overfit. This is the smallest honest fit available.
    """
    def fit_predict(train_X: Sequence[dict], train_y: Sequence[int],
                    test_X: Sequence[dict]) -> list[int]:
        best_t = best_threshold([weighted_score(x, weights) for x in train_X], train_y)
        return [1 if weighted_score(x, weights) > best_t else 0 for x in test_X]
    return fit_predict


def best_threshold(scores: Sequence[float], labels: Sequence[int]) -> float:
    """The threshold maximising training accuracy, by one ascending sweep.

    Predicting `score > t` gets an observation right when it is a 1 above the
    threshold or a 0 at or below it, so for a given t:

        correct(t) = #{y == 0, s <= t} + #{y == 1, s > t}

    Both counts move monotonically as t rises through the sorted scores, so the
    whole search is one pass instead of re-scoring every row at every candidate.
    That matters because the noise floor refits this hundreds of times per fold:
    the quadratic version made a 200-permutation study on four years of daily
    bars take minutes, which is long enough that nobody presses the button.

    Ties resolve to the LOWEST threshold, matching a naive ascending scan.
    """
    if not scores:
        return 0.0
    pairs = sorted(zip(scores, labels), key=lambda p: p[0])
    total_ones = sum(1 for _, y in pairs if y)
    best_t, best_correct = pairs[0][0], -1
    zeros_le = ones_le = 0
    i, n = 0, len(pairs)
    while i < n:
        t = pairs[i][0]
        while i < n and pairs[i][0] == t:      # consume the whole tie group
            if pairs[i][1]:
                ones_le += 1
            else:
                zeros_le += 1
            i += 1
        correct = zeros_le + (total_ones - ones_le)
        if correct > best_correct:
            best_correct, best_t = correct, t
    return best_t


# ---------------------------------------------------------------------------
# Rank IC
# ---------------------------------------------------------------------------

def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks, so ties do not manufacture an ordering."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation. None when it is undefined rather than zero."""
    if len(xs) != len(ys):
        raise ValueError(f"length mismatch: {len(xs)} vs {len(ys)}")
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:            # a constant column has no ranking
        return None
    return num / (dx * dy)


@dataclass
class ICResult:
    component: str
    per_fold: list[float] = field(default_factory=list)
    # How the number was actually built, carried alongside it so a reader can
    # tell whether it means anything. A cross-sectional IC over three names is
    # arithmetic, not evidence, and only these fields reveal that.
    daily_readings: int = 0
    instruments_per_date: list[int] = field(default_factory=list)

    @property
    def median_universe(self) -> int | None:
        if not self.instruments_per_date:
            return None
        s = sorted(self.instruments_per_date)
        return s[len(s) // 2]

    @property
    def universe_is_too_small(self) -> bool:
        """Below five names a daily rank correlation has too few distinct
        values to carry information, however stable its average looks."""
        m = self.median_universe
        return m is not None and m < 5

    @property
    def mean(self) -> float | None:
        return sum(self.per_fold) / len(self.per_fold) if self.per_fold else None

    @property
    def stdev(self) -> float | None:
        if len(self.per_fold) < 2:
            return None
        m = self.mean
        return math.sqrt(sum((v - m) ** 2 for v in self.per_fold) / (len(self.per_fold) - 1))

    @property
    def hit_rate(self) -> float | None:
        """Share of folds where the IC kept the sign of the mean.

        A mean IC of +0.03 built from folds of +0.30 and -0.24 is not a weak
        edge, it is no edge measured twice. This is the cheapest way to see that.
        """
        if not self.per_fold or self.mean is None or self.mean == 0:
            return None
        want = 1 if self.mean > 0 else -1
        return sum(1 for v in self.per_fold
                   if (1 if v > 0 else -1) == want) / len(self.per_fold)

    @property
    def t_stat(self) -> float | None:
        """Mean over standard error across folds. Not a p-value.

        Folds overlap in the instruments they cover and the label horizon
        overlaps within a fold, so the independence this assumes does not hold.
        It is a magnitude cue, and small samples of folds make it a loose one.
        """
        s, m = self.stdev, self.mean
        if s is None or m is None or s == 0:
            return None
        return m / (s / math.sqrt(len(self.per_fold)))


def rank_ic_by_component(observations: Sequence[Observation],
                         splits: Sequence[Split],
                         components: Sequence[str],
                         *, cross_sectional: bool = True) -> list[ICResult]:
    """Out-of-sample rank IC per component, one reading per test window.

    TWO DIFFERENT STATISTICS WEAR THIS NAME, AND THEY ARE NOT INTERCHANGEABLE.

    CROSS-SECTIONAL (the default, and what "rank IC" means in the literature):
    on each decision date, rank the instruments by the component and by their
    forward excess return, correlate those two rankings, then average the daily
    figures over the test window. It answers "on any given day, does this
    component pick which name will do better?" - which is the question a
    portfolio built from it would actually be asking.

    POOLED: throw every (instrument, date) pair in the window into one
    correlation. This is what the first version of this function did, and it is
    a DIFFERENT question, badly posed: with a handful of instruments and thirty
    dates, the ranking is dominated by which DATES had large excess moves rather
    than which instruments led on a given date. A market-wide selloff shows up
    as signal. It is kept behind the flag only so the two can be compared.

    THE UNIVERSE SIZE IS THE BINDING CONSTRAINT, and the caller must look at it.
    A cross-sectional correlation over three names can only take a handful of
    values, so its per-date reading is almost pure noise even when the average
    over many dates is stable. `instruments_per_date` on the result exists so
    that fact cannot be read past.
    """
    results = {c: ICResult(c) for c in components}
    for sp in splits:
        test = [o for o in observations
                if sp.test_start.isoformat() <= o.decision_date <= sp.test_end.isoformat()]
        if len(test) < 3:
            continue

        if not cross_sectional:
            forward = [o.excess_log_return for o in test]
            for c in components:
                ic = spearman([o.features[c] for o in test], forward)
                if ic is not None:
                    results[c].per_fold.append(ic)
            continue

        by_date: dict[str, list[Observation]] = {}
        for o in test:
            by_date.setdefault(o.decision_date, []).append(o)
        widths = sorted(len(v) for v in by_date.values())
        for c in components:
            daily = []
            for day in sorted(by_date):
                rows = by_date[day]
                if len(rows) < 3:        # a correlation over two points is 1 or -1
                    continue
                ic = spearman([o.features[c] for o in rows],
                              [o.excess_log_return for o in rows])
                if ic is not None:
                    daily.append(ic)
            if daily:
                results[c].per_fold.append(sum(daily) / len(daily))
                results[c].daily_readings += len(daily)
                results[c].instruments_per_date.append(widths[len(widths) // 2])
    return [results[c] for c in components]


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

@dataclass
class VariantResult:
    variant: str
    description: str
    report: EvalReport
    n_train: int
    n_test: int


def run_study(
    observations: Sequence[Observation],
    calendar: TradingCalendar,
    variants: Sequence[Any],
    *,
    train_sessions: int = 180,
    test_sessions: int = 30,
    label_horizon: int = 5,
    embargo_sessions: int = 2,
    n_permutations: int = 200,
    seed: int = 7,
) -> dict[str, Any]:
    """Walk-forward every variant over one calendar, plus per-component rank IC.

    Raises rather than returning a degraded result when the data cannot support
    a study: a backtest on two folds is not a smaller backtest, it is a number
    with no meaning that will nonetheless be read as one.
    """
    if not observations:
        raise ValueError(
            "No usable observations. Every bar needs a complete set of "
            "components AND a resolved label, so a short history yields none.")

    splits = make_splits(calendar, train_sessions=train_sessions,
                         test_sessions=test_sessions,
                         label_horizon_sessions=label_horizon,
                         embargo_sessions=embargo_sessions)

    components = sorted(observations[0].features)
    ic = rank_ic_by_component(observations, splits, components)

    results: list[VariantResult] = []
    for v in variants:
        weights = v.normalised_weights() if hasattr(v, "normalised_weights") else v.weights
        usable = {k: w for k, w in weights.items() if k in components}
        if not usable:
            continue
        folds = folds_from_splits(observations, splits)
        if not folds:
            continue
        rep = evaluate_walk_forward(
            folds, make_threshold_learner(usable), strategy_name=v.name,
            n_permutations=n_permutations, seed=seed, label_horizon=label_horizon,
            sessions=calendar,
        )
        results.append(VariantResult(
            v.name, getattr(v, "description", ""), rep,
            n_train=sum(len(f.train_y) for f in folds),
            n_test=sum(len(f.test_y) for f in folds),
        ))

    return {
        "observations": len(observations),
        "instruments": sorted({o.ticker for o in observations}),
        "first_decision": observations[0].decision_date,
        "last_decision": observations[-1].decision_date,
        "sessions": len(calendar),
        "splits": splits,
        "components": components,
        "rank_ic": ic,
        "variants": results,
        "settings": {
            "train_sessions": train_sessions, "test_sessions": test_sessions,
            "label_horizon_sessions": label_horizon,
            "embargo_sessions": embargo_sessions,
            "n_permutations": n_permutations, "seed": seed,
        },
    }
