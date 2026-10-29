"""Key profiles and the correlation used to compare them.

Split out so the detector and the benchmark tool share exactly the same
definitions (a benchmark that reimplements the thing it measures proves
nothing).

Profiles
--------
`T_MAJ`/`T_MIN` are Temperley's revised profiles (2001). We use these rather
than the original Krumhansl-Kessler (KK) values because:

  * KK's minor profile sums to ~6.5% more than its major profile, which biases
    every comparison toward minor keys. Temperley's sum identically for both
    modes, removing the bias by construction.
  * In published evaluations (e.g. the Stanford WTC/Chopin study) the original
    KK weights were the weakest of the five candidate weight-sets tested,
    misidentifying 12/120 works versus 4-9 for the alternatives.

`KK_*` are kept only so the benchmark can demonstrate the difference.
"""
from .theory import NAMES  # noqa: F401  (re-exported for convenience)

# Temperley (2001) revised profiles. Equal sums by construction.
T_MAJ = [5.0, 2.0, 3.5, 2.0, 4.5, 4.0, 2.0, 4.5, 2.0, 3.5, 1.5, 4.0]
T_MIN = [5.0, 2.0, 3.5, 4.5, 2.0, 4.0, 2.0, 4.5, 3.5, 2.0, 1.5, 4.0]

# Krumhansl-Kessler (original). Retained for benchmarking only.
KK_MAJ = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KK_MIN = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def profile(weights, root):
    """Rotate a profile so index 0 is the tonic, then index it by pitch class."""
    out = [0.0] * 12
    for i, w in enumerate(weights):
        out[(root + i) % 12] = w
    return out


def corr(xs, ys):
    """Pearson correlation of two equal-length sequences."""
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** .5
    dy = sum((y - my) ** 2 for y in ys) ** .5
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)
