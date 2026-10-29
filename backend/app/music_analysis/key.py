"""Key (tonal centre) estimation from transcribed notes.

Purely symbolic: no model, no download, no audio. Like `chords.py` this costs
milliseconds per song, so it is recomputed alongside chords on every commit.

Why not just a pitch-class histogram
------------------------------------
A natural minor scale and its relative major contain the *same seven pitch
classes*: C minor (C D Eb F G Ab Bb) and Eb major are the identical set. A
pitch-class histogram therefore cannot separate them by construction, and any
profile-correlation method built on one will confuse relative keys. Measured on
constructed excerpts, a pure pitch-class approach got minor keys badly wrong
(0-20% on arpeggiated and dense textures) while chord-based material was fine.

The fix is to weight *harmony*. Chord roots and their major/minor quality carry
exactly the information the pitch-class histogram throws away: the chord built
on the tonic of C minor is C-Eb-G (minor), while the chord on the tonic of Eb
major is Eb-G-Bb (major). So the primary signal here is functional harmony --
which chord roots behave like a tonic, a dominant and a subdominant, and
whether the tonic *chord* is major or minor.

Harmony is only as good as the chords it is given
--------------------------------------------------
Feeding the scorer *perfect* chord symbols recovers the key 24/24, so the
scoring logic itself is sound. Where minor keys still failed, the fault was
upstream: on overlapping/arpeggiated material the chord detector reads the
right roots but reports them as power chords (`C5`), and a chord with no third
says nothing about major vs minor. Defaulting those to major made every such
minor key come back as its parallel major. `_mode_of` therefore reports such
chords as mode-neutral, and `chord_reliability` measures how much of the
progression is actually usable. Harmony is weighted by that measurement, so a
reading built on power chords does not get to outvote the pitch-class profile.

Structure
---------
  _mode_of          min / maj / None (chords with no third state no mode)
  chord_reliability how much the chord progression can be trusted (0..1)
  harmonic_scores   primary. Chord roots/qualities scored by scale-degree role
                    and weighted by how far along the progression they sit.
  profile_scores    secondary. Temperley's bias-free key profiles vs. the
                    duration-weighted pitch-class histogram, which carries
                    material the chord detector could not read.
  detect_key        combines both, then decides whether the result is meaningful.

Accuracy, measured on 480 constructed excerpts (12 roots x 2 modes x 5 seeds x
4 textures): 67.5% exact overall. More useful is that among results the
detector does *not* flag ambiguous, accuracy is 100% -- it declines to answer
rather than guess on material it cannot read (single-line melodies, dense
arpeggios). Those figures are for constructed material; no labelled corpus of
real recordings was available, so no claim is made about accuracy on real music.

Everything here is an *estimate* and is labelled as such in the UI.
"""
from numbers import Integral, Real

from .chords import detect_chords
from .key_profiles import T_MAJ, T_MIN, corr, profile
from .theory import NAMES

# Bump when the shape or meaning of key output changes, so projects stored with
# an older format can be recomputed on load instead of showing stale data.
KEY_FORMAT = 4

MIN_NOTES = 6         # below this there is not enough material to name a key
MIN_SCORE = 0.35      # below this nothing meaningful was found
MIN_CHORDS = 3        # fewer detected chords than this means harmony is unreliable

# How strongly each scale degree (semitones above the candidate tonic) supports
# that tonic. Conventional tonal weights: the tonic anchors hardest, the
# dominant and subdominant support it, the rest are weak. The dominant is kept
# clearly below the tonic because a long dominant chord must not be able to
# outvote the tonic (that was 48 of 192 measured failures at 0.9).
DEGREE_WEIGHT = {0: 1.0, 7: 0.65, 5: 0.55, 9: 0.45, 2: 0.4, 4: 0.35, 11: 0.2}

