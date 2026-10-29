"""Background job for video export.

Render state lives in its own file (video.json) next to the project rather than in
project.json, so the project metadata/status contract stays exactly as it was and
the export never interferes with the analysis job.

Every render gets a job id. The state file always names the job that wrote it, so a
client can tell whether the state it is looking at belongs to the render it started
or to a newer one - that is what keeps the panel from reporting "done" for a render
that is still running.
"""
import json
import threading
import time
import uuid

from app.core.config import settings
from app.db import store
from app.exports import video as V

_LOCK = threading.Lock()

STALE_SECONDS = 120  # a render that has not reported progress for this long is dead


def state_path(pid):
    return settings.data_dir / pid / "video.json"


def read_state(pid):
    f = state_path(pid)
    if not f.exists():
        return {"status": "idle"}
    try:
        st = json.loads(f.read_text())
    except Exception:
        return {"status": "idle"}
    return _check_stale(st)


def _check_stale(st):
    """Turn a dead render into a failed one.

    The worker lives in the server process, so a restart (a reload during
    development, a deploy) kills it mid-render. Without this the state would
    stay "rendering" for ever and every later render would be refused.
    """
    if st.get("status") in ("queued", "rendering"):
        touched = st.get("updated") or st.get("created") or 0
        if time.time() - touched > STALE_SECONDS:
            st = dict(st, status="failed", stage="error", eta_seconds=None,
                      error="The render was interrupted - the server stopped while it was running. Render it again.")
    return st


def write_state(pid, st):
    st = {**st, "updated": time.time()}
    with _LOCK:
        f = state_path(pid)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(st))
        except OSError:
            pass  # the project may have been deleted mid-render


def new_job_id():
    """Id of a single render, so a client can recognise its own job in the state."""
    return uuid.uuid4().hex[:12]


def start(pid, opts, job):
    """Publish the queued state before the render is handed to the background task.

    Writing it here (rather than from the worker) closes a race: without it the
    client could read the *previous* render's "done" state while its own render was
    still queued, and would then offer a download of a file that was about to be
    replaced.
    """
    prev = read_state(pid)
    st = {"status": "queued", "progress": 0.0, "stage": "queued", "error": None,
          "created": time.time(), "job": job, **opts}
    for k in ("file", "name", "bytes"):  # the last good render stays downloadable
        if prev.get(k):
            st[k] = prev[k]
    write_state(pid, st)
    return st


def run_video_job(pid, opts, job):
    """Render the project to a video file, reporting progress as it goes."""
    prev = read_state(pid)
    st = {"status": "rendering", "progress": 0.0, "stage": "starting", "error": None,
          "created": time.time(), "job": job, **opts}
    for k in ("file", "name", "bytes"):  # keep the last good render downloadable
        if prev.get(k):
            st[k] = prev[k]
    write_state(pid, st)
    started = time.time()

    def progress(frac, stage):
        elapsed = time.time() - started
        left = elapsed / frac - elapsed if frac > 0 else None
        st.update(progress=round(frac, 4), stage=stage, eta_seconds=round(left) if left else None)
        write_state(pid, st)

    try:
        out = V.render_project(pid, store.load(pid), opts, progress)
        st.update(status="done", progress=1.0, stage="done", error=None, file=out["file"],
                  name=out["name"], bytes=out["bytes"], seconds=round(out["seconds"], 1), eta_seconds=0)
    except Exception as ex:
        st.update(status="failed", stage="error", error=str(ex), eta_seconds=None)
    write_state(pid, st)
