from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path


def test_video_context_parser_builds_markdown_and_keyframes(monkeypatch, tmp_path):
    from app.adapters.video_context_parser import (
        VideoContextParserAdapter,
        VideoContextParserConfig,
    )

    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fake-video")

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=json.dumps(
                    {
                        "format": {
                            "duration": "4.2",
                            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
                            "size": "12345",
                        },
                        "streams": [
                            {
                                "codec_type": "video",
                                "codec_name": "h264",
                                "width": 1280,
                                "height": 720,
                                "avg_frame_rate": "30/1",
                            },
                            {
                                "codec_type": "audio",
                                "codec_name": "aac",
                            },
                        ],
                    }
                ),
                stderr="",
            )
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"jpeg-bytes")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    parser = VideoContextParserAdapter(
        VideoContextParserConfig(
            max_keyframes=2,
            enable_markitdown_transcript=False,
        )
    )
    parsed = asyncio.run(parser.parse(str(source), options={"source_name": "sample.mp4"}))

    assert parsed.metadata["parser"] == "video_context"
    assert parsed.metadata["media_kind"] == "video"
    assert parsed.metadata["duration_seconds"] == 4.2
    assert len(parsed.images) == 2
    assert parsed.images[0]["media_type"] == "image/jpeg"
    assert "Video metadata" in parsed.markdown
    assert "attached as vision image" in parsed.markdown
