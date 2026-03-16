"""
Voice transcription using faster-whisper (runs entirely on-device, no API key).

Model sizes and approximate RAM usage:
  tiny   (39 MB)  – fast, good enough for clear speech; recommended for Raspberry Pi
  base   (74 MB)  – better accuracy, still fast on modern hardware
  small  (244 MB) – high accuracy; requires ~1GB RAM
  medium (769 MB) – near-perfect accuracy; requires ~3GB RAM

Configure with WHISPER_MODEL env var (default: base).
"""
import asyncio
import os
from pathlib import Path

import config

# Cache the loaded model globally to avoid reloading on every voice message
_model = None
_model_lock = asyncio.Lock()


async def _get_model():
    global _model
    async with _model_lock:
        if _model is None:
            def _load():
                from faster_whisper import WhisperModel
                return WhisperModel(
                    config.WHISPER_MODEL,
                    device="cpu",
                    compute_type="int8",  # int8 is fast and accurate on CPU
                )
            _model = await asyncio.to_thread(_load)
    return _model


async def transcribe(audio_path: str) -> dict:
    """
    Transcribe an audio file to text.

    audio_path: path to an OGG, MP3, WAV, or M4A file
    Returns: {"success": True, "text": "...", "language": "en"}
    """
    try:
        model = await _get_model()

        def _run():
            segments, info = model.transcribe(audio_path, beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text, info.language

        text, language = await asyncio.to_thread(_run)

        # Clean up the temp file after transcription
        try:
            os.remove(audio_path)
        except OSError:
            pass

        return {"success": True, "text": text, "language": language}

    except Exception as e:
        return {"success": False, "error": str(e)}
