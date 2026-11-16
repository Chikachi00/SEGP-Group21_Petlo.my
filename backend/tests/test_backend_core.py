"""Unit tests for backend core modules: config, schemas, pipeline helpers, and process control."""
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from backend.config import ROOT, Settings
from backend.pipeline import copy_verified, digest, inside, validate_selection, SAMPLES
from backend.process_control import JobCancelled, ProcessControl
from backend.schemas import (
    ControlJob,
    CreateDog,
    CreateSession,
    RenameSession,
    StartAnalysis,
    StatisticsOut,
)


class TestConfigSettings(unittest.TestCase):
    """Test configuration validation and boundary rules."""

    def test_default_settings_valid(self):
        """Default settings should validate cleanly."""
        settings = Settings()
        settings.validate()
        self.assertGreater(settings.max_upload_bytes, 0)
        self.assertGreater(settings.stage_timeout, 0)
        self.assertGreater(settings.cpu_threads, 0)
        self.assertGreater(settings.tile_batch_size, 0)

    def test_negative_or_zero_limits_rejected(self):
        """Zero or negative limits must raise ValueError."""
        with self.assertRaisesRegex(ValueError, "limits must be positive"):
            Settings(max_upload_bytes=0).validate()

        with self.assertRaisesRegex(ValueError, "limits must be positive"):
            Settings(stage_timeout=-1).validate()

        with self.assertRaisesRegex(ValueError, "limits must be positive"):
            Settings(cpu_threads=0).validate()

        with self.assertRaisesRegex(ValueError, "limits must be positive"):
            Settings(tile_batch_size=-5).validate()

    def test_device_selection_validation(self):
        """Only 'auto', 'cpu', or numeric CUDA indices are allowed."""
        Settings(device="auto").validate()
        Settings(device="cpu").validate()
        Settings(device="0").validate()
        Settings(device="1").validate()

        for invalid in ("gpu", "cuda", "mps", "cuda:0", "-1"):
            with self.assertRaisesRegex(ValueError, "PETLO_DEVICE must be auto, cpu or a CUDA device index"):
                Settings(device=invalid).validate()

    def test_protected_storage_path_rejected(self):
        """Storage cannot reside inside protected repository directories."""
        for protected_name in ("backend", "cv", "src", ".git", "database"):
            with self.assertRaisesRegex(ValueError, "Storage must be outside algorithm"):
                Settings(storage=(ROOT / protected_name / "subfolder")).validate()

    def test_mysql_demo_seeding_rejected(self):
        """Demo seeding is strictly forbidden on MySQL."""
        with self.assertRaisesRegex(ValueError, "Demo seeding is only allowed in SQLite"):
            Settings(
                database_url="mysql+pymysql://user:pass@localhost/petlo",
                seed_demo=True,
            ).validate()


