"""
Walk-forward evaluation with a noise floor.

The most important number this produces is not the strategy's accuracy. It is
the NOISE FLOOR: what accuracy a strategy with no predictive power achieves on
this exact data, by chance, given this many folds and this sample size.

Without that number, 54% accuracy is unreadable. It might be a real edge or it
might be within one standard deviation of a coin flip. Most retail backtests
never compute it, which is why most retail backtests look promising.

Method: permutation test. Shuffle the labels, keep everything else identical,
re-run, repeat N times. The distribution of shuffled results IS the noise floor.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


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
        L.append(f"Noise floor (shuffle): {self.permutation_mean:.4f} "
                 f"+/- {self.permutation_std:.4f}  ({self.n_permutations} permutations)")
        L.append(f"Z vs noise          : {self.z_vs_noise:+.2f}")
        L.append(f"Permutation p-value : {self.permutation_p_value:.4f}")
        L.append(f"VERDICT             : {self.verdict()}")
        return "\n".join(L)


def evaluate_walk_forward(
    fold_data: list[tuple[list, list[int]]],
    predict_fn,
    *,
    strategy_name: str = "unnamed",
    n_permutations: int = 200,
    seed: int = 7,
) -> EvalReport:
    """
    fold_data : list of (features, labels) per chronological fold
    predict_fn: features -> list of predicted 0/1
    """
    rep = EvalReport(strategy_name=strategy_name, n_permutations=n_permutations)

    all_labels: list[int] = []
    for i, (feats, labels) in enumerate(fold_data):
        preds = predict_fn(feats)
        if len(preds) != len(labels):
            raise ValueError(f"fold {i}: {len(preds)} predictions vs {len(labels)} labels")
        rep.folds.append(FoldResult(i, len(labels), sum(int(p == y) for p, y in zip(preds, labels))))
        all_labels.extend(labels)

    if not all_labels:
        return rep

    ones = sum(all_labels)
    rep.majority_class_rate = max(ones, len(all_labels) - ones) / len(all_labels)

    # Noise floor: identical pipeline, labels shuffled.
    rng = random.Random(seed)
    observed = rep.accuracy
    scores: list[float] = []
    for _ in range(n_permutations):
        correct = total = 0
        for feats, labels in fold_data:
            shuffled = labels[:]
            rng.shuffle(shuffled)
            preds = predict_fn(feats)
            correct += sum(int(p == y) for p, y in zip(preds, shuffled))
            total += len(shuffled)
        scores.append(correct / total if total else 0.0)

    m = sum(scores) / len(scores)
    var = sum((s - m) ** 2 for s in scores) / len(scores)
    rep.permutation_mean = m
    rep.permutation_std = math.sqrt(var)
    # One-sided: how often does pure chance match or beat what we observed?
    rep.permutation_p_value = (sum(1 for s in scores if s >= observed) + 1) / (len(scores) + 1)
    return rep
