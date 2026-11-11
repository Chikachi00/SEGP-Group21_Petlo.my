"""Exercise worker files and progress transport without importing inference tools."""
import json
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend import analysis_worker
from backend.config import ROOT, Settings
from backend.pipeline import PipelineRunner, SAMPLES, digest


class WorkerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings = Settings(storage=self.root / 'storage', model=self.root / 'model.pt',
            stage_timeout=10, device='cpu', cpu_threads=2, tile_batch_size=3)
        self.videos = [{'video_id': 'video', 'storage_key': 'uploads/video.mp4',
                        'camera_perspective': 'front', 'source_sha256': 'test-only'}]
        self.runner = PipelineRunner(self.settings)
        self.runner.check_ready = Mock()
        self.runner.tools = Mock(return_value=SimpleNamespace(ffmpeg=str(self.root / 'tools' / 'ffmpeg.exe')))

    def tearDown(self):
        self.temp.cleanup()

    def test_partial_progress_lines_resume_once_and_final_progress_is_delivered(self):
        observed = []
        result = {'statistics': {'test': True}, 'events': []}
        test = self

        class FakeControl:
            def command(self, args, *, cwd, stdout, timeout, on_progress):
                test.assertEqual(args[:3], [sys.executable, '-m', 'backend.analysis_worker'])
                test.assertEqual(cwd, ROOT)
                test.assertEqual(timeout, 10)
                request_path = Path(args[-1])
                request = json.loads(request_path.read_text(encoding='utf-8'))
                test.assertEqual(request['videos'], test.videos)
                test.assertEqual(request['device'], 'cpu')
                test.assertEqual(request['cpu_threads'], 2)
                test.assertEqual(request['tile_batch_size'], 3)
                progress = request_path.parent / 'progress.jsonl'
                progress.write_text('{"stage":"pre', encoding='utf-8')
                test.assertFalse(on_progress())
                test.assertEqual(observed, [])
                with progress.open('a', encoding='utf-8') as stream:
                    stream.write('pare"}\n{"stage":"front:detect"}\n{"stage":"stati')
                test.assertTrue(on_progress())
                test.assertEqual(observed, ['prepare', 'front:detect'])
                test.assertFalse(on_progress())
                with progress.open('a', encoding='utf-8') as stream:
                    stream.write('stics"}\n')
                (request_path.parent / 'result.json').write_text(json.dumps(result), encoding='utf-8')
                # Simulate a last update written just as the worker exits; the
                # API runner must drain it even if the control loop missed it.

        self.assertEqual(self.runner.run('partial-lines', 'single_view', self.videos, observed.append, FakeControl()), result)
        self.assertEqual(observed, ['prepare', 'front:detect', 'statistics'])

    def test_worker_failure_propagates_and_never_accepts_result_file(self):
        result = {'statistics': {'should_not_be_returned': True}}

        class FailedControl:
            def command(self, args, *, cwd, stdout, timeout, on_progress):
                root = Path(args[-1]).parent
                (root / 'progress.jsonl').write_text('{"stage":"front:detect"}\n', encoding='utf-8')
                on_progress()
                (root / 'result.json').write_text(json.dumps(result), encoding='utf-8')
                raise subprocess.CalledProcessError(7, args)

        observed = []
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            self.runner.run('failed-worker', 'single_view', self.videos, observed.append, FailedControl())
        self.assertEqual(raised.exception.returncode, 7)
        self.assertEqual(observed, ['front:detect'])

    def test_complete_invalid_progress_record_fails_instead_of_being_skipped(self):
        class InvalidControl:
            def command(self, args, *, cwd, stdout, timeout, on_progress):
                (Path(args[-1]).parent / 'progress.jsonl').write_text('not-json\n', encoding='utf-8')
                on_progress()

        with self.assertRaises(json.JSONDecodeError):
            self.runner.run('invalid-progress', 'single_view', self.videos, lambda _stage: None, InvalidControl())

    def worker_request(self, identity):
        root = self.settings.storage / 'jobs' / identity
        root.mkdir(parents=True)
        path = root / 'request.json'
        path.write_text(json.dumps({'job_id': identity, 'mode': 'single_view', 'videos': self.videos,
            'storage': str(self.settings.storage), 'model': str(self.settings.model), 'ffmpeg_dir': None,
            'stage_timeout': 10, 'device': 'cpu', 'cpu_threads': 2, 'tile_batch_size': 3}), encoding='utf-8')
        return path

    def test_worker_writes_progress_and_result_using_requested_runtime_settings(self):
        request = self.worker_request('worker-main')
        result = {'statistics': {'test': True}, 'events': []}
        runner = Mock()

        def run_direct(job_id, mode, videos, update):
            self.assertEqual((job_id, mode, videos), ('worker-main', 'single_view', self.videos))
            update('prepare')
            update('statistics')
            return result

        runner.run_direct.side_effect = run_direct
        with patch.object(analysis_worker, 'PipelineRunner', return_value=runner) as constructor, \
             patch.object(sys, 'argv', ['analysis_worker', str(request)]):
            analysis_worker.main()
        settings = constructor.call_args.args[0]
        self.assertEqual(settings.storage, self.settings.storage)
        self.assertEqual(settings.device, 'cpu')
        self.assertEqual(settings.cpu_threads, 2)
        self.assertEqual(settings.tile_batch_size, 3)
        self.assertEqual(json.loads((request.parent / 'result.json').read_text(encoding='utf-8')), result)
        self.assertEqual([json.loads(line)['stage'] for line in (request.parent / 'progress.jsonl').read_text(encoding='utf-8').splitlines()],
            ['prepare', 'statistics'])

    def test_worker_operation_failure_retains_progress_without_publishing_result(self):
        request = self.worker_request('worker-error')

        def fail(_job_id, _mode, _videos, update):
            update('prepare')
            raise ValueError('Stage failed')

        runner = Mock()
        runner.run_direct.side_effect = fail
        with patch.object(analysis_worker, 'PipelineRunner', return_value=runner), \
             patch.object(sys, 'argv', ['analysis_worker', str(request)]):
            with self.assertRaisesRegex(ValueError, 'Stage failed'):
                analysis_worker.main()
        self.assertFalse((request.parent / 'result.json').exists())
        self.assertEqual(json.loads((request.parent / 'progress.jsonl').read_text(encoding='utf-8')), {'stage': 'prepare'})

    def test_worker_refuses_request_outside_its_job_directory(self):
        original = self.worker_request('worker-boundary')
        outside = self.root / 'copied-request.json'
        outside.write_bytes(original.read_bytes())
        with patch.object(analysis_worker, 'PipelineRunner') as constructor, \
             patch.object(sys, 'argv', ['analysis_worker', str(outside)]):
            with self.assertRaisesRegex(ValueError, 'inside its job directory'):
                analysis_worker.main()
        constructor.assert_not_called()

    def test_worker_request_without_tile_setting_uses_compatible_default(self):
        request = self.worker_request('worker-compatible')
        payload = json.loads(request.read_text(encoding='utf-8'))
        payload.pop('tile_batch_size')
        request.write_text(json.dumps(payload), encoding='utf-8')
        runner = Mock()
        runner.run_direct.return_value = {'test': True}
        with patch.object(analysis_worker, 'PipelineRunner', return_value=runner) as constructor, \
             patch.object(sys, 'argv', ['analysis_worker', str(request)]):
            analysis_worker.main()
        self.assertEqual(constructor.call_args.args[0].tile_batch_size, 4)

    def test_paired_direct_pipeline_shares_one_model_and_disables_review_artifacts(self):
        uploads = self.settings.storage / 'uploads'
        uploads.mkdir(parents=True)
        self.settings.model.write_bytes(b'local model fixture')
        videos, samples = [], {}
        for view in ('front', 'side'):
            source = uploads / f'{view}.mp4'
            source.write_bytes(f'{view} source fixture'.encode())
            samples[view] = (SAMPLES[view][0], digest(source))
            videos.append({'video_id': f'{view}-video', 'storage_key': f'uploads/{view}.mp4',
                           'camera_perspective': view, 'source_sha256': digest(source)})

        def prepare(source, pack, tools, *, review_artifacts):
            self.assertFalse(review_artifacts)
            pack.mkdir()
            manifest = {'videos': [{'id': path.stem, 'source': str(path), 'status': 'complete', 'camera': 'tripod', 'role': 'action',
                'metadata': {'avg_frame_rate': 25.}, 'duration': 1., 'width': 640, 'height': 360} for path in source.iterdir()]}
            (pack / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            return manifest

        def preview(command, *, check, timeout):
            self.assertTrue(check)
            self.assertEqual(timeout, self.settings.stage_timeout)
            Path(command[-1]).write_bytes(b'browser preview fixture')

        def events(joint, detections, pack, output, *, ffmpeg_dir, review):
            self.assertFalse(review)
            output.mkdir(parents=True)
            (output / 'events-v3.json').write_text(json.dumps({'event_candidates': [{'throw_id': 'throw-001',
                'predicted_outcome': 'catch_candidate', 'start_sec': .1, 'end_sec': .4}]}), encoding='utf-8')

        def fuse(root):
            self.assertEqual(root.name, 'throw-events-v3')
            for view in ('front', 'side'):
                self.assertTrue((root / f'{view}-v1' / 'events-v3.json').is_file())
            (root / 'fused-results.json').write_text(json.dumps({'schema_version': 1, 'results': [{
                'sample_throw_id': 'sample-throw-001', 'outcome': 'uncertain', 'conflict': True,
                'front_outcome': 'catch_candidate', 'side_outcome': 'ground_pickup_candidate',
                'front_source_time_sec': [.1, .4], 'side_source_time_sec': [.2, .7]}]}), encoding='utf-8')

        model = Mock(name='shared-model')
        torch = SimpleNamespace(__version__='test-only', set_num_threads=Mock(), get_num_threads=Mock(return_value=2),
            cuda=SimpleNamespace(is_available=Mock(return_value=False), get_device_name=Mock()))
        observed = []
        with ExitStack() as stack:
            # Keep protocol checks independent of the optional Torch/CUDA
            # installation by replacing inference entry points and the import.
            stack.enter_context(patch.dict(sys.modules, {'torch': torch}))
            stack.enter_context(patch('backend.pipeline.SAMPLES', samples))
            pack = stack.enter_context(patch('cv.video_tools.prepare.prepare', side_effect=prepare))
            detector = stack.enter_context(patch('cv.detect_disc_video.run'))
            dog = stack.enter_context(patch('cv.track_dog_video.run'))
            disc = stack.enter_context(patch('cv.track_disc_recovered_video.run'))
            joint = stack.enter_context(patch('cv.analyze_dog_disc.run'))
            event_runner = stack.enter_context(patch('cv.analyze_throw_events_v3.run', side_effect=events))
            fusion = stack.enter_context(patch('cv.fuse_throw_events_v3.run', side_effect=fuse))
            load_model = stack.enter_context(patch('cv.detect_video.load_detection_model', return_value=model))
            previews = stack.enter_context(patch('backend.preview.subprocess.run', side_effect=preview))
            result = self.runner.run_direct('paired-worker', 'sample_pair', videos, observed.append)
        self.assertEqual(pack.call_count, 1)
        load_model.assert_called_once_with(str(self.settings.model))
        torch.set_num_threads.assert_called_once_with(2)
        model.add_callback.assert_called_once()
        self.assertEqual(model.add_callback.call_args.args[0], 'on_predict_start')
        inference_start = model.add_callback.call_args.args[1]
        inference_start(None)
        torch.set_num_threads.assert_called_once_with(2)
        torch.get_num_threads.return_value = 64
        inference_start(None)
        self.assertEqual(torch.set_num_threads.call_count, 2)
        self.assertEqual(torch.set_num_threads.call_args.args, (2,))
        for operation in (detector, dog, disc, joint, event_runner):
            self.assertEqual(operation.call_count, 2)
        for call in detector.call_args_list:
            self.assertIs(call.kwargs['model'], model)
            self.assertFalse(call.kwargs['render'])
            self.assertEqual(call.args[0].device, 'cpu')
            self.assertEqual(call.args[0].tile_batch_size, 3)
        for call in disc.call_args_list:
            self.assertIs(call.kwargs['model'], model)
            self.assertEqual(call.kwargs['model_path'], self.settings.model)
            self.assertEqual(call.kwargs['device'], 'cpu')
            self.assertFalse(call.kwargs['render'])
        self.assertTrue(all(not call.kwargs['render'] for call in dog.call_args_list))
        self.assertTrue(all(not call.kwargs['review'] for call in joint.call_args_list))
        self.assertEqual(previews.call_count, 2)
        fusion.assert_called_once()
        self.assertEqual(fusion.call_args.kwargs, {})
        self.assertEqual(result['events'], [{'event_id': 'paired-worker-sample-throw-001', 'category': 'uncertain',
            'conflict': True, 'source_intervals': [{'video_id': 'front-video', 'start_sec': .1, 'end_sec': .4},
                                                {'video_id': 'side-video', 'start_sec': .2, 'end_sec': .7}]}])
        self.assertEqual(result['statistics']['uncertain_events'], 1)
        self.assertFalse(result['statistics']['human_labels_used_for_statistics'])
        self.assertEqual(observed, ['prepare', 'front:preview', 'front:detect', 'front:dog_tracks', 'front:disc_tracks',
            'front:joint', 'front:events', 'side:preview', 'side:detect', 'side:dog_tracks', 'side:disc_tracks', 'side:joint',
            'side:events', 'fusion', 'statistics'])
        root = self.settings.storage / 'jobs' / 'paired-worker'
        self.assertFalse((root / 'evidence-previews').exists())
        runtime = json.loads((root / 'runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(runtime['device'], 'cpu')
        self.assertEqual(runtime['tile_batch_size'], 3)
        self.assertIsNone(runtime['gpu'])
