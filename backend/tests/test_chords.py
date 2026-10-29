"""Tests for chord estimation: vocabulary, inversions/slash basses, jitter merging."""
from app.music_analysis.chords import detect_chords, merge_chords


def N(i, p, start=0.0, end=1.0):
    return {"id": i, "pitch": p, "start": start, "end": end}


def test_c_major_root():
    c = detect_chords([N(0, 48), N(1, 52), N(2, 55)])
    assert c[0]["symbol"] == "C" and c[0]["inversion"] == 0


def test_first_inversion():
    c = detect_chords([N(0, 52), N(1, 55), N(2, 60)])
    assert c[0]["symbol"] == "C" and c[0]["inversion"] == 1


def test_too_few_notes():
    assert detect_chords([N(0, 60), N(1, 64)]) == []


def test_power_chord_from_two_notes():
    """Root + fifth with no third is the one unambiguous two-note case."""
    c = detect_chords([N(0, 45), N(1, 52)])
    assert c[0]["symbol"] == "A5"


def test_ambiguous_third_is_not_named():
    """C+E could be Cmaj or Am; we must not guess."""
    assert detect_chords([N(0, 60), N(1, 64)]) == []


def test_seventh_quality():
    c = detect_chords([N(0, 48), N(1, 52), N(2, 55), N(3, 58)])
    assert c[0]["symbol"] == "C7"


def test_major_seventh_quality():
    c = detect_chords([N(0, 48), N(1, 52), N(2, 55), N(3, 59)])
    assert c[0]["symbol"] == "Cmaj7"


def test_half_diminished():
    c = detect_chords([N(0, 47), N(1, 50), N(2, 53), N(3, 57)])
    assert c[0]["symbol"] == "Bm7b5"


def test_slash_chord_when_bass_is_not_a_chord_tone():
    """C major triad over F# in the bass -> C/F#."""
    c = detect_chords([N(0, 42), N(1, 48), N(2, 52), N(3, 55)])
    assert c[0]["symbol"] == "C/F#" and c[0]["inversion"] is None


def test_flicker_is_merged():
    """One sustained chord re-articulated must read as a single chord."""
    notes = [N(0, 48, 0.0, 0.30), N(1, 52, 0.0, 0.30), N(2, 55, 0.0, 0.30),
             N(3, 48, 0.35, 0.70), N(4, 52, 0.35, 0.70), N(5, 55, 0.35, 0.70),
             N(6, 48, 0.75, 1.10), N(7, 52, 0.75, 1.10), N(8, 55, 0.75, 1.10)]
    c = detect_chords(notes)
    assert len(c) == 1, c
    assert c[0]["symbol"] == "C" and round(c[0]["end"], 2) == 1.10


def test_merge_keeps_distinct_chords_apart():
    a = {"start": 0.0, "end": 0.5, "symbol": "C", "inversion": 0, "confidence": 1.0, "note_ids": [0]}
    b = {"start": 0.5, "end": 1.0, "symbol": "G", "inversion": 0, "confidence": 1.0, "note_ids": [1]}
    assert [c["symbol"] for c in merge_chords([a, b])] == ["C", "G"]


def test_merge_drops_unreadable_slivers():
    a = {"start": 0.0, "end": 0.5, "symbol": "C", "inversion": 0, "confidence": 1.0, "note_ids": [0]}
    # 30 ms "chord" sandwiched between unrelated material is noise
    b = {"start": 0.5, "end": 0.53, "symbol": "D", "inversion": 0, "confidence": 1.0, "note_ids": [1]}
    c = {"start": 0.6, "end": 1.1, "symbol": "G", "inversion": 0, "confidence": 1.0, "note_ids": [2]}
    assert [x["symbol"] for x in merge_chords([a, b, c])] == ["C", "G"]


def test_empty_input():
    assert detect_chords([]) == []
    assert merge_chords([]) == []
