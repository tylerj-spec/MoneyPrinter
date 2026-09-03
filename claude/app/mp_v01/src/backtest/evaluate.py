"""
Walk-forward evaluation with a noise floor.

The most important number this produces is not the strategy's accuracy. It is
the NOISE FLOOR: what accuracy a strategy with no predictive power achieves on
this exact data, by chance, given this many folds and this sample size.

Without that number, 54% accuracy is unreadable. It might be a real edge or it
might be within one standard deviation of a coin flip. Most retail backtests
never compute it, which is why most retail backtests look promising.

Method: permutation test. Permute the labels, keep everything else identical,
RE-RUN THE WHOLE PROCEDURE INCLUDING THE FIT, repeat N times. The distribution
of permuted results IS the noise floor.

------------------------------------------------------------------------------
TWO THINGS THIS MODULE GETS RIGHT THAT THE OBVIOUS IMPLEMENTATION GETS WRONG
------------------------------------------------------------------------------

1. THE NULL INCLUDES THE FIT.

   The earlier version took `predict_fn(features)` - a function of features
   alone. Predictions therefore did not depend on labels, so permuting the
   labels changed nothing about the predictions and the loop merely rescored a
   fixed vector. That is a null for "does this FIXED prediction vector beat
   chance", not for "does this PROCEDURE beat chance", and the difference is
   the procedure's capacity to overfit - which is exactly the thing a noise
   floor exists to price.

   The interface is therefore `fit_predict_fn(train_X, train_y, test_X)`. Under
   permutation the model is refit on permuted TRAINING labels, so whatever it
   can wring out of noise is in the null where it belongs. This is ~N times
   slower. That cost is the price of the number meaning what you think it means.

2. THE PERMUTATION PRESERVES AUTOCORRELATION.

   Labels here are 5-trading-day forward returns computed daily, so consecutive
   labels share four of their five days and are heavily autocorrelated. An IID
   shuffle destroys that structure, which makes the permuted distribution TOO
   TIGHT: permutation_std too small, z_vs_noise too large, p-value too small.
   The harness would then be biased toward reporting edge - in the one place
   you least want optimism.

   So permutation is done in contiguous BLOCKS of `block_size` labels, default
   twice the label horizon. Block permutation is still a permutation (the
   marginal class balance is untouched) but it keeps local dependence intact.
   Passing block_size=1 reproduces the old IID behaviour and is retained only
   so the bias can be demonstrated - see demo/run_noise_floor.py.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Sequence

from .walkforward import LeakageError

# Default label horizon, in observations. Blocks are twice this so a block
# spans more than one label's worth of overlap.
DEFAULT_LABEL_HORIZON = 5


@dataclass
class Fold:
    """One chronological train/test split, with the labels for both.

    Both halves are required: the null refits on the training labels, so a fold
    that carries only test data cannot express the procedure being tested.

    train_times / test_times are optional per-observation decision times. When
    supplied they are CHECKED - see _assert_fold_is_chronological. A guard you
    have to remember to call is a guard that eventually doesn't get called, so
    this one lives inside the evaluation path rather than beside it.
    """
    index: int
    train_X: Sequence[Any]
    train_y: Sequence[int]
    test_X: Sequence[Any]
    test_y: Sequence[int]
    train_times: Sequence[datetime] | None = None
    test_times: Sequence[datetime] | None = None

    def __post_init__(self) -> None:
        if len(self.train_X) != len(self.train_y):
            raise ValueError(
                f"fold {self.index}: {len(self.train_X)} train rows vs "
                f"{len(self.train_y)} train labels")
        if len(self.test_X) != len(self.test_y):
            raise ValueError(
                f"fold {self.index}: {len(self.test_X)} test rows vs "
                f"{len(self.test_y)} test labels")


def _assert_fold_is_chronological(fold: Fold, label_horizon: int) -> None:
    """Test data must come strictly after training data, with a purge gap.

    Only runs when decision times were supplied. It cannot invent them, but
    when they exist it will not let a fold through that trains on the future.
    """
    if not fold.train_times or not fold.test_times:
        return
    last_train, first_test = max(fold.train_times), min(fold.test_times)
    if last_train >= first_test:
        raise LeakageError(
            f"fold {fold.index}: last training decision {last_train} is not "
            f"before the first test decision {first_test}")
    gap_days = (first_test - last_train).days
    if gap_days < label_horizon:
        raise LeakageError(
            f"fold {fold.index}: purge gap {gap_days}d < label horizon "
            f"{label_horizon}. The last training labels resolve after the test "
            f"window opens, leaking the future into training.")


def block_permute(labels: Sequence[int], block_size: int, rng: random.Random) -> list[int]:
    """Permute contiguous blocks, preserving local autocorrelation.

    block_size=1 degenerates to an IID shuffle, which is the wrong null for
    overlapping labels. It stays reachable only to demonstrate that.
    """
    if block_size < 1:
        raise ValueError(f"block_size must be >= 1, got {block_size}")
    if block_size == 1:
        out = list(labels)
        rng.shuffle(out)
        return out
    blocks = [list(labels[i:i + block_size]) for i in range(0, len(labels), block_size)]
    rng.shuffle(blocks)
    return [y for b in blocks for y in b][:len(labels)]


@dataclass
class FoldResult:
    index: int
    n: int
    correct: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else float("nan")


@dataclass
class EvalReport:
    strategy_name: str
    folds: list[FoldResult] = field(default_factory=list)
    majority_class_rate: float = 0.0
    permutation_mean: float = 0.0
    permutation_std: float = 0.0
    permutation_p_value: float = 1.0
    n_permutations: int = 0
    block_size: int = 0
    refit_under_permutation: bool = True

    @property
    def n_total(self) -> int:
        return sum(f.n for f in self.folds)

    @property
    def accuracy(self) -> float:
        n = self.n_total
        return sum(f.correct for f in self.folds) / n if n else float("nan")

    @property
    def z_vs_noise(self) -> float:
        if self.permutation_std == 0:
            return 0.0
        return (self.accuracy - self.permutation_mean) / self.permutation_std

    @property
    def fold_accuracy_spread(self) -> float:
        """Worst-to-best fold gap. A strategy that is only profitable in one
        fold out of eight has not shown an edge, it has shown a regime."""
        accs = [f.accuracy for f in self.folds if f.n]
        return (max(accs) - min(accs)) if accs else float("nan")

    def verdict(self) -> str:
        """Deliberately harsh. The default answer is 'no edge'."""
        if self.accuracy <= self.majority_class_rate:
            return "NO_EDGE (does not beat always predicting the majority class)"
        if self.permutation_p_value > 0.05:
            return f"NO_EDGE (p={self.permutation_p_value:.3f}; indistinguishable from chance)"
        if self.z_vs_noise < 2.0:
            return f"INCONCLUSIVE (z={self.z_vs_noise:.2f}; within noise)"
        return (f"SIGNAL_CANDIDATE (z={self.z_vs_noise:.2f}, p={self.permutation_p_value:.3f}) "
                f"- NOT validated. Requires out-of-sample, cost, and regime testing.")

    def render(self) -> str:
        L = []
        L.append(f"Strategy            : {self.strategy_name}")
        L.append(f"Observations        : {self.n_total} across {len(self.folds)} folds")
        L.append(f"Accuracy            : {self.accuracy:.4f}")
        L.append(f"Majority-class rate : {self.majority_class_rate:.4f}  <- must beat this")
        L.append(f"Per-fold accuracy   : "
                 + ", ".join(f"{f.accuracy:.3f}" for f in self.folds)
                 + f"   (spread {self.fold_accuracy_spread:.3f})")
        L.append(f"Noise floor (permute): {self.permutation_mean:.4f} "
                 f"+/- {self.permutation_std:.4f}  ({self.n_permutations} permutations, "
                 f"block={self.block_size}, refit={'yes' if self.refit_under_permutation else 'NO'})")
        L.append(f"Z vs noise          : {self.z_vs_noise:+.2f}")
        L.append(f"Permutation p-value : {self.permutation_p_value:.4f}")
        L.append(f"VERDICT             : {self.verdict()}")
        return "\n".join(L)


def evaluate_walk_forward(
    folds: Sequence[Fold],
    fit_predict_fn: Callable[[Sequence[Any], Sequence[int], Sequence[Any]], Sequence[int]],
    *,
    strategy_name: str = "unnamed",
    n_permutations: int = 200,
    seed: int = 7,
    label_horizon: int = DEFAULT_LABEL_HORIZON,
    block_size: int | None = None,
) -> EvalReport:
    """
    folds          : chronological Fold objects carrying train AND test data
    fit_predict_fn : (train_X, train_y, test_X) -> predicted 0/1 for test_X

    The function is called once per fold to score the strategy, then
    n_permutations more times per fold with permuted training labels to build
    the noise floor. It must therefore be deterministic given its inputs, or
    the null measures the strategy's own randomness as well.
    """
    if block_size is None:
        block_size = max(1, 2 * label_horizon)

    rep = EvalReport(strategy_name=strategy_name, n_permutations=n_permutations,
                     block_size=block_size)

    all_labels: list[int] = []
    for fold in folds:
        _assert_fold_is_chronological(fold, label_horizon)
        preds = fit_predict_fn(fold.train_X, fold.train_y, fold.test_X)
        if len(preds) != len(fold.test_y):
            raise ValueError(
                f"fold {fold.index}: {len(preds)} predictions vs {len(fold.test_y)} labels")
        rep.folds.append(FoldResult(
            fold.index, len(fold.test_y),
            sum(int(p == y) for p, y in zip(preds, fold.test_y))))
        all_labels.extend(fold.test_y)

    if not all_labels:
        return rep

    ones = sum(all_labels)
    rep.majority_class_rate = max(ones, len(all_labels) - ones) / len(all_labels)

    # Noise floor: identical pipeline, labels block-permuted, MODEL REFIT.
    rng = random.Random(seed)
    observed = rep.accuracy
    scores: list[float] = []
    for _ in range(n_permutations):
        correct = total = 0
        for fold in folds:
            train_perm = block_permute(fold.train_y, block_size, rng)
            test_perm = block_permute(fold.test_y, block_size, rng)
            preds = fit_predict_fn(fold.train_X, train_perm, fold.test_X)
            correct += sum(int(p == y) for p, y in zip(preds, test_perm))
            total += len(test_perm)
        scores.append(correct / total if total else 0.0)

    m = sum(scores) / len(scores)
    var = sum((s - m) ** 2 for s in scores) / len(scores)
    rep.permutation_mean = m
    rep.permutation_std = math.sqrt(var)
    # One-sided: how often does pure chance match or beat what we observed?
    rep.permutation_p_value = (sum(1 for s in scores if s >= observed) + 1) / (len(scores) + 1)
    return rep
