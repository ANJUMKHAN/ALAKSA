"""FastMCP server exposing the DaVinci Resolve Studio scripting API."""

from __future__ import annotations

import re
from typing import Any, Iterator, Literal

from mcp.server.fastmcp import FastMCP

from .client import ResolveError, session

mcp = FastMCP(
    "davinci-resolve-studio",
    instructions=(
        "Controls a running DaVinci Resolve Studio instance. Start with "
        "resolve_status. Media pool clips and timeline items are addressed by "
        "their unique id (returned by list_media / list_timeline_items). "
        "Use resolve_call for API methods that have no dedicated tool."
    ),
)

TrackType = Literal["video", "audio", "subtitle"]
TRACK_TYPES = ("video", "audio", "subtitle")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _resolve() -> Any:
    return session.resolve()


def _project_manager() -> Any:
    pm = _resolve().GetProjectManager()
    if not pm:
        raise ResolveError("Could not get the project manager.")
    return pm


def _project() -> Any:
    project = _project_manager().GetCurrentProject()
    if not project:
        raise ResolveError("No project is open. Use open_project or create_project.")
    return project


def _media_pool() -> Any:
    return _project().GetMediaPool()


def _timeline() -> Any:
    timeline = _project().GetCurrentTimeline()
    if not timeline:
        raise ResolveError("No current timeline. Use set_current_timeline or create_timeline.")
    return timeline


def _check(result: Any, action: str) -> Any:
    """Resolve signals failure with False/None; turn that into an error."""
    if result is None or result is False:
        raise ResolveError(f"Resolve reported failure while trying to {action}.")
    return result


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "GetName"):
        try:
            return {"object": type(value).__name__, "name": value.GetName(),
                    "id": value.GetUniqueId() if hasattr(value, "GetUniqueId") else None}
        except Exception:
            pass
    return repr(value)


def _constant(name: str, prefix: str = "") -> Any:
    """Look up a Resolve constant such as EXPORT_AAF or SUBTITLE_LANGUAGE."""
    resolve = _resolve()
    for candidate in (name, prefix + name.upper(), prefix + name):
        if candidate and hasattr(resolve, candidate):
            return getattr(resolve, candidate)
    raise ResolveError(f"Unknown Resolve constant '{name}'.")


def _walk_folders(folder: Any) -> Iterator[Any]:
    yield folder
    for sub in folder.GetSubFolderList() or []:
        yield from _walk_folders(sub)


def _find_folder(path: str) -> Any:
    """Find a bin by path like 'Master/Footage' (leading 'Master' optional)."""
    root = _media_pool().GetRootFolder()
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if parts and parts[0] == root.GetName():
        parts = parts[1:]
    folder = root
    for part in parts:
        for sub in folder.GetSubFolderList() or []:
            if sub.GetName() == part:
                folder = sub
                break
        else:
            raise ResolveError(f"Bin '{path}' not found (no '{part}' in '{folder.GetName()}').")
    return folder


def _find_clip(clip_id: str) -> Any:
    for folder in _walk_folders(_media_pool().GetRootFolder()):
        for clip in folder.GetClipList() or []:
            if clip.GetUniqueId() == clip_id:
                return clip
    raise ResolveError(f"Media pool clip '{clip_id}' not found.")


def _iter_timeline_items(timeline: Any) -> Iterator[tuple[str, int, Any]]:
    for track_type in TRACK_TYPES:
        for index in range(1, int(timeline.GetTrackCount(track_type) or 0) + 1):
            for item in timeline.GetItemListInTrack(track_type, index) or []:
                yield track_type, index, item


def _find_item(item_id: str) -> Any:
    for _, _, item in _iter_timeline_items(_timeline()):
        if item.GetUniqueId() == item_id:
            return item
    raise ResolveError(f"Timeline item '{item_id}' not found on the current timeline.")


def _find_timeline(name_or_id: str) -> Any:
    project = _project()
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        tl = project.GetTimelineByIndex(i)
        if name_or_id in (tl.GetName(), tl.GetUniqueId()):
            return tl
    raise ResolveError(f"Timeline '{name_or_id}' not found.")


def _clip_summary(clip: Any) -> dict:
    props = clip.GetClipProperty() or {}
    keys = ("Type", "Clip Name", "File Path", "Duration", "FPS", "Resolution", "Frames")
    return {
        "id": clip.GetUniqueId(),
        "name": clip.GetName(),
        "properties": {k: props[k] for k in keys if k in props},
    }


