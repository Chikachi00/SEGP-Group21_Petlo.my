"""Encode source-time browser previews, preferring available NVIDIA hardware."""
from pathlib import Path
import subprocess


PREVIEW_FILTER = 'setpts=PTS-STARTPTS,scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2'


def encode_preview(source, target, tools, timeout, device='auto'):
    """Return the encoder used; CPU remains available when NVENC cannot encode.

    Decoder timestamps and frame count are preserved with passthrough timing.
    A stage timeout propagates without starting another full encoding attempt.
    """
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError('Preview output must differ from the source video')
    target.parent.mkdir(parents=True, exist_ok=True)
    common = [str(tools.ffmpeg), '-nostdin', '-y', '-v', 'error', '-i', str(source),
        '-map', '0:v:0', '-vf', PREVIEW_FILTER, '-fps_mode', 'passthrough', '-an']
    output = ['-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)]
    if device != 'cpu':
        options = ['-c:v', 'h264_nvenc', '-preset', 'p4', '-rc', 'vbr', '-cq', '24', '-b:v', '0']
        if str(device).isdecimal():
            options.extend(('-gpu', str(device)))
        try:
            subprocess.run(common + options + output, check=True, timeout=timeout)
            return 'h264_nvenc'
        except subprocess.CalledProcessError:
            # Unsupported builds, drivers or hardware must not prevent playback.
            # The CPU retry overwrites any incomplete NVENC output using -y.
            pass
    # Reordered B-frames can shorten MP4 duration on sparse VFR inputs even
    # though all frame PTS survive. Keep source-time playback complete at the end.
    subprocess.run(common + ['-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-crf', '24', '-bf', '0'] + output,
        check=True, timeout=timeout)
    return 'libx264'
