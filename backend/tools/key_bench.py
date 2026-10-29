"""Benchmark harness for key detection (dev tool; not collected by pytest).

Builds excerpts whose key is known by construction and reports accuracy, so
changes are measured instead of guessed at. It calls the shipped `detect_key`
directly -- a benchmark that reimplements what it measures proves nothing.

Run:  .venv/bin/python tools/key_bench.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.music_analysis.chords import detect_chords  # noqa: E402
from app.music_analysis.key import detect_key  # noqa: E402

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def chords_in_key(root, minor, degrees):
    """Chord specs for a progression expressed in scale degrees of the key."""
    steps = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    if minor:
        quals = {0: "min", 1: "dim", 2: "maj", 3: "min", 4: "min", 5: "maj", 6: "maj"}
    else:
        quals = {0: "maj", 1: "min", 2: "min", 3: "maj", 4: "maj", 5: "min", 6: "dim"}
    out = []
    for d in degrees:
        base = steps[d % 7]
        q = quals[d % 7]
        third = 4 if q == "maj" else 3
        ivs = [0, third, 6 if q == "dim" else 7]
        out.append((root + base, ivs, q))
    return out


def make_excerpt(root, minor, seed=0, texture="full", degrees=None):
    """A short excerpt: chord progression with a texture on top.

    texture='full'  bass + triad + melody (like a dense piano transcription)
    texture='bass'  bass + triad (clean harmony)
    texture='arpeg' broken chords with deliberately uneven note lengths
    texture='melody' mostly single line (chord detector has little to work with)
    """
    rnd = random.Random(seed)
    degrees = degrees or [0, 3, 4, 5, 2, 1, 0, 4]
    notes = []
    i = 0
    t = 0.0
    pool = [root + s for s in ([0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11])]
    for chord_root, ivs, qual in chords_in_key(root, minor, degrees):
        dur = rnd.choice([0.8, 1.0, 1.2])
        if texture == "bass":
            for iv in ivs:
                notes.append({"id": i, "pitch": 48 + chord_root + iv, "start": t, "end": t + dur})
                i += 1
        elif texture == "arpeg":
            seq = ivs + ivs[:1] + ivs
            for k, iv in enumerate(seq):
                notes.append({"id": i, "pitch": 60 + chord_root + iv,
                              "start": t + k * dur / 6,
                              "end": t + k * dur / 6 + rnd.choice([0.12, 0.45])})
                i += 1
        elif texture == "melody":
            for k in range(3):
                notes.append({"id": i, "pitch": 72 + rnd.choice(pool),
                              "start": t + k * dur / 3, "end": t + k * dur / 3 + dur / 4})
                i += 1
        else:
            for iv in ivs:
                notes.append({"id": i, "pitch": 60 + chord_root + iv, "start": t, "end": t + dur})
                i += 1
            notes.append({"id": i, "pitch": 36 + chord_root, "start": t, "end": t + dur})
            i += 1
            for _ in range(2):
                notes.append({"id": i, "pitch": 72 + rnd.choice(pool),
                              "start": t + rnd.uniform(0, .5),
                              "end": t + rnd.uniform(.6, 1.0)})
                i += 1
        t += dur
    return notes


TEXTURES = ("full", "bass", "arpeg", "melody")


def corpus(seeds=5):
    out = []
    for root in range(12):
        for minor in (False, True):
            for seed in range(seeds):
                for tex in TEXTURES:
                    out.append((root, minor, tex, make_excerpt(root, minor, seed, tex)))
    return out


def report(label, predictor, cases):
    n = len(cases)
    exact = root_only = mode_only = 0
    by_tex = {}
    for root, minor, tex, notes in cases:
        r = predictor(notes)
        ok = bool(r) and r["tonic"] == root and r["minor"] == minor
        exact += ok
        root_only += bool(r) and r["tonic"] == root
        mode_only += bool(r) and r["minor"] == minor
        by_tex.setdefault(tex, [0, 0])
        by_tex[tex][0] += ok
        by_tex[tex][1] += 1
    print(f"  {label:26s} exact {exact/n*100:5.1f}%  root {root_only/n*100:5.1f}%  mode {mode_only/n*100:5.1f}%   "
          + " ".join(f"{t[:5]}:{v[0]/v[1]*100:3.0f}%" for t, v in sorted(by_tex.items())))
    return exact / n


if __name__ == "__main__":
    cases = corpus()
    print(f"corpus: {len(cases)} excerpts (12 roots x 2 modes x 5 seeds x {len(TEXTURES)} textures)\n")
    report("shipped detect_key", detect_key, cases)
    print()
    print("  per-mode breakdown:")
    for minor in (False, True):
        sub = [c for c in cases if c[1] == minor]
        report("  minor" if minor else "  major", detect_key, sub)
