import io, pretty_midi, time
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)

def midi_bytes():
    pm = pretty_midi.PrettyMIDI(); i = pretty_midi.Instrument(0)
    i.notes = [pretty_midi.Note(80, p, 0, 1) for p in (60, 64, 67)]; pm.instruments.append(i)
    b = io.BytesIO(); pm.write(b); return b.getvalue()

def upload():
    r = client.post("/api/v1/projects", files={"file": ("t.mid", midi_bytes())}); assert r.status_code == 202
    return r.json()["project_id"]

def test_midi_flow():
    pid = upload(); assert client.get(f"/api/v1/projects/{pid}").json()["status"] == "completed"
    notes = client.get(f"/api/v1/projects/{pid}/notes").json(); assert [n["pitch"] for n in notes] == [60, 64, 67]
    assert client.get(f"/api/v1/projects/{pid}/chords").json()[0]["symbol"] == "C"
    assert client.patch(f"/api/v1/projects/{pid}/notes/0", json={"hand": "left"}).json()["user_edited"]
    assert client.delete(f"/api/v1/projects/{pid}/notes/1").status_code == 204
    assert client.post(f"/api/v1/projects/{pid}/export/midi").content[:4] == b"MThd"
    assert "pitch" in client.get(f"/api/v1/projects/{pid}/export/csv").text
    assert client.delete(f"/api/v1/projects/{pid}").status_code == 204
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404

def test_rejects_bad_type(): assert client.post("/api/v1/projects", files={"file": ("x.txt", b"hi")}).status_code == 415
def test_rejects_corrupt_audio(): assert client.post("/api/v1/projects", files={"file": ("x.wav", b"junk")}).status_code == 422
def test_traversal_blocked(): assert client.get("/api/v1/projects/..%2F..%2Fetc").status_code == 404

def test_video_export():
    pid = upload()
    pre = client.get(f"/api/v1/projects/{pid}/export/video/presets").json()
    assert pre["resolutions"] and pre["qualities"] and pre["codecs"]
    if not pre["ffmpeg"]["available"]: return  # no ffmpeg on this machine: nothing to render
    assert client.get(f"/api/v1/projects/{pid}/export/video/file").status_code == 404  # nothing rendered yet
    assert client.post(f"/api/v1/projects/{pid}/export/video?resolution=nope").status_code == 400
    assert client.post(f"/api/v1/projects/{pid}/export/video?quality=nope").status_code == 400
    assert client.post(f"/api/v1/projects/{pid}/export/video?codec=nope").status_code == 400
    from app.core.config import settings
    cap = settings.video_max_min; settings.video_max_min = 0.001  # shorter than this project
    try:
        assert client.post(f"/api/v1/projects/{pid}/export/video?end=99999").status_code == 400
    finally:
        settings.video_max_min = cap
    r = client.post(f"/api/v1/projects/{pid}/export/video?resolution=720p30&quality=standard&fps=10")
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["job"]
    st = client.get(f"/api/v1/projects/{pid}/export/video").json()
    for _ in range(120):
        if st["status"] in ("done", "failed"): break
        time.sleep(.5); st = client.get(f"/api/v1/projects/{pid}/export/video").json()
    assert st["status"] == "done", st
    assert st["width"] == 1280 and st["height"] == 720 and st["fps"] == 10
    assert st["job"] == r.json()["job"]  # the state names the render that produced it
    f = client.get(f"/api/v1/projects/{pid}/export/video/file")
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4"
    assert f.content[4:8] == b"ftyp" and len(f.content) > 1000  # a real mp4 container
    assert not list((settings.data_dir / pid / "video").glob(".*"))  # no half-written file left

def test_video_attaches_to_running_render():
    """A second click while a render is under way joins it instead of erroring."""
    from app.workers import video_jobs
    pid = upload()
    video_jobs.write_state(pid, {"status": "rendering", "progress": .5, "job": "job123", "width": 1280})
    r = client.post(f"/api/v1/projects/{pid}/export/video?resolution=720p30")
    assert r.status_code == 200
    assert r.json()["attached"] is True and r.json()["job"] == "job123"
    assert r.json()["note"]

def test_interrupted_render_does_not_block():
    """A render killed by a server restart must not block the next one for ever."""
    import json
    from app.core.config import settings
    pid = upload()
    old = time.time() - 9999
    (settings.data_dir / pid / "video.json").write_text(json.dumps(
        {"status": "rendering", "progress": .5, "job": "j1", "created": old, "updated": old}))
    st = client.get(f"/api/v1/projects/{pid}/export/video").json()
    assert st["status"] == "failed" and "interrupted" in st["error"]
    r = client.post(f"/api/v1/projects/{pid}/export/video?resolution=720p30")
    assert r.status_code == 200 and r.json()["status"] == "queued"

def test_video_download_survives_failed_render():
    """A failed render must not take away the download of the last good one."""
    from app.workers import video_jobs
    pid = upload()
    pre = client.get(f"/api/v1/projects/{pid}/export/video/presets").json()
    if not pre["ffmpeg"]["available"]: return
    client.post(f"/api/v1/projects/{pid}/export/video?resolution=720p30&quality=standard&fps=10")
    for _ in range(120):
        st = client.get(f"/api/v1/projects/{pid}/export/video").json()
        if st["status"] in ("done", "failed"): break
        time.sleep(.5)
    assert st["status"] == "done", st
    video_jobs.write_state(pid, {**st, "status": "failed", "error": "boom", "job": "other"})
    f = client.get(f"/api/v1/projects/{pid}/export/video/file")
    assert f.status_code == 200 and f.content[4:8] == b"ftyp"  # the old file is still there
