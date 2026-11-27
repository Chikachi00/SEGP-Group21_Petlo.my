"""Audio-based constant clock-offset estimation (GCC-PHAT) for two-view camera sync.

Estimates ``side_time - front_time`` from the two cameras' audio tracks without
relying on detected visual events. Verifies both global peak prominence (SNR
and secondary-peak ratio) and first-half / second-half offset agreement so that
edited, spliced, or uncorrelated recordings are rejected as unreliable rather
than silently forced onto a single constant offset.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import subprocess

import numpy as np


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class AudioSyncSettings:
    sample_rate: int = 8000
    max_offset_sec: float = 15.0
    min_snr: float = 5.0
    min_peak_ratio: float = 1.4
    max_half_diff_sec: float = 0.10
    min_duration_sec: float = 4.0
    exclusion_radius_sec: float = 0.5

    def __post_init__(self):
        if type(self.sample_rate) is not int or self.sample_rate < 1000:
            raise ValueError("sample_rate must be an integer >= 1000")
        for name in ("max_offset_sec", "min_snr", "min_peak_ratio", "max_half_diff_sec",
                     "min_duration_sec", "exclusion_radius_sec"):
            value = getattr(self, name)
            if not _finite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")


def gcc_phat_offset(front_signal: np.ndarray, side_signal: np.ndarray,
                    sample_rate: int = 8000, max_offset_sec: float = 15.0,
                    exclusion_radius_sec: float = 0.5) -> tuple[float, float, float]:
    """Return ``(offset_sec, snr, peak_ratio)`` where ``side_t ≈ front_t + offset_sec``.

    Positive ``offset_sec`` means an event occurs later on the side clock than
    on the front clock (i.e. side started recording earlier).
    """
    a_f = np.asarray(front_signal, dtype=np.float32).reshape(-1)
    a_s = np.asarray(side_signal, dtype=np.float32).reshape(-1)
    if a_f.size < 2 or a_s.size < 2:
        raise ValueError("Audio signals must contain at least 2 samples")
    a_f = a_f - float(np.mean(a_f))
    a_s = a_s - float(np.mean(a_s))
    if float(np.max(np.abs(a_f))) < 1e-8 or float(np.max(np.abs(a_s))) < 1e-8:
        return 0.0, 0.0, 0.0
    n = 1 << int(math.ceil(math.log2(a_f.size + a_s.size)))
    f_spec = np.fft.rfft(a_f, n)
    s_spec = np.fft.rfft(a_s, n)
    cross = s_spec * np.conj(f_spec)
    mag = np.abs(cross)
    cross = np.where(mag > 1e-10, cross / (mag + 1e-10), 0.0)
    cc = np.fft.irfft(cross, n)
    max_lag = min(int(round(max_offset_sec * sample_rate)), min(a_f.size, a_s.size) - 1)
    if max_lag < 1:
        return 0.0, 0.0, 0.0
    lags = np.concatenate([cc[-max_lag:], cc[:max_lag + 1]])
    peak_idx = int(np.argmax(lags))
    peak_val = float(lags[peak_idx])
    std = float(np.std(lags))
    snr = peak_val / std if std > 1e-12 else 0.0
    radius = int(round(exclusion_radius_sec * sample_rate))
    mask = np.ones(lags.size, dtype=bool)
    mask[max(0, peak_idx - radius):min(lags.size, peak_idx + radius + 1)] = False
    second = float(np.max(lags[mask])) if mask.any() else 0.0
    peak_ratio = peak_val / second if second > 1e-12 else (float("inf") if peak_val > 0 else 0.0)
    offset_sec = float(peak_idx - max_lag) / float(sample_rate)
    return offset_sec, snr, peak_ratio


def estimate_audio_offset_signals(front_signal: np.ndarray, side_signal: np.ndarray,
                                  settings: AudioSyncSettings | None = None) -> dict:
    """Estimate constant offset with global prominence and half-split consistency checks."""
    cfg = settings or AudioSyncSettings()
    a_f = np.asarray(front_signal, dtype=np.float32).reshape(-1)
    a_s = np.asarray(side_signal, dtype=np.float32).reshape(-1)
    min_samples = int(round(cfg.min_duration_sec * cfg.sample_rate))
    result = {
        "status": "unreliable",
        "method": "audio_gcc_phat",
        "offset_sec": None,
        "snr": None,
        "peak_ratio": None,
        "half_offsets_sec": None,
        "half_diff_sec": None,
        "warning": None,
        "reason": None,
        "settings": asdict(cfg),
    }
    if a_f.size < min_samples or a_s.size < min_samples:
        result["reason"] = f"Audio track shorter than {cfg.min_duration_sec:.1f}s minimum."
        return result

    offset, snr, peak_ratio = gcc_phat_offset(
        a_f, a_s, cfg.sample_rate, cfg.max_offset_sec, cfg.exclusion_radius_sec
    )
    result["snr"] = round(float(snr), 3)
    result["peak_ratio"] = round(float(peak_ratio), 3) if math.isfinite(peak_ratio) else 999.0

    if snr < cfg.min_snr:
        result["reason"] = f"Audio correlation SNR {snr:.2f} below minimum {cfg.min_snr:.2f}."
        return result
    if peak_ratio < cfg.min_peak_ratio:
        result["reason"] = f"Audio peak-to-secondary ratio {peak_ratio:.2f} below minimum {cfg.min_peak_ratio:.2f}."
        return result

    # Half-split consistency check: detect spliced/edited recordings or severe clock drift.
    mid_f, mid_s = a_f.size // 2, a_s.size // 2
    lag1, snr1, _ = gcc_phat_offset(
        a_f[:mid_f], a_s[:mid_s], cfg.sample_rate, cfg.max_offset_sec, cfg.exclusion_radius_sec
    )
    lag2_local, snr2, _ = gcc_phat_offset(
        a_f[mid_f:], a_s[mid_s:], cfg.sample_rate, cfg.max_offset_sec, cfg.exclusion_radius_sec
    )
    lag2 = lag2_local + float(mid_s - mid_f) / float(cfg.sample_rate)
    half_diff = abs(lag1 - lag2)
    result["half_offsets_sec"] = [round(lag1, 4), round(lag2, 4)]
    result["half_diff_sec"] = round(half_diff, 4)

    if half_diff > cfg.max_half_diff_sec:
        result["warning"] = "possible_splice_or_frame_drop"
        result["reason"] = (
            f"First-half ({lag1:+.3f}s) and second-half ({lag2:+.3f}s) audio offsets "
            f"disagree by {half_diff:.3f}s (> {cfg.max_half_diff_sec:.3f}s); "
            "possible edit, splice, or clock drift."
        )
        return result
    if min(snr1, snr2) < cfg.min_snr * 0.6:
        result["reason"] = (
            f"Audio correlation weak in one half (SNRs {snr1:.2f}, {snr2:.2f}); "
            "refusing to claim verified audio sync."
        )
        return result

    result["status"] = "verified"
    result["offset_sec"] = round(offset, 4)
    return result


def extract_mono_audio(video_path: Path, ffmpeg_exe: str, sample_rate: int = 8000,
                       timeout_sec: float = 60.0) -> np.ndarray:
    """Decode the first audio stream of ``video_path`` to mono float32 PCM."""
    command = [
        ffmpeg_exe, "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-map", "0:a:0", "-ac", "1", "-ar", str(sample_rate),
        "-f", "f32le", "-",
    ]
    completed = subprocess.run(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec
    )
    if completed.returncode != 0 or not completed.stdout:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(detail or "No readable audio stream")
    return np.frombuffer(completed.stdout, dtype=np.float32)


def estimate_audio_offset(front_video: Path, side_video: Path, *,
                          ffmpeg_dir: Path | str | None = None,
                          settings: AudioSyncSettings | None = None) -> dict:
    """Safely estimate constant offset between two video files using their audio tracks."""
    cfg = settings or AudioSyncSettings()
    front_path, side_path = Path(front_video), Path(side_video)
    if not front_path.is_file() or not side_path.is_file():
        return {
            "status": "unreliable", "method": "audio_gcc_phat", "offset_sec": None,
            "snr": None, "peak_ratio": None, "half_offsets_sec": None, "half_diff_sec": None,
            "reason": "Source video files are not accessible for audio sync.",
            "settings": asdict(cfg),
        }
    try:
        if __package__:
            from .video_tools.media import Toolchain
        else:
            from video_tools.media import Toolchain
        tools = Toolchain.discover(ffmpeg_dir)
        a_f = extract_mono_audio(front_path, tools.ffmpeg, cfg.sample_rate)
        a_s = extract_mono_audio(side_path, tools.ffmpeg, cfg.sample_rate)
    except Exception as exc:
        return {
            "status": "unreliable", "method": "audio_gcc_phat", "offset_sec": None,
            "snr": None, "peak_ratio": None, "half_offsets_sec": None, "half_diff_sec": None,
            "reason": f"Audio extraction unavailable: {exc}",
            "settings": asdict(cfg),
        }
    return estimate_audio_offset_signals(a_f, a_s, cfg)
