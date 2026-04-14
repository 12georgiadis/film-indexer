"""
Transcoding helpers : BRAW/MOV/MP4 → proxy 720p H264 NVENC.

Stratégie :
- ffmpeg + h264_nvenc (RTX 5090 9e gen NVENC)
- 720p @ 2 Mbps VBR
- preset p4 -tune hq pour qualité Gemini-friendly
- Pour BRAW : on tente direct via ffmpeg (échouera probablement),
  fallback DaVinci Resolve scripting headless.

Note : DaVinci Resolve installé sur Nomad, on l'utilise via DaVinciResolveScript
en headless mode pour le decode BRAW.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


FFMPEG_BIN = "ffmpeg"


def is_braw(path: Path) -> bool:
    return path.suffix.lower() in {".braw"}


def probe_duration(path: Path) -> Optional[float]:
    """Get duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def transcode_proxy_ffmpeg_nvenc(
    src: Path,
    dst: Path,
    target_height: int = 720,
    bitrate: str = "2M",
    preset: str = "p4",
) -> bool:
    """Transcode any video file to MP4 720p H264 NVENC.

    Returns True on success, False on failure.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        FFMPEG_BIN, "-y",
        "-hwaccel", "cuda",
        "-hwaccel_output_format", "cuda",
        "-i", str(src),
        "-vf", f"scale_cuda={int(target_height * 16 / 9)}:{target_height}:format=yuv420p",
        "-c:v", "h264_nvenc",
        "-preset", preset,
        "-tune", "hq",
        "-rc", "vbr",
        "-cq", "23",
        "-b:v", bitrate,
        "-maxrate", "3M",
        "-bufsize", "5M",
        "-spatial-aq", "1",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ac", "2",
        "-movflags", "+faststart",
        str(dst),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            print(f"[transcode] ffmpeg failed: {result.stderr[-1000:]}")
            return False
        return dst.exists() and dst.stat().st_size > 1024
    except subprocess.TimeoutExpired:
        print("[transcode] ffmpeg timeout")
        return False


def transcode_proxy_resolve_braw(src: Path, dst: Path, target_height: int = 720) -> bool:
    """Transcode BRAW via DaVinci Resolve scripting headless.

    Requires DaVinci Resolve installed on Nomad (Free or Studio).
    Uses Resolve's BRAW SDK natively.
    """
    # Resolve scripting requires Resolve to be running OR headless mode
    # For PoC: we'll call Resolve via its CLI scripting interface
    # If this is too complex, fallback: pre-transcode all BRAW manually before pipeline
    raise NotImplementedError(
        "BRAW transcoding via Resolve headless not implemented in PoC. "
        "Workaround : pre-transcode BRAW to ProRes/H264 manually or via DaVinci batch."
    )


def transcode_proxy(src: Path, dst: Path) -> bool:
    """Main entry point. Routes to ffmpeg or Resolve depending on format."""
    if is_braw(src):
        return transcode_proxy_resolve_braw(src, dst)
    return transcode_proxy_ffmpeg_nvenc(src, dst)


def find_test_clip(search_paths: list[Path]) -> Optional[Path]:
    """Find a non-BRAW video clip for PoC testing."""
    extensions = {".mov", ".mp4", ".mxf", ".m4v"}
    for root in search_paths:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() in extensions and path.stat().st_size > 1_000_000:
                return path
    return None
