"""
Sanity check on the evaluation harness itself.

A harness that reports edge on random data is worse than no harness, because it
will confidently endorse noise. So: feed it a pure random walk, where no edge
can exist by construction, and confirm it says NO_EDGE.

Only after passing this is the harness trustworthy enough to evaluate anything real.
"""
from __future__ import annotations
import sys, os, random, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from backtest.evaluate import evaluate_walk_forward

random.seed(11)


def random_walk_folds(n_folds=8, per_fold=120, drift=0.0003, vol=0.011):
    """Geometric random walk. Forward 5-day excess sign is unpredictable by construction."""
    folds = []
    price = 100.0
    for _ in range(n_folds):
        rets = [random.gauss(drift, vol) for _ in range(per_fold + 5)]
        feats, labels = [], []
        for i in range(per_fold):
            window = rets[max(0, i - 10):i + 1]
            mom = sum(window)                          # trailing momentum feature
            fwd = sum(rets[i + 1:i + 6])               # forward 5-day return
            feats.append({"momentum": mom})
            labels.append(1 if fwd > 0 else 0)
        folds.append((feats, labels))
    return folds


def momentum_strategy(feats):
    return [1 if f["momentum"] > 0 else 0 for f in feats]


def always_long(feats):
    return [1] * len(feats)


def main():
    print("=" * 74)
    print("NOISE FLOOR CHECK - harness validation on PURE RANDOM DATA")
    print("=" * 74)
    print("\nData is a geometric random walk. No edge exists by construction.")
    print("A trustworthy harness MUST report NO_EDGE here.\n")

    folds = random_walk_folds()

    for name, fn in (("trailing momentum", momentum_strategy),
                     ("always long", always_long)):
        rep = evaluate_walk_forward(folds, fn, strategy_name=name, n_permutations=200)
        print("-" * 74)
        print(rep.render())
        print()

    print("=" * 74)
    print("Read the VERDICT lines. Both should say NO_EDGE or INCONCLUSIVE.")
    print("If either says SIGNAL_CANDIDATE, the harness is broken and every")
    print("result it ever produces is untrustworthy. That is the whole point")
    print("of this check: prove the measuring instrument reads zero on nothing")
    print("BEFORE pointing it at real data.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
