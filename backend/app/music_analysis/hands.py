def estimate_hand(pitch):
    """Pitch-range heuristic only; the ambiguous middle register stays 'unknown'."""
    return "left" if pitch < 58 else "right" if pitch >= 62 else "unknown"
