"""Run one job in one isolated, pausable process with a shared inference model."""
import json
from pathlib import Path
import sys

from .config import Settings
from .pipeline import PipelineRunner, inside


def main():
    request_path = Path(sys.argv[1]).resolve()
    request = json.loads(request_path.read_text(encoding='utf-8'))
    raw_band = request.get('disc_band')
    disc_band = tuple(raw_band) if isinstance(raw_band, (list, tuple)) and len(raw_band) == 2 else None
    settings = Settings(storage=Path(request['storage']), model=Path(request['model']),
        ffmpeg_dir=request['ffmpeg_dir'], stage_timeout=request['stage_timeout'],
        device=request['device'], cpu_threads=request['cpu_threads'],
        tile_batch_size=request.get('tile_batch_size', 4),
        disc_band=disc_band, band_cols=request.get('band_cols', 4),
        motion_disc_confidence=request.get('motion_disc_confidence'))
    settings.validate()
    root = inside(settings.storage, f'jobs/{request["job_id"]}')
    if request_path.parent != root:
        raise ValueError('Worker request must be inside its job directory')

    def update(stage):
        with (root / 'progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'stage': stage}) + '\n')

    result = PipelineRunner(settings).run_direct(request['job_id'], request['mode'], request['videos'], update)
    (root / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    main()
