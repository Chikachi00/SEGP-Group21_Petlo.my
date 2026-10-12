import json
from pathlib import Path
import tempfile
import unittest
import subprocess

from cv.joint_analysis import JointSettings,analyze
from cv.analyze_dog_disc import run,sha256,write_json
from cv.build_joint_analysis_review import build as build_review
from cv.prepare_joint_previews import build as build_previews
from cv.video_tools.media import Toolchain,scan_video


def fixture(times,positions,dog_box=None,source='saved_detector',identity='disc-001'):
    records=[]; dogs=[]; discs=[]
    for i,(now,x) in enumerate(zip(times,positions)):
        r={'frame_id':i,'t_sec':now,'pts_sec':now+2,'timestamp_source':'pts_time'}
        records.append(r)
        dogs.append({**r,'track_id':'dog-001','state':'detected' if dog_box else 'lost','bbox':dog_box,
                     'confidence':.9 if dog_box else None,'prediction_bbox':None})
        discs.append({**r,'tracks':[{'track_id':identity,'state':'detected' if x is not None else 'predicted',
                     'bbox':[x,200.,x+20.,210.] if x is not None else None,'confidence':None if source=='local_visual' or x is None else .8,
                     'prediction_bbox':[500.,200.,520.,210.] if x is None else None,'measurement_source':source if x is not None else None}]})
    return dogs,discs,records


def calculate(data,camera='tripod'):
    return analyze(*data,1000,600,camera)


