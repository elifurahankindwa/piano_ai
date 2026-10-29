NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
def note_name(p): return f"{NAMES[p % 12]}{p // 12 - 1}"
