"""Server-side video export: renders the piano roll and encodes it with ffmpeg.

The browser can only record the canvas it happens to be drawing right now, in real
time, using whatever codec the browser supports. That makes an export take as long as
the song plays and caps the quality at the browser's encoder settings. Rendering here
runs as fast as the CPU allows, always produces a file with an audio track, and
exposes the knobs that actually decide quality: resolution, frame rate and CRF.
"""
import heapq
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from bisect import bisect_right
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.core.config import AUDIO_EXT, settings

# Geometry and palette mirror the app's live view (frontend/src/app.js) so an export
# looks like the screen it came from.
BLACK_PITCH = {1, 3, 6, 8, 10}
BG = (15, 17, 21)
LANE = (20, 23, 29)
GRID = (35, 40, 52)
WHITE_KEY = (242, 242, 242)
BLACK_KEY = (26, 26, 26)
FG = (230, 232, 236)
MUT = (139, 147, 161)
HAND = {"left": (74, 163, 255), "right": (255, 159, 67), "unknown": (179, 157, 219)}
SPAN = 8.0  # seconds of lookahead shown in the roll, same window as the live view

RESOLUTIONS = [
    {"id": "720p30", "label": "720p · 30 fps", "width": 1280, "height": 720, "fps": 30},
    {"id": "720p60", "label": "720p · 60 fps", "width": 1280, "height": 720, "fps": 60},
    {"id": "1080p30", "label": "1080p · 30 fps", "width": 1920, "height": 1080, "fps": 30},
    {"id": "1080p60", "label": "1080p · 60 fps", "width": 1920, "height": 1080, "fps": 60},
    {"id": "1440p60", "label": "1440p · 60 fps", "width": 2560, "height": 1440, "fps": 60},
    {"id": "2160p30", "label": "4K · 30 fps", "width": 3840, "height": 2160, "fps": 30},
    {"id": "2160p60", "label": "4K · 60 fps", "width": 3840, "height": 2160, "fps": 60},
]

QUALITIES = [
    {"id": "standard", "label": "Standard · smaller file"},
    {"id": "high", "label": "High · recommended"},
    {"id": "maximum", "label": "Maximum · slowest, best detail"},
]

CODECS = [
    {"id": "h264", "label": "MP4 · H.264 (plays everywhere)", "ext": "mp4"},
    {"id": "h265", "label": "MP4 · H.265 (smaller, newer players)", "ext": "mp4"},
    {"id": "vp9", "label": "WebM · VP9", "ext": "webm"},
]

# CRF is the quality knob: lower is better quality and a bigger file. The scale
# differs per codec, so each tier maps to a value per codec rather than a constant.
CRF = {
    "standard": {"h264": 23, "h265": 30, "vp9": 32},
    "high": {"h264": 18, "h265": 26, "vp9": 24},
    "maximum": {"h264": 16, "h265": 22, "vp9": 18},
}
SPEED = {"standard": "veryfast", "high": "fast", "maximum": "slow"}


def ffmpeg_bin():
    """Locate ffmpeg: a system install first, then the binary bundled with imageio-ffmpeg."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe, "system"
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe(), "bundled"
    except Exception:
        return None, None


def presets():
    """Everything the UI needs to build the export options."""
    exe, source = ffmpeg_bin()
    return {"resolutions": RESOLUTIONS, "qualities": QUALITIES, "codecs": CODECS,
            "ffmpeg": {"available": bool(exe), "source": source, "max_minutes": settings.video_max_min}}


def _font(size):
    """Pillow's default font is a scalable TrueType since 10.1, so text stays crisp at 4K."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _geometry(width, height):
    """Keyboard/roll layout. Mirrors the live renderer: 52 white keys across, 0.6 ratio blacks."""
    kb_h = max(96, int(round(height * 0.16)))
    roll_h = height - kb_h
    rw = width / 52.0
    rb = rw * 0.6
    wi, c = {}, 0
    for p in range(21, 109):
        wi[p] = c
        if p % 12 not in BLACK_PITCH:
            c += 1
    keys = {}
    for p in range(21, 109):
        if p % 12 in BLACK_PITCH:
            keys[p] = (wi[p] * rw - rb / 2, rb)
        else:
            keys[p] = (wi[p] * rw + 0.5, rw - 1)
    return {"width": width, "height": height, "roll_h": roll_h, "kb_h": kb_h, "keys": keys,
            "lw": max(1, round(height / 540)),  # line weight that stays visible at any resolution
            "pad": max(8, round(height * 0.018))}