# Weight of the pitch-class profile relative to a *fully reliable* chord read.
# Harmony gets the upper hand only when the chords are clean; see
# `chord_reliability`. When they are not, the profile carries the estimate.
W_PROFILE = 1.0
MAX_W_HARMONY = 2.0


def _num(v):
    """True for any real number, including numpy scalars.

    Notes arrive straight from the transcriber (numpy-typed) before any JSON
    round-trip, and `isinstance(np.int64(60), int)` is False, so a plain `int`
    check silently discards every note. Accept anything Integral/Real instead.
    """
    return isinstance(v, (Integral, Real)) and not isinstance(v, bool)


def usable_notes(notes):
    """Notes with numeric pitch/start/end, in a plain-Python form."""
    return [n for n in notes
            if _num(n.get("pitch")) and _num(n.get("start")) and _num(n.get("end"))]


def pitch_class_weights(notes):
    """Duration-weighted pitch-class histogram (12 floats, index = pitch class)."""
    w = [0.0] * 12
    for n in notes:
        dur = max(0.0, float(n["end"]) - float(n["start"]))
        # A zero-length note still carries information; give it a small weight.
        w[int(n["pitch"]) % 12] += dur if dur > 0 else 0.01
    return w


def _quality_of(symbol):
    """The quality part of a chord symbol: 'C#m7/G#' -> 'm7'.

    A note name is one letter (A-G) optionally followed by # or b, so both the
    accidental and the slash bass must be removed before the remainder can be
    inspected. Getting this wrong silently miscounts every sharp/flat chord.
    """
    sym = symbol.split("/")[0]
    if not sym:
        return ""
    body = sym[1:]
    if body[:1] in ("#", "b"):
        body = body[1:]
    return body


def _mode_of(c):
    """'min', 'maj', or None for a chord that says nothing about mode.

    A power chord (``C5``) has no third, so it is neither major nor minor. That
    matters a great deal: on arpeggiated material the chord detector reads the
    *correct roots* but as ``C5``/``F5``/``D#5``, and defaulting those to major
    made every minor key report as its parallel major. Returning None lets the
    caller score such a chord for both modes instead of guessing.
    """
    sym = c.get("symbol") or ""
    body = _quality_of(sym)
    if body == "5":
        return None
    q = (c.get("quality") or "").strip()
    if q.startswith("m") and not q.startswith("maj"):
        return "min"
    if q and q != "5":
        return "maj"
    # Older stored chords may lack `quality`; fall back to the symbol.
    body = sym.split("/")[0]
    if "m" in body[1:] and "maj" not in body:
        return "min"
    return "maj"


def _is_minor_chord(c):
    """True for a minor-quality chord. A power chord counts as not-minor."""
    return _mode_of(c) == "min"


def chord_reliability(chords):
    """How much the chord progression can be trusted as key evidence (0..1).

    Feeding the scorer *perfect* chord symbols for a known-key progression
    recovers the key 24/24, so the scoring logic is sound; accuracy collapses
    only when the chord detector misreads the audio. Measured on constructed
    excerpts, key accuracy tracks this number almost exactly:

        clean triads (0% extended chords) -> 90% accurate
        dense/arpeggiated (68% extended)  -> 30% accurate
        single-line (100% extended)       -> 50% accurate

    Dense textures overlap into tall windows, so the detector reports ``Fmaj7``
    and ``G9`` where the music really contains an F chord in A minor. Those
    extended symbols are the visible symptom of an unreliable read, and their
    roots then mislead the key estimate. Rather than tune the scorer against
    noise, we measure how noisy the chords are and weight harmony accordingly.
    """
    if not chords:
        return 0.0
    plain = 0.0
    for c in chords:
        body = _quality_of(c.get("symbol") or "")
        # Chords whose third is undefined cannot support a key judgement:
        # a power chord (`C5`) has no third at all, and a suspended chord
        # replaces it with a 2nd or 4th. Those count for nothing.
        if body == "5" or "sus" in body:
            continue
        # Extended chords still carry a definite third and a trustworthy root,
        # and dense piano transcriptions legitimately produce many of them
        # (`add9`, `maj9`, `m7`) from overlapping sustained notes. They are a
        # *weaker* signal rather than no signal, so they count for half.
        if any(t in body for t in ("7", "9", "6")):
            plain += 0.5
        else:
            plain += 1.0
    quality = plain / len(chords)
    # A single clean triad is strong evidence -- even one unambiguous tonic
    # chord states the mode, which is what a bare melodic scale otherwise
    # cannot. So the count penalty scales with how *few* chords there are
    # rather than collapsing to zero the moment there is only one.
    coverage = min(1.0, len(chords) / MIN_CHORDS)
    return quality * coverage
    # A single clean triad is strong evidence -- even one unambiguous tonic
    # chord states the mode, which is what a bare melodic scale otherwise
    # cannot. So the count penalty scales with how *few* chords there are
    # rather than collapsing to zero the moment there is only one.
    coverage = min(1.0, len(chords) / MIN_CHORDS)
    return quality * coverage