def _item_summary(track_type: str, track_index: int, item: Any) -> dict:
    return {
        "id": item.GetUniqueId(),
        "name": item.GetName(),
        "track_type": track_type,
        "track_index": track_index,
        "start": item.GetStart(),
        "end": item.GetEnd(),
        "duration": item.GetDuration(),
    }


# --------------------------------------------------------------------------
# connection / navigation
# --------------------------------------------------------------------------

@mcp.tool()
def resolve_status() -> dict:
    """Report Resolve version/edition, current page, project and timeline.

    `studio` is false on the free edition, where external scripting (and so
    this server) will not work.
    """
    resolve = _resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline() if project else None
    product = resolve.GetProductName()
    return {
        "product": product,
        "studio": "studio" in (product or "").lower(),
        "version": resolve.GetVersionString(),
        "page": resolve.GetCurrentPage(),
        "project": project.GetName() if project else None,
        "timeline": timeline.GetName() if timeline else None,
    }


@mcp.tool()
def open_page(page: Literal["media", "cut", "edit", "fusion", "color", "fairlight", "deliver"]) -> str:
    """Switch Resolve to the given page."""
    _check(_resolve().OpenPage(page), f"open the {page} page")
    return page


# --------------------------------------------------------------------------
# projects
# --------------------------------------------------------------------------

@mcp.tool()
def list_projects() -> dict:
    """List projects and folders in the project manager's current folder."""
    pm = _project_manager()
    return {
        "projects": pm.GetProjectListInCurrentFolder() or [],
        "folders": pm.GetFolderListInCurrentFolder() or [],
        "database": _jsonable(pm.GetCurrentDatabase()),
    }


@mcp.tool()
def open_project(name: str) -> str:
    """Open a project by name from the current project-manager folder."""
    _check(_project_manager().LoadProject(name), f"open project '{name}'")
    return name


@mcp.tool()
def create_project(name: str) -> str:
    """Create and open a new project."""
    _check(_project_manager().CreateProject(name), f"create project '{name}' (name may exist)")
    return name


@mcp.tool()
def save_project() -> str:
    """Save the current project."""
    _check(_project_manager().SaveProject(), "save the project")
    return _project().GetName()


@mcp.tool()
def close_project() -> str:
    """Close the current project (saves it first)."""
    pm = _project_manager()
    project = _project()
    name = project.GetName()
    pm.SaveProject()
    _check(pm.CloseProject(project), "close the project")
    return name


@mcp.tool()
def delete_project(name: str, confirm: bool = False) -> str:
    """Permanently delete a project. Requires confirm=true."""
    if not confirm:
        raise ResolveError("delete_project is destructive; call again with confirm=true.")
    _check(_project_manager().DeleteProject(name), f"delete project '{name}'")
    return name


@mcp.tool()
def export_project(name: str, path: str, with_stills_and_luts: bool = True) -> str:
    """Export a project to a .drp file at `path`."""
    _check(_project_manager().ExportProject(name, path, with_stills_and_luts), "export the project")
    return path


@mcp.tool()
def import_project(path: str, name: str | None = None) -> str:
    """Import a .drp project file, optionally under a new name."""
    pm = _project_manager()
    _check(pm.ImportProject(path, name) if name else pm.ImportProject(path), "import the project")
    return path


@mcp.tool()
def get_project_settings(names: list[str] | None = None) -> dict:
    """Read project settings. Pass names (e.g. ['timelineFrameRate']) or omit for all."""
    project = _project()
    if not names:
        return _jsonable(project.GetSetting("") or {})
    return {n: _jsonable(project.GetSetting(n)) for n in names}


@mcp.tool()
def set_project_settings(settings: dict[str, str]) -> dict:
    """Set project settings, e.g. {'timelineFrameRate': '24', 'timelineResolutionWidth': '3840'}."""
    project = _project()
    return {k: bool(project.SetSetting(k, str(v))) for k, v in settings.items()}


# --------------------------------------------------------------------------
# media storage & media pool
# --------------------------------------------------------------------------

@mcp.tool()
def browse_media_storage(path: str | None = None) -> dict:
    """List mounted volumes, or the sub-folders and files under `path`."""
    storage = _resolve().GetMediaStorage()
    if not path:
        return {"volumes": storage.GetMountedVolumeList() or []}
    return {
        "folders": storage.GetSubFolderList(path) or [],
        "files": storage.GetFileList(path) or [],
    }


