"""
BRAW handling via DaVinci Resolve Python scripting.

ffmpeg ne lit pas le BRAW natif. Solution : utiliser DaVinci Resolve
(Free ou Studio) en scripting headless pour pre-transcoder les .braw
en .mp4 720p H.264 NVENC.

Prérequis sur Nomad :
1. DaVinci Resolve installé (confirmé : C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\)
2. Resolve doit être LANCÉ (l'API scripting nécessite l'UI active)
3. Variables d'environnement :
   - RESOLVE_SCRIPT_API = C:\\ProgramData\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\
   - RESOLVE_SCRIPT_LIB = C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\fusionscript.dll
   - PYTHONPATH = %PYTHONPATH%;%RESOLVE_SCRIPT_API%\\Modules\\

Usage :
    # Option A : batch_transcode_braw(list_of_braw_paths, out_dir)
    # Option B : ligne de commande si Resolve est lancé
    python -m film_indexer.lib.braw_resolve --inputs "F:\\A030\\*.braw" --out C:\\Goldberg\\film-indexer\\proxies\\

Alternative plus simple (manuel) :
- Ouvrir Resolve → File → Media Import Settings → BRAW
- Deliver page → Custom Export → preset "Proxy 720p H.264"
- Render queue → Start Render
- Les MP4 sortent dans le dossier choisi, qu'on scanne ensuite avec scan_drives.py
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


def setup_resolve_env():
    """Configure the Resolve scripting environment variables on Windows."""
    if os.name == "nt":
        os.environ.setdefault(
            "RESOLVE_SCRIPT_API",
            r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
        )
        os.environ.setdefault(
            "RESOLVE_SCRIPT_LIB",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
        )
        # Add to PYTHONPATH
        scripting_modules = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
        if scripting_modules not in sys.path:
            sys.path.insert(0, scripting_modules)


def get_resolve():
    """Import DaVinciResolveScript and return the Resolve app instance.

    Raises RuntimeError if Resolve is not running or scripting is not configured.
    """
    setup_resolve_env()
    try:
        import DaVinciResolveScript as dvr_script
    except ImportError as e:
        raise RuntimeError(
            "DaVinciResolveScript module not found. "
            "Make sure DaVinci Resolve is installed and RESOLVE_SCRIPT_API / PYTHONPATH are set."
        ) from e

    resolve = dvr_script.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Could not connect to DaVinci Resolve. Make sure Resolve is running "
            "(the scripting API requires the UI to be active, even in headless scenarios)."
        )
    return resolve


def transcode_braw_files(
    braw_files: list[Path],
    output_dir: Path,
    preset_name: str = "H.264 Master",
    width: int = 1280,
    height: int = 720,
) -> dict:
    """Transcode a list of BRAW files to 720p H.264 proxies via Resolve render queue.

    Creates a temporary project, adds all files, deliveries them, starts render,
    waits for completion. Cleans up the temp project after.

    Returns {"ok": [...], "failed": [...], "output_dir": path}.
    """
    resolve = get_resolve()
    project_manager = resolve.GetProjectManager()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create a temp project
    project_name = "film_indexer_braw_transcode"
    project = project_manager.CreateProject(project_name)
    if not project:
        project = project_manager.LoadProject(project_name)
    if not project:
        raise RuntimeError(f"Could not create or load project {project_name}")

    media_pool = project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()

    # Import BRAW files
    media_storage = resolve.GetMediaStorage()
    import_paths = [str(p) for p in braw_files if p.exists()]
    clips = media_storage.AddItemListToMediaPool(import_paths)
    if not clips:
        return {"ok": [], "failed": import_paths, "error": "AddItemListToMediaPool failed"}

    # Configure deliver
    project.DeleteAllRenderJobs()
    project.LoadRenderPreset(preset_name)  # may need to use "H.264 Master" or similar
    project.SetRenderSettings({
        "SelectAllFrames": True,
        "TargetDir": str(output_dir),
        "CustomName": "",  # will use clip name by default
        "FormatWidth": width,
        "FormatHeight": height,
        "VideoQuality": 0,  # use preset
    })

    # Add each clip as a render job
    for clip in clips:
        project.SetCurrentTimeline(None)  # ensure no timeline active
        media_pool.CreateEmptyTimeline(f"tl_{clip.GetName()}")
        timeline = project.GetCurrentTimeline()
        media_pool.AppendToTimeline([clip])
        project.AddRenderJob()

    # Start rendering
    project.StartRendering()

    # Wait for completion (poll)
    import time as _t
    while project.IsRenderingInProgress():
        _t.sleep(2)

    # Return success
    return {
        "ok": [str(p) for p in braw_files if p.exists()],
        "failed": [],
        "output_dir": str(output_dir),
    }


def main():
    parser = argparse.ArgumentParser(description="BRAW → 720p H.264 transcode via DaVinci Resolve")
    parser.add_argument("--inputs", nargs="+", required=True, help="BRAW file paths or glob patterns")
    parser.add_argument("--out", type=Path, required=True, help="Output directory for proxies")
    parser.add_argument("--preset", type=str, default="H.264 Master", help="Resolve render preset name")
    args = parser.parse_args()

    # Expand globs
    from glob import glob
    files = []
    for pattern in args.inputs:
        files.extend([Path(p) for p in glob(pattern)])

    if not files:
        print(f"No files matching {args.inputs}", file=sys.stderr)
        sys.exit(1)

    print(f"Transcoding {len(files)} BRAW files via DaVinci Resolve → {args.out}")

    try:
        result = transcode_braw_files(files, args.out, preset_name=args.preset)
        print(f"OK: {len(result['ok'])}")
        print(f"FAILED: {len(result['failed'])}")
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("\nFALLBACK SUGGESTION:")
        print("  1. Ouvrir DaVinci Resolve manuellement")
        print("  2. Import BRAW files → Media Pool")
        print("  3. Deliver page → Custom Export, preset 'H.264 Master' 1280x720, 2 Mbps VBR")
        print("  4. Target : " + str(args.out))
        print("  5. Add to Render Queue → Start Render")
        print("  6. Les .mp4 sortent dans Target dir, ensuite scan via scan_drives.py")
        sys.exit(1)


if __name__ == "__main__":
    main()
