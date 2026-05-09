"""VideoContextParserAdapter - lightweight video-to-context conversion.

The chat upload path needs a dependable first pass for local video files even
when heavy ASR/scene-detection stacks are not installed. This adapter uses the
production-standard FFmpeg toolchain for metadata + representative keyframes,
and opportunistically asks MarkItDown for an audio transcript when audio extras
are present.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.adapters.markitdown_parser import MarkItDownConfig, MarkItDownParserAdapter
from app.ports.document_parser import DocumentParserPort, ParsedDocument

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoContextParserConfig:
    """Configuration for bounded local video parsing."""

    max_keyframes: int = 4
    frame_width: int = 640
    frame_detail: str = "low"
    probe_timeout_seconds: float = 12.0
    frame_timeout_seconds: float = 20.0
    transcript_max_chars: int = 12_000
    enable_markitdown_transcript: bool = True


class VideoContextParserAdapter(DocumentParserPort):
    """Convert local video files into markdown + sampled keyframes."""

    _SUPPORTED_FORMATS = ["mp4", "m4v", "mov", "webm", "mkv"]

    def __init__(
        self,
        config: VideoContextParserConfig | None = None,
        *,
        transcript_parser: DocumentParserPort | None = None,
    ) -> None:
        self._config = config or VideoContextParserConfig()
        self._transcript_parser = transcript_parser

    @property
    def is_available(self) -> bool:
        return bool(shutil.which("ffprobe") and shutil.which("ffmpeg"))

    async def parse(self, file_path: str, options: dict | None = None) -> ParsedDocument:
        """Convert a local video file to bounded markdown and keyframe images."""
        ext = Path(file_path).suffix.lower().lstrip(".")
        if ext not in self._SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported video file extension: .{ext}")
        if not self.is_available:
            raise NotImplementedError("Video parsing requires ffmpeg and ffprobe on PATH.")

        opts = options or {}
        source_name = str(opts.get("source_name") or Path(file_path).name)

        def _parse() -> ParsedDocument:
            probe = self._probe(file_path)
            metadata = self._summarize_probe(probe)
            keyframes = self._extract_keyframes(
                file_path,
                duration_seconds=metadata.get("duration_seconds"),
            )
            transcript_markdown, transcript_status = self._try_markitdown_transcript(file_path)
            markdown = self._render_markdown(
                source_name=source_name,
                extension=ext,
                metadata=metadata,
                keyframes=keyframes,
                transcript_markdown=transcript_markdown,
                transcript_status=transcript_status,
            )

            return ParsedDocument(
                markdown=markdown,
                page_count=1,
                metadata={
                    "title": source_name,
                    "parser": "video_context",
                    "media_kind": "video",
                    "source_extension": ext,
                    "duration_seconds": metadata.get("duration_seconds"),
                    "width": metadata.get("width"),
                    "height": metadata.get("height"),
                    "has_audio": metadata.get("has_audio"),
                    "transcript_status": transcript_status,
                    "extracted_image_count": len(keyframes),
                },
                section_map={
                    "Video metadata": [1],
                    "Sampled keyframes": [1],
                    "Audio transcript": [1],
                },
                images=keyframes,
            )

        return await asyncio.to_thread(_parse)

    def supported_formats(self) -> list[str]:
        return list(self._SUPPORTED_FORMATS)

    def _probe(self, file_path: str) -> dict[str, Any]:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=self._config.probe_timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffprobe failed")
        try:
            parsed = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RuntimeError("ffprobe returned invalid JSON") from exc
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _parse_float(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed) or parsed < 0:
            return None
        return parsed

    @classmethod
    def _summarize_probe(cls, probe: dict[str, Any]) -> dict[str, Any]:
        streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
        fmt = probe.get("format") if isinstance(probe.get("format"), dict) else {}
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        duration = cls._parse_float(fmt.get("duration")) or cls._parse_float(video_stream.get("duration"))
        fps = cls._frame_rate(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
        size_bytes = None
        try:
            size_bytes = int(fmt.get("size")) if fmt.get("size") is not None else None
        except (TypeError, ValueError):
            size_bytes = None

        return {
            "duration_seconds": duration,
            "format_name": fmt.get("format_name"),
            "size_bytes": size_bytes,
            "bit_rate": fmt.get("bit_rate"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": fps,
            "video_codec": video_stream.get("codec_name"),
            "audio_codecs": [str(s.get("codec_name") or "").strip() for s in audio_streams if s.get("codec_name")],
            "has_audio": bool(audio_streams),
        }

    @staticmethod
    def _frame_rate(raw_rate: Any) -> float | None:
        if not raw_rate:
            return None
        text = str(raw_rate)
        if "/" in text:
            num, den = text.split("/", 1)
            try:
                denominator = float(den)
                return round(float(num) / denominator, 3) if denominator else None
            except ValueError:
                return None
        try:
            return round(float(text), 3)
        except ValueError:
            return None

    def _sample_timestamps(self, duration_seconds: float | None) -> list[float]:
        if not duration_seconds or duration_seconds <= 0:
            return [0.0]
        if duration_seconds < 2.0:
            return [round(max(0.0, duration_seconds / 2), 2)]

        ratios = [0.12, 0.35, 0.62, 0.88][: max(1, self._config.max_keyframes)]
        timestamps: list[float] = []
        for ratio in ratios:
            ts = min(max(duration_seconds * ratio, 0.1), max(duration_seconds - 0.1, 0.1))
            rounded = round(ts, 2)
            if not timestamps or abs(rounded - timestamps[-1]) >= 0.35:
                timestamps.append(rounded)
        return timestamps[: self._config.max_keyframes]

    def _extract_keyframes(
        self,
        file_path: str,
        *,
        duration_seconds: float | None,
    ) -> list[dict[str, Any]]:
        keyframes: list[dict[str, Any]] = []
        timestamps = self._sample_timestamps(duration_seconds)
        with tempfile.TemporaryDirectory(prefix="wiii-video-frames-") as tmp_dir:
            for index, timestamp in enumerate(timestamps, start=1):
                output_path = Path(tmp_dir) / f"frame-{index}.jpg"
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        f"{timestamp:.2f}",
                        "-i",
                        file_path,
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={self._config.frame_width}:-2:force_original_aspect_ratio=decrease",
                        "-q:v",
                        "3",
                        str(output_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self._config.frame_timeout_seconds,
                    check=False,
                )
                if result.returncode != 0 or not output_path.exists():
                    logger.debug(
                        "Video keyframe extraction skipped at %.2fs: %s",
                        timestamp,
                        result.stderr.strip()[:300],
                    )
                    continue
                data = base64.b64encode(output_path.read_bytes()).decode("ascii")
                keyframes.append(
                    {
                        "id": f"video-frame-{index}",
                        "label": f"Khung hình {index} @ {self._format_timestamp(timestamp)}",
                        "timestamp_seconds": timestamp,
                        "media_type": "image/jpeg",
                        "data": data,
                        "detail": self._config.frame_detail,
                        "source": "video_keyframe",
                    }
                )
        return keyframes

    def _try_markitdown_transcript(self, file_path: str) -> tuple[str, str]:
        if not self._config.enable_markitdown_transcript:
            return "", "disabled"
        parser = self._transcript_parser
        if parser is None:
            parser = MarkItDownParserAdapter(
                MarkItDownConfig(enable_plugins=False, local_only=True)
            )
        if not getattr(parser, "is_available", False):
            return "", "markitdown_unavailable"
        if "mp4" not in {fmt.lower() for fmt in parser.supported_formats()}:
            return "", "markitdown_video_not_supported"

        try:
            parsed = asyncio.run(parser.parse(file_path, options={"source": "video_audio"}))
        except Exception as exc:  # noqa: BLE001
            logger.debug("MarkItDown video transcript unavailable: %s", exc)
            return "", "transcript_unavailable"

        transcript = (parsed.markdown or "").strip()
        if not transcript:
            return "", "empty"
        if len(transcript) > self._config.transcript_max_chars:
            transcript = transcript[: self._config.transcript_max_chars].rstrip()
            return transcript, "truncated"
        return transcript, "ok"

    @classmethod
    def _format_timestamp(cls, seconds: float | None) -> str:
        if seconds is None:
            return "?"
        total = max(0, int(round(seconds)))
        minute, sec = divmod(total, 60)
        hour, minute = divmod(minute, 60)
        if hour:
            return f"{hour:d}:{minute:02d}:{sec:02d}"
        return f"{minute:d}:{sec:02d}"

    @classmethod
    def _render_markdown(
        cls,
        *,
        source_name: str,
        extension: str,
        metadata: dict[str, Any],
        keyframes: list[dict[str, Any]],
        transcript_markdown: str,
        transcript_status: str,
    ) -> str:
        duration = metadata.get("duration_seconds")
        resolution = (
            f"{metadata.get('width')}x{metadata.get('height')}"
            if metadata.get("width") and metadata.get("height")
            else "unknown"
        )
        lines = [
            f"# Video upload: {source_name}",
            "",
            "## Video metadata",
            f"- Type: .{extension}",
            f"- Duration: {cls._format_timestamp(duration)} ({duration:.2f}s)" if isinstance(duration, float) else "- Duration: unknown",
            f"- Resolution: {resolution}",
            f"- Video codec: {metadata.get('video_codec') or 'unknown'}",
            f"- FPS: {metadata.get('fps') or 'unknown'}",
            f"- Has audio: {bool(metadata.get('has_audio'))}",
        ]
        audio_codecs = metadata.get("audio_codecs")
        if audio_codecs:
            lines.append(f"- Audio codec(s): {', '.join(audio_codecs)}")

        lines.extend(["", "## Sampled keyframes"])
        if keyframes:
            lines.append(
                "Representative frames were extracted and attached to the same chat turn "
                "as vision inputs. Use them as visual evidence, not as the whole video."
            )
            for frame in keyframes:
                lines.append(
                    f"- {frame.get('label')}: attached as vision image `{frame.get('id')}`"
                )
        else:
            lines.append("- No keyframes could be extracted.")

        lines.extend(["", "## Audio transcript"])
        if transcript_markdown:
            lines.append(transcript_markdown)
        else:
            lines.append(
                f"[Transcript unavailable: {transcript_status}. "
                "This turn still includes video metadata and sampled keyframes when available.]"
            )

        return "\n".join(lines).strip()