class JointEvidenceTests(unittest.TestCase):
    def test_source_time_not_frame_number_controls_pixel_motion(self):
        times=[0,.05,.11,.18,.24,.31,.39,.46,.53,.61]
        frames,events,_=calculate(fixture(times,[50+400*t for t in times]))
        speeds=[d['observed_speed_px_sec'] for f in frames for d in f['discs'] if d['moving']]
        self.assertTrue(speeds)
        for speed in speeds: self.assertAlmostEqual(speed,400)
        self.assertTrue(events)
        for e in events: self.assertIn(e['start_sec'],times)

    def test_predictions_and_disappearance_never_prove_catch(self):
        times=[i*.04 for i in range(35)]
        data=fixture(times,[40+400*t if i<23 else None for i,t in enumerate(times)],[350.,170.,430.,280.])
        frames,events,metrics=calculate(data)
        contacts=[e for e in events if e['type']=='contact_candidate']
        self.assertTrue(contacts)
        for e in contacts:
            self.assertEqual(e['outcome'],'uncertain')
            self.assertFalse(e['evidence']['mouth_localized'])
            self.assertIn('disc_disappears_after_proximity',e['uncertainty_reasons'])
        self.assertIsNone(metrics['catch_rate'])
        for f in frames[23:]:
            d=f['discs'][0]
            self.assertEqual(d['phase'],'unobserved')
            self.assertIsNone(d['gap_to_dog_px'])
            self.assertFalse(d['moving'])

    def test_stationary_plate_next_to_dog_does_not_create_contact(self):
        _,events,_=calculate(fixture([i*.04 for i in range(30)],[370]*30,[350.,170.,430.,280.]))
        self.assertEqual(events,[])

    def test_stationary_then_motion_is_only_throw_candidate(self):
        times=[i*.04 for i in range(40)]
        data=fixture(times,[50 if t<.6 else 50+(t-.6)*400 for t in times])
        _,events,_=calculate(data)
        throws=[e for e in events if e['type']=='throw_candidate']
        self.assertTrue(throws)
        self.assertTrue(all(e['outcome']=='uncertain' and e['model_probability'] is None for e in events))
        _,handheld,_=calculate(data,'handheld')
        self.assertTrue(handheld)
        self.assertFalse(any(e['type']=='throw_candidate' for e in handheld))
        self.assertTrue(all('camera_motion_not_compensated' in e['uncertainty_reasons'] for e in handheld))

    def test_visual_is_observation_with_distinct_source_not_yolo_probability(self):
        _,events,_=calculate(fixture([i*.04 for i in range(30)],[50+16*i for i in range(30)],source='local_visual'))
        self.assertTrue(events)
        self.assertTrue(all(e['evidence']['measurement_sources']=={'local_visual':e['evidence']['observed_samples']} for e in events))
        self.assertTrue(all('local_visual_box_can_cover_only_part_of_disc' in e['uncertainty_reasons'] for e in events))

    def test_long_gap_cannot_provide_displacement_or_connect_ids(self):
        times=[0,.04,.08,.6,.64,.68]
        data=fixture(times,[50,50,50,500,500,500])
        _,events,_=calculate(data)
        self.assertEqual(events,[])
        data=fixture([i*.04 for i in range(30)],[50+16*i for i in range(30)])
        for i,row in enumerate(data[1]):
            if i>=15: row['tracks'][0]['track_id']='disc-002'
        _,events,_=calculate(data)
        self.assertEqual({e['disc_id'] for e in events},{'disc-001','disc-002'})

    def test_missing_dog_cannot_supply_predicted_proximity(self):
        data=fixture([i*.04 for i in range(30)],[50+16*i for i in range(30)])
        for row in data[0]: row['prediction_bbox']=[200.,170.,400.,280.]
        frames,events,_=calculate(data)
        self.assertTrue(events)
        self.assertFalse(any(e['type']=='contact_candidate' for e in events))
        self.assertTrue(all(d['gap_to_dog_px'] is None for f in frames for d in f['discs']))

    def test_retired_disc_is_not_an_observation(self):
        data=fixture([i*.04 for i in range(30)],[50+16*i if i<20 else None for i in range(30)])
        data[1][20]['tracks'][0].update(state='retired',prediction_bbox=None)
        frames,_,_=calculate(data)
        self.assertEqual(frames[20]['discs'][0]['phase'],'unobserved')
        self.assertIsNone(frames[20]['discs'][0]['gap_to_dog_px'])

    def test_frame_mismatch_duplicate_id_or_invalid_observation_rejected(self):
        for mutate in (lambda data:data[0][2].update(t_sec=.123),
                       lambda data:data[1][2]['tracks'].append(dict(data[1][2]['tracks'][0])),
                       lambda data:data[1][2]['tracks'][0].update(measurement_source='prediction'),
                       lambda data:data[1][2]['tracks'][0].update(bbox=[-1,1,5,5]),
                       lambda data:data[1][2]['tracks'][0].update(state='lost')):
            data=fixture([i*.04 for i in range(20)],[50+16*i for i in range(20)])
            mutate(data)
            with self.assertRaises(ValueError): calculate(data)

    def test_invalid_settings_rejected(self):
        for opts in ({'motion_window_sec':float('nan')},{'min_contact_sec':0},{'observation_gap_sec':.5}):
            with self.assertRaises(ValueError): JointSettings(**opts)


