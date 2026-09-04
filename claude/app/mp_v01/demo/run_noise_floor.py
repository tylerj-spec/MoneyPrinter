"""
Sanity check on the evaluation harness itself.

A harness that reports edge on random data is worse than no harness, because it
will confidently endorse noise. So: feed it a pure random walk, where no edge
can exist by construction, and confirm it says NO_EDGE.

Only after passing this is the harness trustworthy enough to evaluate anything
real.

This also demonstrates, with numbers, why the null is built the way it is. The
labels below are OVERLAPPING 5-day forward returns computed daily - consecutive
labels share four of their five days, exactly as in the real label contract. An
IID shuffle destroys that dependence and produces a null that is too tight. The
final section runs the identical strategy under both nulls so the size of the
distortion is visible rather than asserted.
"""
from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from backtest.evaluate import Fold, evaluate_walk_forward

random.seed(11)

HORIZON = 5


def _segment(rng, n, drift=0.0003, vol=0.011):
    """Features and OVERLAPPING forward labels from a geometric random walk."""
    rets = [rng.gauss(drift, vol) for _ in range(n + HORIZON)]
    feats, labels = [], []
    for i in range(n):
        window = rets[max(0, i - 10):i + 1]
        feats.append({"momentum": sum(window)})
        labels.append(1 if sum(rets[i + 1:i + 1 + HORIZON]) > 0 else 0)
    return feats, labels


def random_walk_folds(n_folds=8, train=240, test=120):
    rng = random.Random(11)
    folds = []
    for i in range(n_folds):
        tr_X, tr_y = _segment(rng, train)
        te_X, te_y = _segment(rng, test)
        folds.append(Fold(i, tr_X, tr_y, te_X, te_y))
    return folds


def momentum_strategy(train_X, train_y, test_X):
    """A fixed rule. Ignores the training labels entirely."""
    return [1 if f["momentum"] > 0 else 0 for f in test_X]


def always_long(train_X, train_y, test_X):
    return [1] * len(test_X)


def fitted_threshold(train_X, train_y, test_X):
    """A genuinely FITTED strategy: it searches the training data for the
    momentum cutoff that best separates the training labels, then applies it.

    On pure noise the best training cutoff is an artefact. The old harness could
    not see that, because it never refit under permutation - the model was fit
    once on the real labels and then merely rescored. Here the search runs again
    inside every permutation, so its capacity to fit noise is priced into the
    null where it belongs.
    """
    best_cut, best_hit = 0.0, -1
    for cand in (f["momentum"] for f in train_X):
        hits = sum(1 for f, y in zip(train_X, train_y)
                   if (1 if f["momentum"] > cand else 0) == y)
        if hits > best_hit:
            best_cut, best_hit = cand, hits
    return [1 if f["momentum"] > best_cut else 0 for f in test_X]


def main():
    print("=" * 74)
    print("NOISE FLOOR CHECK - harness validation on PURE RANDOM DATA")
    print("=" * 74)
    print("\nData is a geometric random walk. No edge exists by construction.")
    print("A trustworthy harness MUST report NO_EDGE here.\n")

    folds = random_walk_folds()

    for name, fn in (("trailing momentum (fixed rule)", momentum_strategy),
                     ("always long", always_long),
                     ("fitted momentum threshold", fitted_threshold)):
        rep = evaluate_walk_forward(folds, fn, strategy_name=name,
                                    n_permutations=200, label_horizon=HORIZON)
        print("-" * 74)
        print(rep.render())
        print()

    print("=" * 74)
    print("WHY THE PERMUTATION USES BLOCKS")
    print("=" * 74)
    print("\nSame strategy, same data, same number of permutations. The only")
    print("difference is whether the shuffle respects the fact that consecutive")
    print("labels overlap by four of five days.\n")

    iid = evaluate_walk_forward(folds, fitted_threshold, strategy_name="IID shuffle (WRONG)",
                                n_permutations=200, block_size=1)
    blk = evaluate_walk_forward(folds, fitted_threshold, strategy_name="block permutation",
                                n_permutations=200, label_horizon=HORIZON)

    print(f"  {'':<26}{'null std':>10}{'z':>9}{'p':>9}")
    for tag, r in (("IID shuffle (the old null)", iid), ("block permutation", blk)):
        print(f"  {tag:<26}{r.permutation_std:>10.4f}{r.z_vs_noise:>+9.2f}{r.permutation_p_value:>9.4f}")

    tighter = (blk.permutation_std - iid.permutation_std) / blk.permutation_std * 100
    print(f"\n  The IID null is {tighter:.0f}% tighter than the honest one.")
    print("  A tighter null means a larger z and a smaller p for the SAME result,")
    print("  which is the harness talking itself into significance. That bias runs")
    print("  in the one direction you cannot afford it to.\n")

    print("=" * 74)
    print("Read the VERDICT lines. All three should say NO_EDGE or INCONCLUSIVE.")
    print("If any says SIGNAL_CANDIDATE, the harness is broken and every result")
    print("it ever produces is untrustworthy. That is the whole point of this")
    print("check: prove the measuring instrument reads zero on nothing BEFORE")
    print("pointing it at real data.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
