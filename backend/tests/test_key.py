"""Tests for key estimation: known keys, ambiguity, and numeric robustness."""
import json
import numpy as np

from app.music_analysis.key import detect_key, pitch_class_weights

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def N(i, p, start=0.0, end=1.0):
    return {"id": i, "pitch": p, "start": start, "end": end}


def scale(root, minor, dur=1.0):
    """Ascending scale plus a held tonic triad, which clearly establishes a key."""
    steps = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    ns, i, t = [], 0, 0.0
    for o in range(2):
        for s in steps:
            ns.append(N(i, root + 12 * o + s, t, t + dur)); i += 1; t += dur
    for iv in (0, 3 if minor else 4, 7):
        ns.append(N(i, root + 12 + iv, t, t + dur * 3)); i += 1
    return ns


def progression(root, minor, spec, reps=3, dur=1.0):
    """spec is a list of (scale_degree, quality) where quality is maj/min/dim."""
    steps = [0, 2, 3, 5, 7, 8, 10] if minor else [0, 2, 4, 5, 7, 9, 11]
    ns, i, t = [], 0, 0.0
    for _ in range(reps):
        for deg, q in spec:
            base = steps[deg]
            for iv in (0, 4 if q == "maj" else 3, 7 if q != "dim" else 6):
                ns.append(N(i, root + base + iv, t, t + dur)); i += 1
            t += dur
    return ns


def test_c_major_scale():
    r = detect_key(scale(0, False))
    assert r["name"] == "C major" and not r["minor"]


def test_a_minor_scale():
    """A minor must not be reported as its relative major (C major).

    This is the classic failure of pitch-class methods: A natural minor and C
    major share the same seven pitch classes, so only the *quality of the tonic
    chord* (A-C-E = minor) can separate them.
    """
    r = detect_key(scale(9, True))
    assert r["name"] == "A minor" and r["minor"]


def test_all_twelve_major_keys():
    for root in range(12):
        r = detect_key(scale(root, False))
        assert r["name"] == f"{NAMES[root]} major", r


def test_all_twelve_minor_keys():
    for root in range(12):
        r = detect_key(scale(root, True))
        assert r["name"] == f"{NAMES[root]} minor", r


def test_bare_scale_without_chords_is_flagged_not_guessed():
    """A melodic line alone cannot establish a mode; the result must say so."""
    steps = [0, 2, 3, 5, 7, 8, 10]
    ns, t = [], 0.0
    for s in steps * 2:                       # no overlapping notes -> no chords
        ns.append(N(len(ns), 60 + s, t, t + 1.0)); t += 1.0
    r = detect_key(ns)
    assert r["ambiguous"], r


def test_progression_i_iv_v_i():
    r = detect_key(progression(5, False, [(0, "maj"), (3, "maj"), (4, "maj"), (0, "maj")]))
    assert r["name"] == "F major"


def test_progression_relative_minor_is_not_confused_with_its_major():
    """i-iv-V-i in D minor must not be reported as F major."""
    r = detect_key(progression(2, True, [(0, "min"), (3, "min"), (4, "maj"), (0, "min")]))
    assert r["name"] == "D minor"


def test_vi_iv_i_v_lands_on_the_tonic_not_the_relative_minor():
    r = detect_key(progression(0, False, [(5, "min"), (3, "maj"), (0, "maj"), (4, "maj")]))
    assert r["name"] == "C major"


def test_pitch_class_weights_are_duration_weighted():
    w = pitch_class_weights([N(0, 60, 0, 4.0), N(1, 62, 0, 1.0)])
    assert w[0] == 4.0 and w[2] == 1.0


def test_too_few_notes_returns_none():
    assert detect_key([]) is None
    assert detect_key([N(0, 60)]) is None
    assert detect_key([N(0, 60), N(1, 64)]) is None


def test_unkeyed_material_is_not_trusted():
    """A chromatic run has no tonal centre, so any label must be flagged.

    Every pitch class is present with equal weight, which fits all 24 candidate
    keys about equally. Naming one is unavoidable (something has to be the best
    guess) but it must never be presented as trustworthy.
    """
    r = detect_key([N(i, 60 + i) for i in range(12)])
    assert r is None or (r["ambiguous"] and r["confidence"] < 0.6), r


def test_whole_tone_scale_is_flagged_ambiguous():
    r = detect_key([N(i, 60 + 2 * i) for i in range(6)])
    assert r["ambiguous"]