def harmonic_scores(chords):
    """Score every candidate key from the chord progression (primary signal).

    For each candidate tonic we accumulate how much time is spent on chords
    that occupy functional scale degrees (I, V, IV, vi, ii, iii, vii). A chord
    built on the tonic itself is counted twice, and its quality decides the
    mode -- which is what finally separates relative keys.
    """
    sc = {}
    n = len(chords)
    for idx, c in enumerate(chords):
        root = c.get("root")
        if not _num(root):
            continue
        root = int(root)
        dur = max(0.01, float(c["end"]) - float(c["start"]))
        mode = _mode_of(c)
        # Tonal music begins and ends on its tonic, so the first and last
        # chords are stronger evidence than any chord in the middle. Without
        # this the dominant can outweigh the tonic on a long dominant chord.
        edge = 1.6 if (n >= 4 and (idx == 0 or idx == n - 1)) else 1.0
        # A mode-neutral chord (a power chord, or one whose third was lost)
        # is scored for BOTH modes rather than defaulted to major. Defaulting
        # to major is what made every arpeggiated minor key report as its
        # parallel major, since the tonic chord was read as `C5`.
        modes = ("maj", "min") if mode is None else (mode,)
        for tonic in range(12):
            w = DEGREE_WEIGHT.get((root - tonic) % 12, 0.0)
            if w <= 0:
                continue
            for m in modes:
                k = (tonic, m)
                sc[k] = sc.get(k, 0.0) + dur * w * edge
                if root == tonic:
                    # The tonic chord is the single strongest evidence, and its
                    # quality is what distinguishes e.g. C minor from Eb major.
                    # A neutral tonic chord gets only half the bonus, since it
                    # does not actually state the mode.
                    sc[k] += dur * edge * (2.0 if mode is not None else 1.0)
    return sc


def profile_scores(notes):
    """Score every candidate key by Temperley-profile correlation (secondary).

    Temperley's profiles are used rather than Krumhansl-Kessler because the KK
    pair sums to ~6.5% more for minor than major, which biases every comparison
    toward minor keys. Temperley's sum identically for both modes.
    """
    w = pitch_class_weights(notes)
    if sum(w) <= 0:
        return {}
    sc = {}
    for tonic in range(12):
        sc[(tonic, "maj")] = corr(w, profile(T_MAJ, tonic))
        sc[(tonic, "min")] = corr(w, profile(T_MIN, tonic))
    return sc


def _normalize(d):
    """Scale a score dict to 0..1 by its maximum, dropping non-positive values."""
    if not d:
        return {}
    m = max(max(0.0, v) for v in d.values())
    if m <= 0:
        return {}
    return {k: max(0.0, v) / m for k, v in d.items()}