class JointPipelineTests(unittest.TestCase):
    def create_inputs(self,root):
        source=root/'raw'/'sample.mp4';source.parent.mkdir();source.write_bytes(b'unchanged source fixture')
        pack=root/'pack';pack.mkdir()
        data=fixture([i*.04 for i in range(30)],[50+16*i for i in range(30)],[350.,170.,430.,280.])
        write_json(pack/'frames.json',data[2])
        v={'id':'fixture','source':str(source),'source_sha256':sha256(source),'status':'complete','role':'action',
           'camera':'tripod','width':1000,'height':600,'frames_count':30,'paths':{'frame_index':'frames.json'},'metadata':{'avg_frame_rate':25.}}
        write_json(pack/'manifest.json',{'videos':[v]})
        for name,rows in [('dog',data[0]),('disc',data[1])]:
            folder=root/name;folder.mkdir()
            (folder/'states.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            summary={'status':'complete','video_id':'fixture','source':str(source),'processed_frames':30,
                     'artifact_sha256':{'states.jsonl':sha256(folder/'states.jsonl')},
                     'provenance':{'source_sha256':sha256(source),'detections_sha256':'same detector','display_size':[1000,600]}}
            write_json(folder/'summary.json',summary)
        return root/'dog',root/'disc',pack,root/'output'

    def test_complete_pipeline_cache_and_originals_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.create_inputs(Path(temp))
            before={str(p):sha256(p) for parent in args[:3] for p in parent.iterdir() if p.is_file()}
            summary=run(*args)
            self.assertEqual(summary['metrics']['processed_frames'],30)
            self.assertTrue(summary['validated']['predictions_excluded_from_evidence'])
            self.assertEqual(summary,run(*args))
            self.assertEqual(before,{p:sha256(p) for p in before})
            events=json.loads((args[3]/'events.json').read_text())['candidate_events']
            self.assertTrue(events)
            self.assertTrue(all(e['outcome']=='uncertain' for e in events))
            self.assertIn('源帧',(args[3]/'index.html').read_text(encoding='utf-8'))
            (args[3]/'events.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'cache changed'): run(*args)

    def test_corrupt_input_time_or_source_and_unsafe_output_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            args=self.create_inputs(Path(temp))
            with self.assertRaisesRegex(ValueError,'independent output'): run(*args[:3],args[0]/'new')
            (args[1]/'states.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'recorded hash'): run(*args)
        with tempfile.TemporaryDirectory() as temp:
            args=self.create_inputs(Path(temp))
            (Path(temp)/'raw'/'sample.mp4').write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError,'Source identity'): run(*args)

    def test_review_index_reuses_runs_and_refuses_to_overwrite_edited_page(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);gallery=root/'gallery'
            for slug in ('front','side','handheld'):
                sample=root/slug;sample.mkdir()
                args=self.create_inputs(sample)
                run(*args[:3],gallery/(slug+'-v1'))
            page=build_review(gallery)
            self.assertEqual(build_review(gallery),page)
            page.write_text('manual edit')
            with self.assertRaisesRegex(ValueError,'changed input/content'): build_review(gallery)
            self.assertEqual(page.read_text(),'manual edit')


class JointCleanPreviewTests(unittest.TestCase):
    def test_vfr_clean_replay_preserves_all_frames_source_and_cache(self):
        tools=Toolchain.discover()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=root/'raw';raw.mkdir();pack=root/'pack';pack.mkdir()
            source=raw/'sample.mkv'
            subprocess.run([tools.ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=96x64:rate=10:duration=1',
                '-vf','select=eq(n\\,0)+eq(n\\,1)+eq(n\\,4)+eq(n\\,9)','-fps_mode','vfr','-c:v','ffv1',str(source)],check=True,capture_output=True)
            metadata,records,_=scan_video(source,tools)
            before=sha256(source)
            v={'id':'sample','status':'complete','role':'action','source':str(source),'source_sha256':before,
               'width':96,'height':64,'frames_count':len(records),'metadata':metadata}
            write_json(pack/'manifest.json',{'videos':[v]})
            output=root/'clean'
            build_previews(pack,output,Path(tools.ffmpeg).parent)
            result=read_json_for_test(output/'sample.json')
            self.assertEqual(result['signature']['source_frames'],4)
            self.assertEqual(before,sha256(source))
            self.assertEqual(build_previews(pack,output,Path(tools.ffmpeg).parent),output)
            (output/'sample.mp4').write_bytes(b'edited output')
            with self.assertRaisesRegex(ValueError,'cache changed'): build_previews(pack,output,Path(tools.ffmpeg).parent)
            self.assertEqual((output/'sample.mp4').read_bytes(),b'edited output')


def read_json_for_test(p): return json.loads(p.read_text(encoding='utf-8'))


if __name__=='__main__': unittest.main()