def test_single_pitch_has_no_real_key_information():
    r = detect_key([N(i, 72) for i in range(30)])
    assert r["ambiguous"] and r["margin"] == 0.0


def test_relative_minor_is_not_reported_as_its_major():
    """The failure that motivated the harmony-first rewrite, at the unit level."""
    # A minor: i-iv-v-i, the same pitch classes as C major.
    r = detect_key(progression(9, True, [(0, "min"), (3, "min"), (4, "min"), (0, "min")]))
    assert r["name"] == "A minor", r


def test_power_chords_alone_are_not_treated_as_reliable():
    """A chord with no third cannot state a mode, so it must not be trusted."""
    from app.music_analysis.key import chord_reliability
    ch = [{"root": r, "symbol": f"{NAMES[r]}5", "quality": "5",
           "start": i, "end": i + 1} for i, r in enumerate([0, 5, 7])]
    assert chord_reliability(ch) == 0.0


def test_power_chord_is_mode_neutral_not_major():
    """The bug behind the relative-key failures, at the unit level.

    On arpeggiated material the detector reads the correct roots but as `C5`
    (no third). Those were defaulted to major, so every minor key came back as
    its parallel major -- C minor reported as C major.
    """
    from app.music_analysis.key import _mode_of
    assert _mode_of({"symbol": "C5", "quality": "5"}) is None
    assert _mode_of({"symbol": "Cm", "quality": "m"}) == "min"
    assert _mode_of({"symbol": "C", "quality": ""}) == "maj"


def test_sharp_and_flat_chord_symbols_parse_correctly():
    """A note name is a letter plus an optional accidental, so `G#5` is a power
    chord and `C#m7/G#` is a minor seventh -- not a major chord named 'G'."""
    from app.music_analysis.key import _quality_of
    assert _quality_of("G#5") == "5"
    assert _quality_of("D#m9") == "m9"
    assert _quality_of("C#m7/G#") == "m7"
    assert _quality_of("Bbadd9") == "add9"
    assert _quality_of("F#") == ""


def test_drum_track_is_not_given_a_confident_key():
    """Percussion transcribed as power chords must not produce a confident key.

    A real drum upload produced only `G#5`/`D#5`/`A#5` and was reported as a
    confident key. That is overclaiming and must be flagged instead.
    """
    ns = [N(i, p, i * 0.2, i * 0.2 + 0.15) for i, p in enumerate([44, 49, 56] * 8)]
    r = detect_key(ns)
    assert r["ambiguous"], r
    assert r["chord_reliability"] == 0.0, r


def test_extended_chords_lower_reliability():
    """Stacked/extended symbols are a weak signal, not a clean triad."""
    from app.music_analysis.key import chord_reliability
    clean = [{"root": r, "symbol": n, "quality": q, "start": i, "end": i + 1}
             for i, (r, n, q) in enumerate([(0, "C", ""), (5, "F", ""), (7, "G", "")])]
    messy = [{"root": r, "symbol": n, "quality": q, "start": i, "end": i + 1}
             for i, (r, n, q) in enumerate([(0, "Cmaj9", "maj9"), (5, "Fmaj7", "maj7"),
                                            (7, "G9", "9")])]
    assert chord_reliability(clean) > chord_reliability(messy)


def test_numpy_typed_notes_are_handled():
    """Transcriber output is numpy-typed; isinstance(np.int64, int) is False.

    A plain int check silently dropped every note, so this must be covered.
    """
    ns = [{"id": np.int64(i), "pitch": np.int64(60 + [0, 4, 7][i % 3]),
           "start": np.float64(i), "end": np.float64(i + 1)} for i in range(9)]
    r = detect_key(ns)
    assert r is not None and r["name"] == "C major"


def test_output_is_json_serializable():
    """Key is cached into project.json, so numpy scalars must not leak through."""
    ns = [{"id": np.int64(i), "pitch": np.int8(60 + [0, 2, 4, 5, 7, 9, 11][i % 7]),
           "start": np.float32(i * .5), "end": np.float32(i * .5 + .5)} for i in range(60)]
    r = detect_key(ns)
    assert json.loads(json.dumps(r)) == r


def test_deterministic():
    ns = scale(7, False)
    assert len({detect_key(ns)["name"] for _ in range(5)}) == 1


def test_confidence_within_bounds():
    for root in range(12):
        for minor in (False, True):
            r = detect_key(scale(root, minor))
            assert 0.0 <= r["confidence"] <= 1.0