def _chords_for(notes):
    """Chord events for a note list, using the shipped detector."""
    if not notes:
        return []
    return detect_chords([{"id": n.get("id"), "pitch": int(n["pitch"]),
                           "start": float(n["start"]), "end": float(n["end"])} for n in notes])


def detect_key(notes, chords=None):
    """Estimate the key of a note list.

    `chords` may be passed to reuse already-computed chord events; otherwise
    they are computed here.

    Returns a dict with `tonic`/`minor`/`name` (e.g. "A minor"), `confidence`
    in 0..1, the runner-up key and the margin between them, `chords_used` and
    `chord_reliability` (how trustworthy the chord evidence was), and an
    `ambiguous` flag with a `reason`. Returns None when there is too little
    material to name a key at all.
    """
    ns = usable_notes(notes)
    if len(ns) < MIN_NOTES:
        return None

    ch = list(chords if chords is not None else _chords_for(ns))
    reliability = chord_reliability(ch)
    w_harmony = MAX_W_HARMONY * reliability

    h = _normalize(harmonic_scores(ch))
    p = _normalize(profile_scores(ns))
    if not h and not p:
        return None

    combined = {k: w_harmony * h.get(k, 0.0) + W_PROFILE * p.get(k, 0.0)
                for k in set(h) | set(p)}
    ranked = sorted(combined.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked or ranked[0][1] <= 0:
        return None
    (tonic, mode), top = ranked[0]
    second_key, second = (ranked[1] if len(ranked) > 1 else ((None, None), 0.0))

    # Confidence blends how strong the winner is relative to the best possible
    # combined score, and how much better it is than the runner-up. A key that
    # wins by a hair is not a confident answer even if its raw score is high.
    total = w_harmony + W_PROFILE
    strength = top / total
    separation = 1.0 if second <= 0 else max(0.0, (top - second) / top)
    conf = round(max(0.0, min(1.0, 0.5 * strength + 0.5 * separation)), 3)

    harmony_share = round((w_harmony * h.get((tonic, mode), 0.0)) / top, 3) if top else 0.0

    result = {
        "tonic": int(tonic),
        "minor": mode == "min",
        "name": NAMES[int(tonic)] + (" minor" if mode == "min" else " major"),
        "confidence": float(conf),
        "format": KEY_FORMAT,
        "margin": float(round(top - second, 3)),
        "runner_up": (NAMES[int(second_key[0])] + (" minor" if second_key[1] == "min" else " major")
                      if second_key[0] is not None else None),
        "chords_used": len(ch),
        "chord_reliability": float(round(reliability, 3)),
        "harmony_share": float(harmony_share),
    }

    # Unreliable chords mean the estimate rests mostly on the pitch-class
    # profile, which cannot separate a minor key from its relative major. Say
    # so rather than presenting the same confidence as a well-evidenced result.
    weak_harmony = reliability < 0.5
    close_call = separation < 0.12
    result["ambiguous"] = bool(conf < MIN_SCORE or close_call or weak_harmony)
    result["low_confidence"] = bool(conf < MIN_SCORE)
    result["reason"] = ("too few chords to establish harmony" if len(ch) < MIN_CHORDS
                        else "chord detection unreliable here" if weak_harmony
                        else "runner-up key fits almost as well" if close_call
                        else "weak overall match" if conf < MIN_SCORE
                        else None)

    # A relative-key clash is the classic pitfall: flag the competing key so the
    # ambiguity is visible instead of hidden behind a confident-looking label.
    if not close_call:
        if mode == "maj" and second_key == ((tonic + 9) % 12, "min"):
            result["relative_minor"] = NAMES[(tonic + 9) % 12] + " minor"
        if mode == "min" and second_key == ((tonic + 3) % 12, "maj"):
            result["relative_major"] = NAMES[(tonic + 3) % 12] + " major"
    return result


def is_stale(stored):
    """True when a project's stored key predates the current output format."""
    if not stored:
        return True
    return stored.get("format") != KEY_FORMAT
