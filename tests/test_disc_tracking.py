"""Disc association failure cases and real-media/provenance regression tests."""
import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from cv.disc_tracker import DiscTracker, DiscSettings, center, contract_rows
from cv.track_disc_video import run
from cv.track_dog_video import write_json, sha256
from cv.video_tools.media import Toolchain, scan_video
from cv.build_disc_tracking_review import build


def disc(x=100, y=100, confidence=.8, label='disc', size=12):
    return {'label':label,'bbox':[x,y,x+size,y+size],'confidence':confidence}


class DiscAssociationTests(unittest.TestCase):
    def initialized(self, settings=None):
        t = DiscTracker(1000,600,settings)
        t.update(0.,[disc()])
        state = t.update(.02,[disc(110)])
        self.assertEqual(state['tracks'][0]['track_id'],'disc-001')
        return t

    def test_isolated_false_positive_needs_consecutive_confirmation(self):
        t = DiscTracker(1000,600)
        self.assertIsNone(t.update(0.,[disc()])['tracks'][0]['track_id'])
        self.assertEqual(t.update(.02,[])['tracks'],[])
        self.assertIsNone(t.update(.04,[disc()])['tracks'][0]['track_id'])
        self.assertEqual(t.update(.06,[disc()])['tracks'][0]['track_id'],'disc-001')

    def test_two_discs_and_detection_order_have_distinct_stable_ids(self):
        t = DiscTracker(1000,600)
        t.update(0.,[disc(),disc(700)])
        state = t.update(.02,[disc(700),disc(110)])
        self.assertEqual(len({v['track_id'] for v in state['tracks']}),2)
        moving = next(v['track_id'] for v in state['tracks'] if v['bbox'][0]==110)
        state = t.update(.04,[disc(120),disc(700)])
        self.assertEqual(next(v['track_id'] for v in state['tracks'] if v['bbox'][0]==120),moving)

    def test_fast_small_disc_learns_velocity_during_confirmation(self):
        t = DiscTracker(1000,600)
        t.update(0.,[disc()])
        t.update(.02,[disc(155)])
        state = t.update(.04,[disc(210)])
        self.assertEqual(state['tracks'][0]['track_id'],'disc-001')
        self.assertEqual(state['tracks'][0]['bbox'],disc(210)['bbox'])

    def test_gap_prediction_uses_vfr_time_and_is_not_a_detection(self):
        t = self.initialized()
        a = t.update(.04,[])
        b = t.update(.10,[])
        pa,pb = center(a['tracks'][0]['prediction_bbox']),center(b['tracks'][0]['prediction_bbox'])
        self.assertAlmostEqual(pb[0]-116,4*(pa[0]-116))
        rows = contract_rows('test',{'frame_id':3,'t_sec':.1},b)
        self.assertEqual(rows[0]['status'],'missing')
        self.assertIsNone(rows[0]['bbox'])
        self.assertIsNone(rows[0]['confidence'])
        back = t.update(.12,[disc(160)])['tracks'][0]
        self.assertEqual(back['track_id'],'disc-001')
        self.assertTrue(back['reacquired'])

    def test_prediction_expires_then_id_retires_and_new_id_confirms(self):
        t = self.initialized()
        lost = t.update(.2,[])['tracks'][0]
        self.assertEqual(lost['state'],'lost')
        self.assertIsNone(lost['prediction_bbox'])
        state = t.update(.5,[disc(800)])
        self.assertEqual(state['retired_track_ids'],['disc-001'])
        state = t.update(.52,[disc(800)])
        self.assertEqual(state['tracks'][0]['track_id'],'disc-002')

    def test_high_confidence_distant_outlier_does_not_take_old_id(self):
        t = self.initialized()
        state = t.update(.04,[disc(850,confidence=.99)])
        old = next(v for v in state['tracks'] if v['track_id']=='disc-001')
        self.assertIsNone(old['bbox'])
        self.assertEqual(old['state'],'predicted')

    def test_person_and_dog_boxes_cannot_become_discs(self):
        t = self.initialized()
        state = t.update(.04,[disc(120,label='dog'),disc(120,label='person')])
        self.assertIsNone(state['tracks'][0]['bbox'])
        self.assertEqual(state['raw_disc_count'],0)

    def test_duplicate_contained_crop_does_not_create_extra_id(self):
        t = DiscTracker(1000,600)
        duplicate = {'label':'disc','bbox':[103,102,110,110],'confidence':.6}
        t.update(0.,[disc(),duplicate,disc(700)])
        state = t.update(.02,[disc(),duplicate,disc(700)])
        self.assertEqual(state['duplicate_count'],1)
        self.assertEqual(t.track_count,2)

    def test_ambiguous_candidates_are_not_forced_or_born_as_duplicates(self):
        t = DiscTracker(1000,600)
        t.update(0.,[disc()])
        t.update(.02,[disc()])
        state = t.update(.04,[disc(95,103,size=6),disc(111,103,size=6)])
        self.assertEqual(len(state['tracks']),1)
        self.assertEqual(state['tracks'][0]['reason'],'ambiguous_association')
        self.assertIsNone(state['tracks'][0]['bbox'])

    def test_one_detection_is_never_shared_by_two_tracks_at_crossing(self):
        t = DiscTracker(1000,600)
        t.update(0.,[disc(100,size=4),disc(160,size=4)])
        t.update(.02,[disc(110,size=4),disc(150,size=4)])
        state = t.update(.06,[disc(130,size=4)])
        self.assertFalse(any(v['bbox'] for v in state['tracks']))
        self.assertEqual(t.track_count,2)

    def test_capacity_and_confidence_filtering_are_explicit(self):
        t = DiscTracker(1000,600,DiscSettings(max_tracks=1))
        state = t.update(0.,[disc(),disc(700),disc(850,confidence=.1)])
        self.assertEqual(len(state['tracks']),1)
        self.assertEqual(state['capacity_rejections'],1)
        self.assertEqual(state['candidate_count'],2)

    def test_prediction_outside_frame_is_not_drawn_as_a_clipped_measurement(self):
        t = DiscTracker(1000,600)
        t.update(0.,[disc(950)])
        t.update(.02,[disc(980)])
        state = t.update(.06,[])['tracks'][0]
        self.assertEqual(state['state'],'lost')
        self.assertIsNone(state['prediction_bbox'])
        self.assertIsNone(state['bbox'])

    def test_invalid_time_dimensions_boxes_and_settings_are_rejected(self):
        t = self.initialized()
        for now in (.02,float('nan'),True):
            with self.assertRaises(ValueError): t.update(now,[])
        for d in (disc(-1),disc(confidence=float('nan')),{'label':'disc','bbox':[0,0,1],'confidence':.8}):
            with self.assertRaises(ValueError): t.update(.04,[d])
        for setting in ({'prediction_sec':1},{'confirm_samples':True},{'max_tracks':0},{'confidence':2},{'gate_diagonal_fraction':0}):
            with self.assertRaises(ValueError): DiscSettings(**setting)
        with self.assertRaises(ValueError): DiscTracker(float('nan'),600)


class DiscMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.tools = Toolchain.discover()
        except (ValueError,RuntimeError,OSError) as exc: raise unittest.SkipTest(str(exc))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='disc-tracking-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'raw'/'discs.mkv'
        self.source.parent.mkdir()
        subprocess.run([self.tools.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-f','lavfi','-i',
            'testsrc2=size=96x64:rate=10:duration=1','-vf','select=eq(n\\,0)+eq(n\\,1)+eq(n\\,4)+eq(n\\,9)',
            '-fps_mode','vfr','-c:v','ffv1',str(self.source)],capture_output=True,check=True)
        metadata,self.index,_ = scan_video(self.source,self.tools)
        self.pack = self.root/'pack'
        self.pack.mkdir()
        write_json(self.pack/'frame_index.json',self.index)
        self.video = {'id':'discs','source':str(self.source),'source_sha256':sha256(self.source),'status':'complete','role':'action',
                      'width':96,'height':64,'frames_count':4,'duration':metadata['duration'],
                      'paths':{'frame_index':'frame_index.json'},'metadata':metadata}
        write_json(self.pack/'manifest.json',{'videos':[self.video]})
        self.det = self.root/'detections.jsonl'
        self.rows = [{'video_id':'discs',**r,'detections':[disc(10,10),disc(65,10)] if i!=2 else []} for i,r in enumerate(self.index)]
        self.det.write_text(''.join(json.dumps(r)+'\n' for r in self.rows),encoding='utf-8')
        write_json(self.det.with_suffix('.json'),{'status':'complete','source':str(self.source),'source_sha256':sha256(self.source),
            'video_id':'discs','first_frame':self.index[0],'last_frame':self.index[-1],
            'counts':{'processed_frames':4,'disc_frames':3,'dog_frames':0,'person_frames':0}})

    def test_real_vfr_replay_schema_csv_and_cache_preserve_original(self):
        output = self.root/'result'
        before = sha256(self.source)
        summary = run(self.det,self.pack,output,ffmpeg_dir=Path(self.tools.ffmpeg).parent)
        self.assertEqual(summary['processed_frames'],4)
        states = [json.loads(r) for r in (output/'states.jsonl').read_text().splitlines()]
        self.assertEqual([r['t_sec'] for r in states],[r['t_sec'] for r in self.index])
        rows = [json.loads(r) for r in (output/'tracks.jsonl').read_text().splitlines()]
        self.assertEqual(len({r['track_id'] for r in rows if r['status']=='detected'}),2)
        self.assertTrue(all(r['bbox'] is None for r in rows if r['status']=='missing'))
        with (output/'trajectory.csv').open(newline='') as handle: csv_rows = list(csv.DictReader(handle))
        self.assertTrue(all(r['measured_x_px']=='' for r in csv_rows if r['frame_id']=='2'))
        self.assertEqual(sha256(self.source),before)
        self.assertEqual(run(self.det,self.pack,output,ffmpeg_dir=Path(self.tools.ffmpeg).parent)['cache_key'],summary['cache_key'])
        (output/'tracks.jsonl').write_text('changed',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Cached output changed'):
            run(self.det,self.pack,output,ffmpeg_dir=Path(self.tools.ffmpeg).parent)

    def test_window_has_true_source_frame_ids_not_local_numbering(self):
        output = self.root/'window'
        summary = run(self.det,self.pack,output,start=.1,end=.5,ffmpeg_dir=Path(self.tools.ffmpeg).parent)
        self.assertEqual(summary['processed_frames'],2)
        rows = [json.loads(r) for r in (output/'states.jsonl').read_text().splitlines()]
        self.assertEqual([r['frame_id'] for r in rows],[1,2])

    def test_gallery_keeps_cfr_replay_clock_and_protects_modified_output(self):
        output = self.root/'gallery'
        for slug in ('front','side','handheld'):
            run(self.det,self.pack,output/f'{slug}-v1',ffmpeg_dir=Path(self.tools.ffmpeg).parent)
        page = build(output,Path(self.tools.ffmpeg).parent)
        rendered = page.read_text(encoding='utf-8')
        self.assertIn('v.currentTime*s.fps',rendered)
        self.assertIn('current.t_sec.toFixed(3)',rendered)
        self.assertTrue((output/'all-tracks.jsonl').is_file())
        self.assertEqual(build(output,Path(self.tools.ffmpeg).parent),page)
        page.write_text('modified',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Gallery changed'):
            build(output,Path(self.tools.ffmpeg).parent)
        self.assertEqual(page.read_text(),'modified')

    def test_existing_directory_and_input_paths_are_never_overwritten(self):
        for output in (self.source.parent/'bad',self.pack/'bad',self.root):
            with self.assertRaises(ValueError): run(self.det,self.pack,output,ffmpeg_dir=Path(self.tools.ffmpeg).parent)
        output = self.root/'existing'
        output.mkdir()
        marker = output/'keep.txt'
        marker.write_text('keep')
        with self.assertRaises(OSError): run(self.det,self.pack,output,ffmpeg_dir=Path(self.tools.ffmpeg).parent)
        self.assertEqual(marker.read_text(),'keep')


if __name__ == '__main__': unittest.main()