class TestSchemas(unittest.TestCase):
    """Test Pydantic request/response schema validation and constraints."""

    def test_create_session_requires_timezone(self):
        """Creating a session with naive datetime must be rejected."""
        valid_payload = {
            "dog_id": "dog_123",
            "recorded_at": datetime.now(timezone.utc),
            "name": "Morning Practice",
        }
        session = CreateSession(**valid_payload)
        self.assertEqual(session.dog_id, "dog_123")
        self.assertEqual(session.name, "Morning Practice")

        # Timezone naive should fail validation
        with self.assertRaises(ValidationError) as ctx:
            CreateSession(
                dog_id="dog_123",
                recorded_at=datetime(2026, 11, 15, 10, 0, 0),  # No timezone
            )
        self.assertIn("recorded_at requires a timezone", str(ctx.exception))

    def test_create_session_boundary_rules(self):
        """Empty dog ID or extra fields must be rejected."""
        with self.assertRaises(ValidationError):
            CreateSession(dog_id="", name="Valid Name")

        with self.assertRaises(ValidationError):
            CreateSession(dog_id="dog_1", name="a" * 121)  # Max length 120

        with self.assertRaises(ValidationError):
            CreateSession(dog_id="dog_1", name="Valid", extra_field="forbidden")

    def test_rename_session_validation(self):
        """Session renaming validates string lengths and extra fields."""
        valid = RenameSession(name="  Trimmed Name  ")
        self.assertEqual(valid.name, "Trimmed Name")

        with self.assertRaises(ValidationError):
            RenameSession(name="")

        with self.assertRaises(ValidationError):
            RenameSession(name="a" * 121)

    def test_create_dog_validation(self):
        """Dog creation validates fields and dates."""
        dog = CreateDog(name="Buddy", breed="Border Collie", date_of_birth=date(2022, 5, 1))
        self.assertEqual(dog.name, "Buddy")
        self.assertEqual(dog.breed, "Border Collie")

        with self.assertRaises(ValidationError):
            CreateDog(name="", breed="Collie", date_of_birth=date(2022, 1, 1))

    def test_start_analysis_validation(self):
        """StartAnalysis requires valid modes and unique, non-empty video IDs."""
        valid = StartAnalysis(video_ids=["vid_1"], mode="single_view")
        self.assertEqual(valid.mode, "single_view")

        valid_pair = StartAnalysis(video_ids=["vid_1", "vid_2"], mode="paired_views")
        self.assertEqual(len(valid_pair.video_ids), 2)

        # Duplicate video IDs
        with self.assertRaises(ValidationError) as ctx:
            StartAnalysis(video_ids=["vid_1", "vid_1"], mode="sample_pair")
        self.assertIn("Video IDs must be non-empty and unique", str(ctx.exception))

        # Too many videos (> 2)
        with self.assertRaises(ValidationError):
            StartAnalysis(video_ids=["v1", "v2", "v3"], mode="paired_views")

        # Invalid mode
        with self.assertRaises(ValidationError):
            StartAnalysis(video_ids=["v1"], mode="invalid_mode")

    def test_control_job_actions(self):
        """ControlJob only accepts pause, resume, cancel."""
        for action in ("pause", "resume", "cancel"):
            control = ControlJob(action=action)
            self.assertEqual(control.action, action)

        for invalid in ("stop", "kill", "terminate", "restart"):
            with self.assertRaises(ValidationError):
                ControlJob(action=invalid)

    def test_statistics_out_validation(self):
        """StatisticsOut enforces non-negative counts and valid coverage bounds."""
        stats = StatisticsOut(
            report_type="unverified_candidate_statistics",
            total_throw_candidates=4,
            classified_candidate_events=4,
            uncertain_events=0,
            candidate_counts={
                "in_air_catch_candidate": 3,
                "ground_pickup_candidate": 1,
                "miss_candidate": 0,
                "uncertain": 0,
            },
            candidate_coverage=1.0,
            in_air_catch_candidate_rate=0.75,
            retrieval_candidate_rate=1.0,
            denominator_definition="Test definition",
            human_labels_used_for_statistics=False,
        )
        self.assertEqual(stats.total_throw_candidates, 4)

        # Coverage > 1.0 must fail
        with self.assertRaises(ValidationError):
            StatisticsOut(
                report_type="unverified_candidate_statistics",
                total_throw_candidates=1,
                classified_candidate_events=1,
                uncertain_events=0,
                candidate_counts={
                    "in_air_catch_candidate": 1,
                    "ground_pickup_candidate": 0,
                    "miss_candidate": 0,
                    "uncertain": 0,
                },
                candidate_coverage=1.5,  # Invalid
                in_air_catch_candidate_rate=1.0,
                retrieval_candidate_rate=1.0,
                denominator_definition="Test",
                human_labels_used_for_statistics=False,
            )