@mcp.tool()
def import_media(paths: list[str], bin: str | None = None) -> list[dict]:
    """Import files/folders into the media pool, optionally into bin path 'Master/Footage'."""
    pool = _media_pool()
    previous = pool.GetCurrentFolder()
    if bin:
        _check(pool.SetCurrentFolder(_find_folder(bin)), f"switch to bin '{bin}'")
    try:
        clips = _check(pool.ImportMedia(paths), "import media")
    finally:
        if bin:
            pool.SetCurrentFolder(previous)
    return [_clip_summary(c) for c in clips]


@mcp.tool()
def list_media(bin: str | None = None, recursive: bool = False) -> dict:
    """List clips and sub-bins in a bin (default: the current bin)."""
    pool = _media_pool()
    folder = _find_folder(bin) if bin else pool.GetCurrentFolder()
    folders = list(_walk_folders(folder)) if recursive else [folder]
    return {
        "bin": folder.GetName(),
        "sub_bins": [f.GetName() for f in folder.GetSubFolderList() or []],
        "clips": [
            dict(_clip_summary(c), bin=f.GetName())
            for f in folders for c in f.GetClipList() or []
        ],
    }


@mcp.tool()
def create_bin(name: str, parent: str | None = None) -> str:
    """Create a bin inside `parent` (default: the current bin)."""
    pool = _media_pool()
    parent_folder = _find_folder(parent) if parent else pool.GetCurrentFolder()
    _check(pool.AddSubFolder(parent_folder, name), f"create bin '{name}'")
    return name


@mcp.tool()
def get_clip_properties(clip_id: str) -> dict:
    """Return all clip properties, metadata and markers for a media pool clip."""
    clip = _find_clip(clip_id)
    return {
        "properties": _jsonable(clip.GetClipProperty() or {}),
        "metadata": _jsonable(clip.GetMetadata() or {}),
        "markers": _jsonable(clip.GetMarkers() or {}),
    }


@mcp.tool()
def set_clip_metadata(clip_id: str, metadata: dict[str, str]) -> dict:
    """Set metadata fields (e.g. 'Comments', 'Keywords', 'Scene') on a clip."""
    clip = _find_clip(clip_id)
    return {k: bool(clip.SetMetadata(k, v)) for k, v in metadata.items()}


@mcp.tool()
def transcribe_audio(clip_id: str | None = None, bin: str | None = None, clear: bool = False) -> str:
    """[Studio] Transcribe (or clear transcription of) a clip, or every clip in a bin."""
    if (clip_id is None) == (bin is None):
        raise ResolveError("Provide exactly one of clip_id or bin.")
    target = _find_clip(clip_id) if clip_id else _find_folder(bin)
    action = target.ClearTranscription if clear else target.TranscribeAudio
    _check(action(), "clear transcription" if clear else "transcribe audio")
    return "cleared" if clear else "transcribed"


# --------------------------------------------------------------------------
# timelines
# --------------------------------------------------------------------------

@mcp.tool()
def list_timelines() -> list[dict]:
    """List all timelines in the current project."""
    project = _project()
    current = project.GetCurrentTimeline()
    current_id = current.GetUniqueId() if current else None
    out = []
    for i in range(1, int(project.GetTimelineCount() or 0) + 1):
        tl = project.GetTimelineByIndex(i)
        out.append({"id": tl.GetUniqueId(), "name": tl.GetName(), "current": tl.GetUniqueId() == current_id})
    return out


@mcp.tool()
def set_current_timeline(timeline: str) -> str:
    """Make the timeline with this name or id current."""
    tl = _find_timeline(timeline)
    _check(_project().SetCurrentTimeline(tl), "set the current timeline")
    return tl.GetName()


@mcp.tool()
def create_timeline(name: str, clip_ids: list[str] | None = None) -> dict:
    """Create a timeline, empty or from the given media pool clips (in order)."""
    pool = _media_pool()
    if clip_ids:
        tl = pool.CreateTimelineFromClips(name, [_find_clip(c) for c in clip_ids])
    else:
        tl = pool.CreateEmptyTimeline(name)
    _check(tl, f"create timeline '{name}'")
    return {"id": tl.GetUniqueId(), "name": tl.GetName()}


@mcp.tool()
def append_to_timeline(clip_ids: list[str]) -> int:
    """Append whole media pool clips to the end of the current timeline."""
    _timeline()
    items = _check(_media_pool().AppendToTimeline([_find_clip(c) for c in clip_ids]), "append clips")
    return len(items)


