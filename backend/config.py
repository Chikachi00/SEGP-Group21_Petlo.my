from dataclasses import dataclass, field
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / 'backend/.env', override=False)


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

    def validate(self):
        if self.max_upload_bytes <= 0 or self.stage_timeout <= 0:
            raise ValueError('Upload and timeout limits must be positive')
        protected = [ROOT / name for name in ('cv', 'sources', 'src', 'database', 'docs', 'tests', 'backend', '.git', '.venv')]
        if ROOT.is_relative_to(self.storage) or any(self.storage.is_relative_to(path) for path in protected):
            raise ValueError('Storage must be outside algorithm and reference directories')
        if self.seed_demo and not self.database_url.startswith('sqlite:'):
            raise ValueError('Demo seeding is only allowed in SQLite. For MySQL use PETLO_SEED_DEMO=false.')