class TestPipelineHelpers(unittest.TestCase):
    """Test helper functions in backend/pipeline.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_digest_calculates_sha256(self):
        """digest() should accurately compute SHA-256 for files."""
        content = b"Hello Disc Dog Analytics"
        test_file = self.root / "test_data.bin"
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        self.assertEqual(digest(test_file), expected)

    def test_inside_guards_against_path_traversal(self):
        """inside() must resolve paths safely and reject path traversal attempts."""
        safe_path = inside(self.root, "subfolder/file.mp4")
        self.assertTrue(safe_path.is_relative_to(self.root))

        traversal_attempts = [
            "../outside.txt",
            "../../etc/passwd",
            "subfolder/../../escaped.bin",
        ]
        for key in traversal_attempts:
            with self.assertRaisesRegex(ValueError, "Storage key outside root"):
                inside(self.root, key)

    def test_validate_selection_single_view(self):
        """validate_selection() accepts 1 video for single_view and rejects anything else."""
        single = [{"camera_perspective": "front", "source_sha256": "any-hash"}]
        validate_selection("single_view", single)

        two_videos = [
            {"camera_perspective": "front", "source_sha256": "hash1"},
            {"camera_perspective": "side", "source_sha256": "hash2"},
        ]
        with self.assertRaisesRegex(ValueError, "Choose one video"):
            validate_selection("single_view", two_videos)

    def test_validate_selection_sample_pair(self):
        """sample_pair requires front and side perspectives with exact sample hashes."""
        front_hash = SAMPLES["front"][1]
        side_hash = SAMPLES["side"][1]

        valid_sample_pair = [
            {"camera_perspective": "front", "source_sha256": front_hash},
            {"camera_perspective": "side", "source_sha256": side_hash},
        ]
        validate_selection("sample_pair", valid_sample_pair)

        # Mismatched hash rejected for sample_pair
        bad_hash_pair = [
            {"camera_perspective": "front", "source_sha256": "wrong_hash"},
            {"camera_perspective": "side", "source_sha256": side_hash},
        ]
        with self.assertRaisesRegex(ValueError, "Sample-pair fusion supports only the original"):
            validate_selection("sample_pair", bad_hash_pair)

        # Same perspective twice rejected
        two_fronts = [
            {"camera_perspective": "front", "source_sha256": front_hash},
            {"camera_perspective": "front", "source_sha256": front_hash},
        ]
        with self.assertRaisesRegex(ValueError, "Choose one video, or one front and one side video"):
            validate_selection("sample_pair", two_fronts)

    def test_validate_selection_paired_views(self):
        """paired_views requires one front and one side view, allowing arbitrary source hashes."""
        valid_paired = [
            {"camera_perspective": "front", "source_sha256": "custom_front_hash"},
            {"camera_perspective": "side", "source_sha256": "custom_side_hash"},
        ]
        validate_selection("paired_views", valid_paired)

    def test_copy_verified_atomic_integrity(self):
        """copy_verified copies file atomically and removes corrupt targets upon failure."""
        source = self.root / "source.bin"
        target = self.root / "target.bin"
        content = b"Exact verified payload content"
        source.write_bytes(content)
        correct_hash = hashlib.sha256(content).hexdigest()

        # Success case
        copy_verified(source, target, correct_hash)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), content)

        # Failure case with wrong hash removes the target
        target2 = self.root / "target2.bin"
        with self.assertRaisesRegex(ValueError, "Stored source content changed"):
            copy_verified(source, target2, "incorrect_sha256_hash")
        self.assertFalse(target2.exists(), "Target file must be removed when hash verification fails")


class TestProcessControl(unittest.TestCase):
    """Test ProcessControl thread-safe state machine."""

    def test_lifecycle_requests_and_transitions(self):
        """Test pause, resume, and cancellation state transitions."""
        states = []
        control = ProcessControl(publish=states.append)

        # Initial pause before process start publishes 'paused'
        control.request("pause")
        self.assertTrue(control.pause_requested)
        self.assertIn("paused", states)

        # Resume before process start publishes 'queued'
        control.request("resume")
        self.assertFalse(control.pause_requested)
        self.assertIn("queued", states)

        # Cancel request publishes 'cancelling'
        control.request("cancel")
        self.assertTrue(control.cancel_requested)
        self.assertIn("cancelling", states)

        # Actions after cancellation must be rejected
        with self.assertRaisesRegex(ValueError, "This task can no longer be controlled"):
            control.request("pause")

    def test_unsupported_action_rejected(self):
        """Unsupported action raises ValueError."""
        control = ProcessControl(publish=lambda _: None)
        with self.assertRaisesRegex(ValueError, "Unsupported task action"):
            control.request("force_kill")

    def test_checkpoint_raises_job_cancelled(self):
        """checkpoint() should raise JobCancelled when cancel was requested."""
        control = ProcessControl(publish=lambda _: None)
        control.request("cancel")
        with self.assertRaises(JobCancelled):
            control.checkpoint()


if __name__ == "__main__":
    unittest.main()
