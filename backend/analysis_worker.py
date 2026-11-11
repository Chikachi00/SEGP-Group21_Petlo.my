"""Run one job in one isolated, pausable process with a shared inference model."""
import json
from pathlib import Path
import sys

from .config import Settings
from .pipeline import PipelineRunner, inside


def main():
    request_path = Path(sys.argv[1]).resolve()
    request = json.loads(request_path.read_text(encoding='utf-8'))
    settings = Settings(storage=Path(request['storage']), model=Path(request['model']),
        ffmpeg_dir=request['ffmpeg_dir'], stage_timeout=request['stage_timeout'],
        device=request['device'], cpu_threads=request['cpu_threads'],
        tile_batch_size=request.get('tile_batch_size', 4))
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