def _fmt_time(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _chord_at(chords, t):
    for c in chords:
        if c["start"] <= t < c["end"]:
            return c
    return None


def _draw(project, t, geo, fonts, base, sounding, incoming, chord):
    """One frame: falling notes, the keyboard they land on, and a small heads-up display."""
    width, height = geo["width"], geo["height"]
    roll_h, kb_h, keys = geo["roll_h"], geo["kb_h"], geo["keys"]
    lw = geo["lw"]
    img = base.copy()  # static layer: lanes, keyboard, title
    d = ImageDraw.Draw(img)

    def y_of(s):
        return roll_h - (s - t) / SPAN * roll_h

    # Second grid.
    first = math.ceil(t)
    for k in range(int(SPAN) + 2):
        y = y_of(first + k)
        if -lw <= y <= roll_h + lw:
            d.rectangle((0, y, width, y + lw), fill=GRID)

    # Notes: a note hangs above the keyboard line for its whole length and slides
    # down onto the line exactly when it starts, then shrinks as it plays out.
    for n in incoming + sounding:
        x, w = keys[n["pitch"]]
        yb = min(roll_h, y_of(n["start"]))
        yt = max(0.0, y_of(n["end"]))
        hgt = max(lw, yb - yt)
        col = HAND.get(n["hand"], HAND["unknown"])
        conf = n.get("confidence")
        if conf is not None and conf < 0.5:
            col = tuple(round(c * 0.4 + b * 0.6) for c, b in zip(col, BG))  # faded, as in the app
        d.rectangle((x, yt, x + w, yt + hgt), fill=col)
        if n["start"] <= t < n["end"]:
            d.rectangle((x, yt, x + w, yt + hgt), outline=(255, 255, 255), width=lw)

    # Keys that are sounding right now.
    lit = {n["pitch"]: n for n in sounding}
    for p, n in lit.items():
        x, w = keys[p]
        h = kb_h * 0.62 if p % 12 in BLACK_PITCH else kb_h
        d.rectangle((x, roll_h, x + w, roll_h + h), fill=HAND[n["hand"]])
        if p % 12 == 0:  # keep the octave label readable on a lit key
            d.text((x + 3, roll_h + kb_h - fonts["small"].size - lw), f"C{p // 12 - 1}", font=fonts["small"], fill=(90, 90, 90))

    # Playhead = the keyboard line itself.
    d.rectangle((0, roll_h - lw, width, roll_h), fill=(255, 255, 255))

    # Heads-up display (the parts that change every frame).
    pad = geo["pad"]
    dur = project.get("duration") or 0
    d.text((width - pad, pad), f"{_fmt_time(t)} / {_fmt_time(dur)}", font=fonts["small"], fill=MUT, anchor="ra")
    if chord:
        sym = chord["symbol"] + (f" ({chord['inversion']})" if chord.get("inversion") else "")
        d.text((width - pad, pad + fonts["small"].size + lw), sym, font=fonts["chord"], fill=FG, anchor="ra")
    return img


def _background(project, geo, fonts):
    """Static layer of a frame, drawn once and reused: lanes, keyboard, title."""
    width, height = geo["width"], geo["height"]
    roll_h, kb_h, keys = geo["roll_h"], geo["kb_h"], geo["keys"]
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    # Black-key lanes give the roll its vertical structure.
    for p in range(21, 109):
        if p % 12 in BLACK_PITCH:
            x, w = keys[p]
            d.rectangle((x, 0, x + w, roll_h), fill=LANE)

    # Keyboard.
    for p in range(21, 109):
        if p % 12 in BLACK_PITCH:
            continue
        x, w = keys[p]
        d.rectangle((x, roll_h, x + w, roll_h + kb_h), fill=WHITE_KEY)
        if p % 12 == 0:
            d.text((x + 3, roll_h + kb_h - fonts["small"].size - geo["lw"]), f"C{p // 12 - 1}", font=fonts["small"], fill=(90, 90, 90))
    for p in range(21, 109):
        if p % 12 in BLACK_PITCH:
            x, w = keys[p]
            d.rectangle((x, roll_h, x + w, roll_h + kb_h * 0.62), fill=BLACK_KEY)

    # Title block.
    pad = geo["pad"]
    title = project.get("name") or project.get("filename") or "Piano AI"
    d.text((pad, pad), title, font=fonts["title"], fill=FG)
    key = project.get("key") or {}
    kname = f"{key.get('name')} (estimate)" if key.get("name") else "key unknown"
    d.text((pad, pad + fonts["title"].size + geo["lw"]), f"{len(project.get('notes') or [])} notes · {kname}",
           font=fonts["small"], fill=MUT)
    return img


def _audio_path(project_dir, project):
    ext = project.get("ext") or ""
    if ext in AUDIO_EXT:
        return project_dir / ("source" + ext)
    return project_dir / "audio.wav"  # MIDI projects get a synthesized preview


def audio_duration(project_dir, project):
    """Length of the audio to render: the stored duration, or read off the file.

    MIDI projects have no stored duration (the preview is synthesized after upload),
    so their length has to come from the rendered audio itself.
    """
    if project.get("duration"):
        return float(project["duration"])
    f = _audio_path(project_dir, project)
    if f.exists():
        try:
            import soundfile as sf

            return float(sf.info(str(f)).duration)
        except Exception:
            pass
    return 0.0


def _command(exe, opts, audio, out_path):
    codec = opts["codec"]
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{opts['width']}x{opts['height']}",
           "-r", str(opts["fps"]), "-i", "pipe:0",
           "-ss", f"{opts['start']:.3f}", "-t", f"{opts['end'] - opts['start']:.3f}", "-i", str(audio),
           "-map", "0:v:0", "-map", "1:a:0"]
    if codec == "h264":
        cmd += ["-c:v", "libx264", "-crf", str(opts["crf"]), "-preset", opts["speed"], "-pix_fmt", "yuv420p",
                "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    elif codec == "h265":
        cmd += ["-c:v", "libx265", "-crf", str(opts["crf"]), "-preset", opts["speed"], "-pix_fmt", "yuv420p",
                "-tag:v", "hvc1", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    else:
        cmd += ["-c:v", "libvpx-vp9", "-crf", str(opts["crf"]), "-b:v", "0", "-row-mt", "1", "-cpu-used", "4",
                "-pix_fmt", "yuv420p", "-c:a", "libopus", "-b:a", "160k", "-avoid_negative_ts", "make_zero"]
    cmd += ["-shortest", str(out_path)]
    return cmd


def _drop(path):
    """Remove a leftover temporary file; a failed render should leave no debris."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def render_project(pid, project, opts, on_progress=None):
    """Render the project to a video file and return its path and size in bytes."""
    exe, _ = ffmpeg_bin()
    if not exe:
        raise RuntimeError("ffmpeg was not found. Install it system-wide, or run: pip install imageio-ffmpeg")

    project_dir = (settings.data_dir / pid).resolve()
    audio = _audio_path(project_dir, project)
    if not audio.exists():
        raise RuntimeError("No audio found for this project")

    width = int(opts["width"]) - int(opts["width"]) % 2  # H.264 needs even dimensions
    height = int(opts["height"]) - int(opts["height"]) % 2
    opts = dict(opts, width=width, height=height)
    fps = int(opts["fps"])
    start, end = float(opts["start"]), float(opts["end"])
    total = max(1, int(round((end - start) * fps)))

    out_dir = project_dir / "video"
    out_dir.mkdir(exist_ok=True)
    codec = next(c for c in CODECS if c["id"] == opts["codec"])
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", project.get("name") or "piano")[:60]
    out_path = out_dir / f"{name}-{opts['resolution']}-{opts['quality']}-{opts['codec']}.{codec['ext']}"
    # Encode into a hidden temporary file and move it into place at the end. The
    # file that is served is then always a complete, closed video - never one that
    # is still being written, which is what a download grabbed mid-render used to
    # get. The suffix still tells ffmpeg which container to write.
    tmp_path = out_dir / f".{name}-{opts.get('job') or 'render'}.part.{codec['ext']}"

    geo = _geometry(width, height)
    fonts = {"title": _font(max(14, round(height * 0.038))), "chord": _font(max(16, round(height * 0.05))),
             "small": _font(max(11, round(height * 0.024)))}
    base = _background(project, geo, fonts)

    notes = sorted(project.get("notes") or [], key=lambda n: n["start"])
    starts = [n["start"] for n in notes]
    chords = project.get("chords") or []

    cmd = _command(exe, opts, audio, tmp_path)
    err = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err)

    def ffmpeg_error():
        err.seek(0)
        return err.read().decode("utf-8", "replace").strip()

    active, idx = [], 0  # heap of (end, note) for what is sounding right now
    started = time.time()
    try:
        for i in range(total):
            t = start + i / fps
            while idx < len(notes) and notes[idx]["start"] <= t:
                heapq.heappush(active, (notes[idx]["end"], idx, notes[idx]))
                idx += 1
            while active and active[0][0] <= t:
                heapq.heappop(active)
            sounding = [n for _, _, n in active]
            lo = bisect_right(starts, t)
            hi = bisect_right(starts, t + SPAN)
            incoming = notes[lo:hi]
            img = _draw(project, t, geo, fonts, base, sounding, incoming, _chord_at(chords, t))
            proc.stdin.write(img.tobytes())
            if on_progress and (i % 5 == 0 or i == total - 1):
                on_progress((i + 1) / total * 0.97, "rendering frames")
        proc.stdin.close()
    except BrokenPipeError:
        proc.wait()
        message = ffmpeg_error()
        err.close()
        _drop(tmp_path)
        raise RuntimeError(f"ffmpeg stopped while encoding: {message or 'unknown error'}")
    except Exception:
        proc.kill()
        proc.wait()
        err.close()
        _drop(tmp_path)
        raise
    rc = proc.wait()
    message = ffmpeg_error()
    err.close()
    if rc != 0:
        _drop(tmp_path)
        raise RuntimeError(f"ffmpeg failed: {message or f'exit code {rc}'}")
    if not tmp_path.exists() or tmp_path.stat().st_size == 0:
        _drop(tmp_path)
        raise RuntimeError(f"ffmpeg produced no output: {message}")

    os.replace(tmp_path, out_path)  # the finished file appears in one step
    if on_progress:
        on_progress(1.0, "done")
    return {"file": str(out_path), "name": out_path.name, "bytes": out_path.stat().st_size,
            "seconds": time.time() - started}
