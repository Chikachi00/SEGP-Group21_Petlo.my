"""Analysis-only preparation keeps source evidence while avoiding review renders."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cv.video_tools import cli
from cv.video_tools.media import MediaError
from tests.test_video_tools import VideoFixtures


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class AnalysisPrepareTests(VideoFixtures):
    def test_analysis_only_preserves_full_indexes_and_modes_do_not_share_cache(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            output = Path(folder) / "pack"
            full = self.prepare_module.prepare(self.source, output, self.tools)
            evidence = {video["id"]: {
                "frames": read_json(output / video["paths"]["frame_index"]),
                "motion": read_json(output / video["paths"]["motion_index"]),
                "metadata": video["metadata"], "hash": video["source_sha256"], "key": video["cache_key"],
            } for video in full["videos"]}
            with patch.object(self.prepare_module, "extract_frames", side_effect=AssertionError("Unexpected JPEG extraction")), \
                 patch.object(self.prepare_module, "_contact_sheet", side_effect=AssertionError("Unexpected contact sheet")):
                light = self.prepare_module.prepare(self.source, output, self.tools, review_artifacts=False)
            self.assertIsNone(light["overview"])
            self.assertFalse(light["parameters"]["review_artifacts"])
            self.assertEqual(list(output.rglob("*.jpg")), [])
            for video in light["videos"]:
                with self.subTest(video=video["id"]):
                    previous = evidence[video["id"]]
                    self.assertEqual(video["status"], "complete")
                    self.assertFalse(video["cached"])
                    self.assertNotEqual(video["cache_key"], previous["key"])
                    self.assertEqual(video["source_sha256"], previous["hash"])
                    self.assertEqual(video["source_sha256"], hashlib.sha256(Path(video["source"]).read_bytes()).hexdigest())
                    self.assertEqual(video["metadata"], previous["metadata"])
                    self.assertEqual(read_json(output / video["paths"]["frame_index"]), previous["frames"])
                    self.assertEqual(read_json(output / video["paths"]["motion_index"]), previous["motion"])
                    self.assertEqual(read_json(output / video["paths"]["image_index"]), [])
                    self.assertEqual(read_json(output / video["paths"]["candidates"]), [])
                    self.assertIsNone(video["paths"]["overview"])
            with patch.object(self.prepare_module, "scan_video", side_effect=AssertionError("Cache should not decode")):
                cached = self.prepare_module.prepare(self.source, output, self.tools, review_artifacts=False)
            self.assertTrue(all(video["cached"] for video in cached["videos"]))
            # An incomplete index must invalidate even the analysis-only cache.
            (output / light["videos"][0]["paths"]["frame_index"]).write_text("[]", encoding="utf-8")
            repaired = self.prepare_module.prepare(self.source, output, self.tools, review_artifacts=False)
            self.assertFalse(repaired["videos"][0]["cached"])
            self.assertEqual(repaired["videos"][0]["status"], "complete")
            restored = self.prepare_module.prepare(self.source, output, self.tools)
            self.assertTrue(all(not video["cached"] and video["images_count"] > 0 for video in restored["videos"]))
            self.assertTrue((output / restored["overview"]).is_file())

    def test_analysis_only_reports_full_decode_failure(self):
        with tempfile.TemporaryDirectory(dir=self.root) as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "Tripod.mp4").write_bytes(self.cfr.read_bytes())
            with patch.object(self.prepare_module, "scan_video", side_effect=MediaError("Incomplete decode")):
                manifest = self.prepare_module.prepare(source, root / "pack", self.tools, review_artifacts=False)
            self.assertEqual(manifest["videos"][0]["status"], "failed")
            self.assertIn("Incomplete decode", manifest["videos"][0]["error"])


class PrepareCliTests(unittest.TestCase):
    def test_cli_skips_guides_only_when_explicitly_requested(self):
        report = {"videos": [{"id": "v", "status": "complete", "frames_count": 10}]}
        for light in (False, True):
            with self.subTest(light=light), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                with patch("cv.video_tools.media.Toolchain.discover", return_value=object()), \
                     patch("cv.video_tools.prepare.prepare", return_value=report) as prepare, \
                     patch("cv.video_tools.guide.write_guides") as guide, contextlib.redirect_stdout(io.StringIO()):
                    arguments = ["prepare", "--source", str(root / "source"), "--output", str(root / "pack")]
                    if light:
                        arguments.append("--no-review-artifacts")
                    self.assertEqual(cli.main(arguments), 0)
                    self.assertEqual(prepare.call_args.kwargs["review_artifacts"], not light)
                    self.assertEqual(guide.call_count, 0 if light else 1)


if __name__ == "__main__":
    unittest.main()