@mcp.tool()
def append_subclip_to_timeline(
    clip_id: str, start_frame: int, end_frame: int,
    track_index: int = 1, record_frame: int | None = None,
    media_type: Literal["both", "video", "audio"] = "both",
) -> dict:
    """Append the [start_frame, end_frame] range of a clip to a track, optionally at record_frame."""
    _timeline()
    info: dict[str, Any] = {
        "mediaPoolItem": _find_clip(clip_id),
        "startFrame": start_frame, "endFrame": end_frame, "trackIndex": track_index,
    }
    if record_frame is not None:
        info["recordFrame"] = record_frame
    if media_type != "both":
        info["mediaType"] = 1 if media_type == "video" else 2
    items = _check(_media_pool().AppendToTimeline([info]), "append subclip")
    return _item_summary(media_type, track_index, items[0])


@mcp.tool()
def import_timeline(path: str, import_source_clips: bool = True) -> dict:
    """Import AAF/EDL/XML/FCPXML/DRT/OTIO/ADL as a new timeline."""
    tl = _check(
        _media_pool().ImportTimelineFromFile(path, {"importSourceClips": import_source_clips}),
        "import the timeline",
    )
    return {"id": tl.GetUniqueId(), "name": tl.GetName()}


@mcp.tool()
def export_timeline(path: str, export_type: str, export_subtype: str | None = None) -> str:
    """Export the current timeline.

    export_type: AAF, DRT, EDL, FCP_7_XML, FCPXML_1_8..1_10, HDR_10_PROFILE_A/B,
    CSV, TAB, DOLBY_VISION_VER_2_9/4_0/5_1, OTIO, TEXT_CSV, TEXT_TAB, ALE, ALE_CDL.
    export_subtype (AAF/EDL only): e.g. AAF_NEW, AAF_EXISTING, CDL, SDL, MISSING_CLIPS, NONE.
    """
    kind = _constant(export_type, "EXPORT_")
    if export_subtype:
        sub = _constant(export_subtype, "EXPORT_")
        ok = _timeline().Export(path, kind, sub)
    else:
        ok = _timeline().Export(path, kind)
    _check(ok, "export the timeline")
    return path


@mcp.tool()
def list_timeline_items(track_type: TrackType | None = None) -> list[dict]:
    """List items on the current timeline, optionally limited to one track type."""
    return [
        _item_summary(t, i, item)
        for t, i, item in _iter_timeline_items(_timeline())
        if track_type in (None, t)
    ]


@mcp.tool()
def add_marker(frame: int, color: str = "Blue", name: str = "", note: str = "",
               duration: int = 1, custom_data: str = "") -> int:
    """Add a marker to the current timeline at `frame`. Returns the frame."""
    _check(_timeline().AddMarker(frame, color, name, note, duration, custom_data),
           f"add a marker at frame {frame} (one may already exist there)")
    return frame


@mcp.tool()
def list_markers() -> dict:
    """Return the current timeline's markers keyed by frame."""
    return {str(k): _jsonable(v) for k, v in (_timeline().GetMarkers() or {}).items()}


@mcp.tool()
def delete_marker(frame: int) -> int:
    """Delete the timeline marker at `frame`."""
    _check(_timeline().DeleteMarkerAtFrame(frame), f"delete marker at {frame}")
    return frame


@mcp.tool()
def get_playhead() -> str:
    """Return the current timeline timecode."""
    return _timeline().GetCurrentTimecode()


@mcp.tool()
def set_playhead(timecode: str) -> str:
    """Move the playhead to a timecode like '01:00:05:12'."""
    _check(_timeline().SetCurrentTimecode(timecode), f"set timecode {timecode}")
    return timecode


@mcp.tool()
def detect_scene_cuts() -> str:
    """[Studio] Detect scene cuts in the current timeline's clips and add cuts."""
    _check(_timeline().DetectSceneCuts(), "detect scene cuts")
    return "ok"


