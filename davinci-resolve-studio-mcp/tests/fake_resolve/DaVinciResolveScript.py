"""Minimal in-memory stand-in for Blackmagic's DaVinciResolveScript module."""

import itertools

_ids = itertools.count(1)


def _uid():
    return f"id{next(_ids)}"


class Item:
    def __init__(self, name, start, end):
        self.name, self.start, self.end, self.uid = name, start, end, _uid()
        self.props = {"Zoom X": 1.0, "Opacity": 100.0}
        self.calls = []

    def GetUniqueId(self): return self.uid
    def GetName(self): return self.name
    def GetStart(self): return self.start
    def GetEnd(self): return self.end
    def GetDuration(self): return self.end - self.start
    def GetProperty(self, key=None): return dict(self.props) if key is None else self.props.get(key)
    def SetProperty(self, key, value): self.props[key] = value; return True
    def Stabilize(self): self.calls.append("stabilize"); return True
    def SmartReframe(self): self.calls.append("reframe"); return True
    def CreateMagicMask(self, mode): self.calls.append(("mask", mode)); return mode in ("F", "B", "BI")
    def SetCDL(self, cdl): self.calls.append(("cdl", cdl)); return True
    def GetNodeGraph(self): return Graph(self)
    def GetFusionCompCount(self): return 2
    def DeleteMarkersByColor(self, color): return True


class Graph:
    def __init__(self, item): self.item = item
    def SetLUT(self, idx, path): self.item.calls.append(("lut", idx, path)); return True


class Clip:
    def __init__(self, path):
        self.path, self.uid = path, _uid()
        self.metadata, self.transcribed = {}, False

    def GetUniqueId(self): return self.uid
    def GetName(self): return self.path.rsplit("/", 1)[-1]
    def GetClipProperty(self): return {"Type": "Video", "File Path": self.path, "FPS": "24", "Junk": 1}
    def GetMetadata(self): return dict(self.metadata)
    def SetMetadata(self, k, v): self.metadata[k] = v; return True
    def GetMarkers(self): return {}
    def TranscribeAudio(self): self.transcribed = True; return True
    def ClearTranscription(self): self.transcribed = False; return True


class Folder:
    def __init__(self, name):
        self.name, self.clips, self.subs = name, [], []

    def GetName(self): return self.name
    def GetClipList(self): return self.clips
    def GetSubFolderList(self): return self.subs
    def TranscribeAudio(self):
        for c in self.clips: c.transcribed = True
        return True
    def ClearTranscription(self): return True


class Timeline:
    def __init__(self, name):
        self.name, self.uid = name, _uid()
        self.tracks = {"video": [[]], "audio": [[]], "subtitle": []}
        self.markers, self.exports, self.timecode = {}, [], "01:00:00:00"
        self.scene_cuts = False

    def GetName(self): return self.name
    def GetUniqueId(self): return self.uid
    def GetTrackCount(self, t): return len(self.tracks[t])
    def GetItemListInTrack(self, t, i): return self.tracks[t][i - 1]
    def AddMarker(self, frame, color, name, note, dur, data):
        if frame in self.markers: return False
        self.markers[frame] = {"color": color, "name": name, "note": note, "duration": dur, "customData": data}
        return True
    def GetMarkers(self): return self.markers
    def DeleteMarkerAtFrame(self, f): return self.markers.pop(f, None) is not None
    def GetCurrentTimecode(self): return self.timecode
    def SetCurrentTimecode(self, tc): self.timecode = tc; return True
    def DetectSceneCuts(self): self.scene_cuts = True; return True
    def CreateSubtitlesFromAudio(self, settings): self.subtitle_settings = settings; return True
    def Export(self, path, kind, sub=None): self.exports.append((path, kind, sub)); return True
    def GrabStill(self): return object()


class MediaPool:
    def __init__(self, project):
        self.project, self.root = project, Folder("Master")
        self.current = self.root

    def GetRootFolder(self): return self.root
    def GetCurrentFolder(self): return self.current
    def SetCurrentFolder(self, f): self.current = f; return True
    def AddSubFolder(self, parent, name):
        f = Folder(name); parent.subs.append(f); return f
    def ImportMedia(self, paths):
        clips = [Clip(p) for p in paths]; self.current.clips.extend(clips); return clips
    def CreateEmptyTimeline(self, name): return self.project._add_timeline(Timeline(name))
    def CreateTimelineFromClips(self, name, clips):
        tl = self.project._add_timeline(Timeline(name))
        for c in clips: tl.tracks["video"][0].append(Item(c.GetName(), 0, 100))
        return tl
    def AppendToTimeline(self, clips):
        tl = self.project.GetCurrentTimeline()
        out = []
        for c in clips:
            clip = c["mediaPoolItem"] if isinstance(c, dict) else c
            idx = c.get("trackIndex", 1) if isinstance(c, dict) else 1
            item = Item(clip.GetName(), 0, 100)
            tl.tracks["video"][idx - 1].append(item); out.append(item)
        return out
    def ImportTimelineFromFile(self, path, opts): return self.project._add_timeline(Timeline("Imported"))


