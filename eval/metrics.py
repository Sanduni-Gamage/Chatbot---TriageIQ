"""Accuracy, macro-F1 and a text confusion matrix. No dependencies."""

from __future__ import annotations

from collections import defaultdict


def accuracy(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return 0.0
    return sum(1 for g, p in pairs if g == p) / len(pairs)


def macro_f1(pairs: list[tuple[str, str]], labels: list[str]) -> float:
    f1s = []
    for label in labels:
        tp = sum(1 for g, p in pairs if g == label and p == label)
        fp = sum(1 for g, p in pairs if g != label and p == label)
        fn = sum(1 for g, p in pairs if g == label and p != label)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        f1s.append(f1)
    return sum(f1s) / len(f1s) if f1s else 0.0


def confusion(pairs: list[tuple[str, str]], labels: list[str]) -> str:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for g, p in pairs:
        counts[(g, p)] += 1
    width = max((len(l) for l in labels), default=4) + 2
    header = "gold\\pred".ljust(width) + "".join(l.ljust(width) for l in labels)
    lines = [header]
    for g in labels:
        row = g.ljust(width) + "".join(str(counts[(g, p)]).ljust(width) for p in labels)
        lines.append(row)
    return "\n".join(lines)