@mcp.tool()
def create_subtitles_from_audio(settings: dict[str, Any] | None = None) -> str:
    """[Studio] Auto-generate subtitles from the current timeline's audio.

    `settings` keys/values are Resolve constant names, e.g.
    {"SUBTITLE_LANGUAGE": "ENGLISH", "CAPTION_PRESET": "SUBTITLE_DEFAULT",
     "CHARS_PER_LINE": 42, "LINE_BREAK": "LINE_SINGLE", "GAP": 0}.
    String values naming a Resolve constant are resolved; others pass through.
    """
    resolve = _resolve()
    resolved: dict[Any, Any] = {}
    for key, value in (settings or {}).items():
        resolved_key = _constant(key)
        resolved[resolved_key] = (
            getattr(resolve, value) if isinstance(value, str) and hasattr(resolve, value) else value
        )
    _check(_timeline().CreateSubtitlesFromAudio(resolved), "create subtitles from audio")
    return "ok"


# --------------------------------------------------------------------------
# timeline items: Studio AI tools, properties, color
# --------------------------------------------------------------------------

@mcp.tool()
def get_item_properties(item_id: str, names: list[str] | None = None) -> dict:
    """Read timeline item properties (Pan, Zoom, Opacity, CropLeft, ...). Omit names for all."""
    item = _find_item(item_id)
    if names:
        return {n: _jsonable(item.GetProperty(n)) for n in names}
    return _jsonable(item.GetProperty() or {})


@mcp.tool()
def set_item_properties(item_id: str, properties: dict[str, Any]) -> dict:
    """Set timeline item properties, e.g. {"Zoom X": 1.2, "Opacity": 80}."""
    item = _find_item(item_id)
    return {k: bool(item.SetProperty(k, v)) for k, v in properties.items()}


@mcp.tool()
def stabilize_item(item_id: str) -> str:
    """[Studio] Run stabilization on a timeline item."""
    _check(_find_item(item_id).Stabilize(), "stabilize the item")
    return "ok"


@mcp.tool()
def smart_reframe_item(item_id: str) -> str:
    """[Studio] Run Smart Reframe on a timeline item (set the timeline to the target aspect first)."""
    _check(_find_item(item_id).SmartReframe(), "smart reframe the item")
    return "ok"


@mcp.tool()
def create_magic_mask(item_id: str, mode: Literal["F", "B", "BI"] = "F") -> str:
    """[Studio] Create a Magic Mask on the item: F=forward, B=backward, BI=bidirectional."""
    _check(_find_item(item_id).CreateMagicMask(mode), "create a magic mask")
    return "ok"


@mcp.tool()
def set_cdl(item_id: str, node_index: int, slope: str, offset: str, power: str,
            saturation: float) -> str:
    """Set a CDL grade on a node. slope/offset/power are 'R G B' strings, e.g. '1.0 1.0 1.0'."""
    cdl = {"NodeIndex": str(node_index), "Slope": slope, "Offset": offset,
           "Power": power, "Saturation": str(saturation)}
    _check(_find_item(item_id).SetCDL(cdl), "set the CDL")
    return "ok"


@mcp.tool()
def apply_lut(item_id: str, lut_path: str, node_index: int = 1) -> str:
    """Apply a LUT file (absolute path, or relative to Resolve's LUT folder) to a node."""
    graph = _find_item(item_id).GetNodeGraph()
    _check(graph, "get the node graph")
    _check(graph.SetLUT(node_index, lut_path), f"apply LUT '{lut_path}'")
    return "ok"


@mcp.tool()
def grab_still() -> str:
    """Grab a still of the current frame to the gallery (Color page context)."""
    _check(_timeline().GrabStill(), "grab a still")
    return "ok"


# --------------------------------------------------------------------------
# render / deliver
# --------------------------------------------------------------------------

@mcp.tool()
def get_render_options(format: str | None = None) -> dict:
    """List render formats, the codecs for `format` (if given), and saved presets."""
    project = _project()
    out: dict[str, Any] = {
        "formats": _jsonable(project.GetRenderFormats() or {}),
        "presets": _jsonable(project.GetRenderPresetList() or []),
    }
    if format:
        out["codecs"] = _jsonable(project.GetRenderCodecs(format) or {})
    return out


