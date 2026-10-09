# DaVinci Resolve Studio MCP

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant drive a running
**DaVinci Resolve Studio** through Blackmagic's Python scripting API: projects, media pool,
timelines, markers, color, Studio AI tools, and the render queue.

> **Studio only.** The free edition allows scripting only from inside Resolve. External
> scripting, which this server uses, needs Studio.

## Setup

1. Install DaVinci Resolve Studio (18.5+ recommended; 19/20 for the newest AI tools).
2. In Resolve: **Preferences > System > General > External scripting using > Local**.
3. Keep Resolve running, then install and register the server:

```bash
pip install -e .            # or: pipx install .
```

Claude Desktop / Claude Code config:

```json
{
  "mcpServers": {
    "davinci-resolve": { "command": "davinci-resolve-studio-mcp" }
  }
}
```

Claude Code: `claude mcp add davinci-resolve -- davinci-resolve-studio-mcp`

The scripting module is found at the standard install paths. If Resolve is installed
elsewhere, set `RESOLVE_SCRIPT_API` to its `Developer/Scripting` folder
(and `RESOLVE_SCRIPT_LIB` to `fusionscript`).

## Tools

| Area | Tools |
|---|---|
| Connection | `resolve_status`, `open_page` |
| Projects | `list_projects`, `open_project`, `create_project`, `save_project`, `close_project`, `delete_project`*, `export_project`, `import_project`, `get_project_settings`, `set_project_settings` |
| Media | `browse_media_storage`, `import_media`, `list_media`, `create_bin`, `get_clip_properties`, `set_clip_metadata`, `transcribe_audio` (Studio) |
| Timelines | `list_timelines`, `set_current_timeline`, `create_timeline`, `append_to_timeline`, `append_subclip_to_timeline`, `import_timeline`, `export_timeline`, `list_timeline_items`, `add_marker`, `list_markers`, `delete_marker`, `get_playhead`, `set_playhead` |
| Studio AI | `detect_scene_cuts`, `create_subtitles_from_audio`, `stabilize_item`, `smart_reframe_item`, `create_magic_mask`, `transcribe_audio` |
| Items & color | `get_item_properties`, `set_item_properties`, `set_cdl`, `apply_lut`, `grab_still` |
| Deliver | `get_render_options`, `configure_render`, `add_render_job`, `list_render_jobs`, `start_rendering`, `render_progress`, `stop_rendering`, `delete_render_jobs`* |
| Escape hatch | `resolve_call`: call any scripting API method on the resolve / project / media pool / timeline / `clip:<id>` / `item:<id>` objects |

\* Destructive: requires `confirm=true`. `resolve_call` applies the same rule to
`Delete*`, `Remove*` and `Clear*` methods.

Clips and timeline items are addressed by unique id, returned by `list_media`,
`list_timeline_items` and the create tools.

## Development

```bash
pip install -e ".[test]"
pytest
```

Tests run against an in-memory fake of `DaVinciResolveScript` (`tests/fake_resolve/`),
including an end-to-end stdio test. They do not need Resolve. The fake mirrors the
documented API, so it has **not** been verified against a real Resolve install: method
availability varies by Resolve version (see the `README.txt` shipped in Resolve's
`Developer/Scripting` folder).
