import pytest

from davinci_resolve_mcp import server as s
from davinci_resolve_mcp.client import ResolveError


def project_with_timeline():
    s.create_project("P")
    clips = s.import_media(["/m/a.mov", "/m/b.mov"])
    tl = s.create_timeline("T", [c["id"] for c in clips])
    return clips, tl


def test_status():
    st = s.resolve_status()
    assert st["studio"] and st["project"] is None
    s.create_project("P")
    assert s.resolve_status()["project"] == "P"


def test_no_project_errors():
    with pytest.raises(ResolveError, match="No project"):
        s.list_media()


def test_duplicate_project_fails():
    s.create_project("P")
    with pytest.raises(ResolveError):
        s.create_project("P")


def test_media_and_bins():
    s.create_project("P")
    s.create_bin("Footage")
    clips = s.import_media(["/m/a.mov"], bin="Master/Footage")
    assert clips[0]["name"] == "a.mov" and "Junk" not in clips[0]["properties"]
    assert s.list_media()["sub_bins"] == ["Footage"]
    assert len(s.list_media(recursive=True)["clips"]) == 1
    with pytest.raises(ResolveError, match="not found"):
        s.list_media(bin="Nope")


def test_timeline_items_and_studio_tools():
    _, _ = project_with_timeline()
    items = s.list_timeline_items("video")
    assert len(items) == 2
    iid = items[0]["id"]
    s.stabilize_item(iid)
    s.smart_reframe_item(iid)
    s.create_magic_mask(iid, "BI")
    s.set_cdl(iid, 1, "1 1 1", "0 0 0", "1 1 1", 1.0)
    s.apply_lut(iid, "/luts/x.cube")
    assert s.set_item_properties(iid, {"Zoom X": 2}) == {"Zoom X": True}
    assert s.get_item_properties(iid, ["Zoom X"]) == {"Zoom X": 2}
    with pytest.raises(ResolveError, match="not found"):
        s.stabilize_item("missing")


def test_markers_and_playhead():
    project_with_timeline()
    s.add_marker(10, name="hi")
    with pytest.raises(ResolveError):
        s.add_marker(10)
    assert s.list_markers()["10"]["name"] == "hi"
    s.delete_marker(10)
    assert s.list_markers() == {}
    s.set_playhead("01:00:01:00")
    assert s.get_playhead() == "01:00:01:00"


def test_timeline_studio_and_export():
    project_with_timeline()
    s.detect_scene_cuts()
    s.create_subtitles_from_audio({"SUBTITLE_LANGUAGE": "ENGLISH"})
    tl = s._timeline()
    assert tl.subtitle_settings == {"subtitle_language": "english"}
    s.export_timeline("/o/t.aaf", "AAF", "AAF_NEW")
    assert tl.exports[-1] == ("/o/t.aaf", "aaf", "aaf_new")
    with pytest.raises(ResolveError, match="Unknown Resolve constant"):
        s.export_timeline("/o/t", "BOGUS")


def test_transcribe_requires_one_target():
    s.create_project("P")
    with pytest.raises(ResolveError):
        s.transcribe_audio()
    clips = s.import_media(["/m/a.mov"])
    s.transcribe_audio(clip_id=clips[0]["id"])
    assert s._find_clip(clips[0]["id"]).transcribed


def test_render_flow():
    project_with_timeline()
    s.configure_render(format="MP4", codec="H.265", settings={"TargetDir": "/out"})
    job = s.add_render_job()
    s.start_rendering([job])
    prog = s.render_progress()
    assert prog["rendering"] and job in prog["jobs"]
    assert s.list_render_jobs()[0]["status"]["JobStatus"] == "Ready"
    s.stop_rendering()
    with pytest.raises(ResolveError, match="confirm"):
        s.delete_render_jobs(job_id=job)
    s.delete_render_jobs(job_id=job, confirm=True)
    assert s.list_render_jobs() == []


def test_delete_project_needs_confirm():
    s.create_project("P")
    with pytest.raises(ResolveError, match="confirm"):
        s.delete_project("P")
    s.delete_project("P", confirm=True)


def test_resolve_call_guards():
    clips, _ = project_with_timeline()
    assert s.resolve_call("resolve", "GetVersionString") == "20.0.0.1"
    iid = s.list_timeline_items()[0]["id"]
    assert s.resolve_call(f"item:{iid}", "GetFusionCompCount") == 2
    with pytest.raises(ResolveError, match="confirm"):
        s.resolve_call(f"item:{iid}", "DeleteMarkersByColor", ["Blue"])
    assert s.resolve_call(f"item:{iid}", "DeleteMarkersByColor", ["Blue"], confirm=True) is True
    with pytest.raises(ResolveError, match="Invalid method"):
        s.resolve_call("resolve", "__class__")
    with pytest.raises(ResolveError, match="no method"):
        s.resolve_call("resolve", "NopeNotReal")
    with pytest.raises(ResolveError, match="Unknown target"):
        s.resolve_call("bogus", "GetName")
    # Resolve objects serialise to a summary instead of crashing
    assert s.resolve_call("media_pool", "GetRootFolder")["name"] == "Master"