@mcp.tool()
def configure_render(
    preset: str | None = None, format: str | None = None, codec: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict:
    """Configure the current render. Optionally load a preset, set format+codec, then
    apply `settings` (e.g. {"TargetDir": "/out", "CustomName": "final", "SelectAllFrames": true,
    "FormatWidth": 3840, "FormatHeight": 2160, "FrameRate": 24, "ExportAudio": true})."""
    project = _project()
    applied: dict[str, Any] = {}
    if preset:
        _check(project.LoadRenderPreset(preset), f"load render preset '{preset}'")
        applied["preset"] = preset
    if format or codec:
        if not (format and codec):
            raise ResolveError("format and codec must be given together.")
        _check(project.SetCurrentRenderFormatAndCodec(format, codec), f"set format {format}/{codec}")
        applied["format"], applied["codec"] = format, codec
    if settings:
        _check(project.SetRenderSettings(settings), "apply render settings")
        applied["settings"] = settings
    return applied


@mcp.tool()
def add_render_job() -> str:
    """Add the current timeline with the current render configuration to the render queue."""
    return _check(_project().AddRenderJob(), "add a render job")


@mcp.tool()
def list_render_jobs() -> list[dict]:
    """List queued render jobs with their status."""
    project = _project()
    return [
        dict(_jsonable(job), status=_jsonable(project.GetRenderJobStatus(job["JobId"])))
        for job in project.GetRenderJobList() or []
    ]


@mcp.tool()
def start_rendering(job_ids: list[str] | None = None) -> str:
    """Start rendering the given jobs, or the whole queue if omitted."""
    project = _project()
    ok = project.StartRendering(job_ids) if job_ids else project.StartRendering()
    _check(ok, "start rendering")
    return "started"


@mcp.tool()
def render_progress() -> dict:
    """Return whether a render is running and the status of every job."""
    project = _project()
    return {
        "rendering": bool(project.IsRenderingInProgress()),
        "jobs": {
            j["JobId"]: _jsonable(project.GetRenderJobStatus(j["JobId"]))
            for j in project.GetRenderJobList() or []
        },
    }


@mcp.tool()
def stop_rendering() -> str:
    """Stop any render in progress."""
    _project().StopRendering()
    return "stopped"


@mcp.tool()
def delete_render_jobs(job_id: str | None = None, all_jobs: bool = False, confirm: bool = False) -> str:
    """Delete one render job, or all of them with all_jobs=true. Requires confirm=true."""
    if not confirm:
        raise ResolveError("delete_render_jobs is destructive; call again with confirm=true.")
    project = _project()
    if all_jobs:
        _check(project.DeleteAllRenderJobs(), "delete all render jobs")
    elif job_id:
        _check(project.DeleteRenderJob(job_id), f"delete render job {job_id}")
    else:
        raise ResolveError("Provide job_id or all_jobs=true.")
    return "deleted"


# --------------------------------------------------------------------------
# generic escape hatch
# --------------------------------------------------------------------------

_METHOD_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_TARGETS = ("resolve", "project_manager", "project", "media_pool", "media_storage",
            "timeline", "current_folder", "root_folder", "fusion")


def _call_target(target: str) -> Any:
    kind, _, ident = target.partition(":")
    if kind == "clip" and ident:
        return _find_clip(ident)
    if kind == "item" and ident:
        return _find_item(ident)
    resolve = _resolve()
    if target == "resolve":
        return resolve
    if target == "project_manager":
        return _project_manager()
    if target == "project":
        return _project()
    if target == "media_pool":
        return _media_pool()
    if target == "media_storage":
        return resolve.GetMediaStorage()
    if target == "timeline":
        return _timeline()
    if target == "current_folder":
        return _media_pool().GetCurrentFolder()
    if target == "root_folder":
        return _media_pool().GetRootFolder()
    if target == "fusion":
        return resolve.Fusion()
    raise ResolveError(f"Unknown target '{target}'. Use one of {_TARGETS}, 'clip:<id>' or 'item:<id>'.")


@mcp.tool()
def resolve_call(target: str, method: str, args: list[Any] | None = None,
                 confirm: bool = False) -> Any:
    """Call any Resolve scripting API method that has no dedicated tool.

    target: resolve | project_manager | project | media_pool | media_storage |
            timeline | current_folder | root_folder | fusion | clip:<id> | item:<id>
    method: API method name, e.g. "GetFusionCompCount" (see Resolve's README.txt).
    args:   positional arguments as JSON. Resolve objects cannot be passed; use
            the dedicated tools when a method needs clip/timeline objects.
    Methods starting with Delete/Remove/Clear require confirm=true.
    """
    if not _METHOD_RE.match(method):
        raise ResolveError(f"Invalid method name '{method}'.")
    if method.startswith(("Delete", "Remove", "Clear")) and not confirm:
        raise ResolveError(f"{method} is destructive; call again with confirm=true.")
    obj = _call_target(target)
    fn = getattr(obj, method, None)
    if not callable(fn):
        raise ResolveError(f"{target} has no method '{method}'.")
    return _jsonable(fn(*(args or [])))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
