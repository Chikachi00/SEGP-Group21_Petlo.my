from dataclasses import dataclass, field
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / 'backend/.env', override=False)


def _parse_band(raw: str | None) -> tuple[float, float] | None:
    if raw is None or raw.strip().lower() in ('', 'none', 'off', 'false'):
        return None
    parts = [p.strip() for p in raw.split(',')]
    if len(parts) != 2:
        raise ValueError('PETLO_DISC_BAND must be "y0,y1" (e.g. 0.15,0.85) or empty')
    return (float(parts[0]), float(parts[1]))


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None or raw.strip().lower() in ('', 'none', 'off', 'false'):
        return None
    return float(raw.strip())


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv('PETLO_DATABASE_URL', f'sqlite:///{(ROOT / "backend/data/petlo.sqlite3").as_posix()}'))
    storage: Path = field(default_factory=lambda: Path(os.getenv('PETLO_STORAGE_DIR', str(ROOT / 'outputs/backend-storage'))).resolve())
    local_user_id: int = field(default_factory=lambda: int(os.getenv('PETLO_LOCAL_USER_ID', '1')))
    seed_demo: bool = field(default_factory=lambda: os.getenv('PETLO_SEED_DEMO', 'true').lower() == 'true')
    origins: tuple[str, ...] = field(default_factory=lambda: tuple(os.getenv('PETLO_ALLOWED_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(',')))
    max_upload_bytes: int = field(default_factory=lambda: int(os.getenv('PETLO_MAX_UPLOAD_MB', '1024')) * 1024 * 1024)
    stage_timeout: int = field(default_factory=lambda: int(os.getenv('PETLO_STAGE_TIMEOUT_SEC', '7200')))
    model: Path = field(default_factory=lambda: Path(os.getenv('PETLO_MODEL_PATH', str(ROOT / 'yolo11n.pt'))).resolve())
    ffmpeg_dir: str | None = field(default_factory=lambda: os.getenv('PETLO_FFMPEG_DIR') or None)
    device: str = field(default_factory=lambda: os.getenv('PETLO_DEVICE', 'auto'))
    cpu_threads: int = field(default_factory=lambda: int(os.getenv('PETLO_CPU_THREADS', '8')))
    tile_batch_size: int = field(default_factory=lambda: int(os.getenv('PETLO_TILE_BATCH_SIZE', '4')))
    disc_band: tuple[float, float] | None = field(default_factory=lambda: _parse_band(os.getenv('PETLO_DISC_BAND', '0.15,0.85')))
    band_cols: int = field(default_factory=lambda: int(os.getenv('PETLO_BAND_COLS', '4')))
    motion_disc_confidence: float | None = field(default_factory=lambda: _parse_optional_float(os.getenv('PETLO_MOTION_DISC_CONFIDENCE', '0.10')))

    def validate(self):
        if self.max_upload_bytes <= 0 or self.stage_timeout <= 0 or self.cpu_threads <= 0 or self.tile_batch_size <= 0:
            raise ValueError('Upload and timeout limits must be positive')
        if self.band_cols < 2 or self.band_cols > 6:
            raise ValueError('PETLO_BAND_COLS must be between 2 and 6')
        if self.disc_band is not None:
            y0, y1 = self.disc_band
            if not (0.0 <= y0 < y1 <= 1.0):
                raise ValueError('PETLO_DISC_BAND must satisfy 0 <= y0 < y1 <= 1')
        if self.motion_disc_confidence is not None and not (0.0 < self.motion_disc_confidence < 0.25):
            raise ValueError('PETLO_MOTION_DISC_CONFIDENCE must be in (0, 0.25)')
        if self.device != 'auto' and self.device != 'cpu' and not self.device.isdecimal():
            raise ValueError('PETLO_DEVICE must be auto, cpu or a CUDA device index')
        protected = [ROOT / name for name in ('cv', 'sources', 'src', 'database', 'docs', 'tests', 'backend', '.git', '.venv')]
        if ROOT.is_relative_to(self.storage) or any(self.storage.is_relative_to(path) for path in protected):
            raise ValueError('Storage must be outside algorithm and reference directories')
        if self.seed_demo and not self.database_url.startswith('sqlite:'):
            raise ValueError('Demo seeding is only allowed in SQLite. For MySQL use PETLO_SEED_DEMO=false.')