class Project:
    def __init__(self, name):
        self.name, self.settings, self.timelines, self.current = name, {"timelineFrameRate": "24"}, [], None
        self.pool, self.jobs, self.rendering, self.render = MediaPool(self), [], False, {}

    def GetName(self): return self.name
    def GetMediaPool(self): return self.pool
    def _add_timeline(self, tl):
        self.timelines.append(tl); self.current = tl; return tl
    def GetCurrentTimeline(self): return self.current
    def GetTimelineCount(self): return len(self.timelines)
    def GetTimelineByIndex(self, i): return self.timelines[i - 1]
    def SetCurrentTimeline(self, tl): self.current = tl; return True
    def GetSetting(self, name=""): return dict(self.settings) if name == "" else self.settings.get(name, "")
    def SetSetting(self, k, v): self.settings[k] = v; return True
    def GetRenderFormats(self): return {"MP4": "mp4", "QuickTime": "mov"}
    def GetRenderCodecs(self, fmt): return {"H.265": "H265"} if fmt == "MP4" else {}
    def GetRenderPresetList(self): return ["YouTube 1080p"]
    def LoadRenderPreset(self, n): return n in self.GetRenderPresetList()
    def SetCurrentRenderFormatAndCodec(self, f, c): return f in self.GetRenderFormats()
    def SetRenderSettings(self, s): self.render.update(s); return True
    def AddRenderJob(self):
        jid = _uid(); self.jobs.append({"JobId": jid, "TimelineName": self.current.name}); return jid
    def GetRenderJobList(self): return self.jobs
    def GetRenderJobStatus(self, jid): return {"JobStatus": "Ready", "CompletionPercentage": 0}
    def StartRendering(self, *a): self.rendering = True; return True
    def IsRenderingInProgress(self): return self.rendering
    def StopRendering(self): self.rendering = False
    def DeleteRenderJob(self, jid): self.jobs = [j for j in self.jobs if j["JobId"] != jid]; return True
    def DeleteAllRenderJobs(self): self.jobs = []; return True


class ProjectManager:
    def __init__(self):
        self.projects, self.current = {}, None

    def CreateProject(self, name):
        if name in self.projects: return None
        self.projects[name] = self.current = Project(name); return self.current
    def LoadProject(self, name):
        self.current = self.projects.get(name); return self.current
    def GetCurrentProject(self): return self.current
    def SaveProject(self): return True
    def CloseProject(self, p): self.current = None; return True
    def DeleteProject(self, name): return self.projects.pop(name, None) is not None
    def GetProjectListInCurrentFolder(self): return list(self.projects)
    def GetFolderListInCurrentFolder(self): return []
    def GetCurrentDatabase(self): return {"DbType": "Disk", "DbName": "Local Database"}
    def ExportProject(self, name, path, stills=True): return name in self.projects
    def ImportProject(self, path, name=None): return True


class Storage:
    def GetMountedVolumeList(self): return ["/media"]
    def GetSubFolderList(self, p): return [p + "/a"]
    def GetFileList(self, p): return [p + "/x.mov"]


class Resolve:
    EXPORT_AAF, EXPORT_EDL, EXPORT_NONE, EXPORT_AAF_NEW = "aaf", "edl", "none", "aaf_new"
    SUBTITLE_LANGUAGE, ENGLISH, CHARS_PER_LINE = "subtitle_language", "english", "chars_per_line"

    def __init__(self):
        self.pm, self.page = ProjectManager(), "edit"

    def GetProductName(self): return "DaVinci Resolve Studio"
    def GetVersionString(self): return "20.0.0.1"
    def GetCurrentPage(self): return self.page
    def OpenPage(self, p): self.page = p; return p in ("media", "cut", "edit", "fusion", "color", "fairlight", "deliver")
    def GetProjectManager(self): return self.pm
    def GetMediaStorage(self): return Storage()
    def Fusion(self): return None


_app = None


def scriptapp(name):
    global _app
    if name != "Resolve": return None
    _app = _app or Resolve()
    return _app
