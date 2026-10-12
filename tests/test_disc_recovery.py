import csv
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import cv2
import numpy as np

from cv.disc_recovery import RecoveryTracker,RecoverySettings,seed_profile
from cv.disc_tracker import DiscSettings,contract_rows
from cv.track_disc_recovered_video import run
from cv.track_dog_video import sha256,write_json
from cv.video_tools.media import Toolchain,scan_video

BLUE=(220,140,40)


def box(x): return [float(x),100.,float(x+24),112.]


def image(x=None,extra=None):
    frame=np.zeros((240,400,3),dtype=np.uint8)
    if x is not None: frame[100:112,x:x+24]=BLUE
    if extra is not None: frame[100:112,extra:extra+24]=BLUE
    return frame


def detection(x): return {'label':'disc','bbox':box(x),'confidence':.8}


class RecoverySafetyTests(unittest.TestCase):
    def initialized(self,recovery=None):
        t=RecoveryTracker(400,240,recovery=recovery)
        for i in range(6): state=t.update(i*.02,[detection(40+8*i)],image(40+8*i))
        self.assertEqual(state['tracks'][0]['track_id'],'disc-001')
        return t

    def test_visible_colour_observation_recovers_same_id_without_model_confidence(self):
        t=self.initialized()
        state=t.update(.12,[],image(88))
        o=state['tracks'][0]
        self.assertEqual(o['state'],'detected')
        self.assertEqual(o['measurement_source'],'local_visual')
        self.assertEqual(o['track_id'],'disc-001')
        self.assertIsNone(o['confidence'])
        self.assertIsNotNone(o['bbox'])
        row=contract_rows('test',{'frame_id':6,'t_sec':.12},state)[0]
        self.assertEqual(row['status'],'detected')
        self.assertIsNone(row['confidence'])
        self.assertTrue(state['recovery'][0]['accepted'])

    def test_model_anchor_expires_even_when_visual_updates_continue(self):
        t=self.initialized(RecoverySettings(max_visual_sec=.12))
        for i in range(6,11):
            state=t.update(i*.02,[],image(40+8*i))
            self.assertEqual(state['tracks'][0]['measurement_source'],'local_visual')
        state=t.update(.24,[],image(136))
        self.assertIsNone(state['tracks'][0]['bbox'])
        self.assertEqual(t.anchors['disc-001']['time'],.1)

    def test_disappearance_does_not_become_a_visual_measurement_or_refresh_clock(self):
        t=self.initialized()
        state=t.update(.12,[],image())
        self.assertIsNone(state['tracks'][0]['bbox'])
        self.assertEqual(state['tracks'][0]['state'],'predicted')
        self.assertEqual(t.base.tracks[0].last_time,.1)
        state=t.update(.26,[],image())
        self.assertEqual(state['tracks'][0]['state'],'lost')
        self.assertIsNone(state['tracks'][0]['prediction_bbox'])
        state=t.update(.48,[],image())
        self.assertEqual(state['retired_track_ids'],['disc-001'])
        self.assertEqual(t.anchors,{})

    def test_two_compatible_colour_components_are_rejected(self):
        t=self.initialized()
        frame=image(78,104)
        state=t.update(.12,[],frame)
        self.assertIsNone(state['tracks'][0]['bbox'])
        self.assertEqual(t.counts['colour_accepted'],0)

    def test_static_disc_does_not_start_background_search(self):
        t=RecoveryTracker(400,240)
        for i in range(8): t.update(i*.02,[detection(60)],image(60))
        state=t.update(.16,[],image(60))
        self.assertEqual(state['recovery'],[])
        self.assertIsNone(state['tracks'][0]['bbox'])

    def test_long_unobserved_gap_does_not_turn_average_displacement_into_current_velocity(self):
        t=self.initialized()
        before=list(t.base.tracks[0].velocity)
        for now in (.12,.16,.22): t.update(now,[],image())
        state=t.update(.3,[detection(250)],image(250))
        self.assertEqual(state['tracks'][0]['track_id'],'disc-001')
        self.assertTrue(state['tracks'][0]['velocity_update_held_after_gap'])
        self.assertEqual(t.base.tracks[0].velocity,before)
        state=t.update(.32,[detection(250)],image(250))
        self.assertEqual(state['tracks'][0]['track_id'],'disc-001')
        self.assertEqual(state['tracks'][0]['measurement_source'],'saved_detector')

    def test_background_coloured_like_the_seed_cannot_create_a_profile(self):
        frame=np.full((240,400,3),BLUE,dtype=np.uint8)
        self.assertIsNone(seed_profile(frame,box(100),9))
        self.assertIsNone(seed_profile(np.zeros_like(frame),box(100),9))

    def test_wrong_colour_near_prediction_is_not_accepted(self):
        t=self.initialized()
        frame=image()
        frame[100:112,88:112]=(40,220,40)
        state=t.update(.12,[],frame)
        self.assertIsNone(state['tracks'][0]['bbox'])

    def test_visual_candidate_in_a_second_tracks_gate_is_rejected(self):
        t=self.initialized()
        # A pre-existing competing tentative candidate must not inherit evidence.
        from cv.disc_tracker import _Track
        t.base.tracks.append(_Track(99,box(88),.10,[0.,0.],samples=1))
        state=t.update(.12,[],image(88))
        self.assertIsNone(next(o for o in state['tracks'] if o['track_id']=='disc-001')['bbox'])

    def test_local_yolo_coordinates_map_back_and_keep_real_model_confidence(self):
        from types import SimpleNamespace
        t=self.initialized()
        track=t.base.tracks[0]
        roi=t._roi(track,.12)
        b=np.array([[88-roi[0],100-roi[1],112-roi[0],112-roi[1]]],dtype=float)
        class Model:
            def predict(self,**kwargs):
                self.kwargs=kwargs
                return [SimpleNamespace(boxes=[SimpleNamespace(cls=[29],xyxy=b,conf=[.73])])]
        model=Model()
        t.model,t.names=model,{29:'frisbee'}
        state=t.update(.12,[],image())
        o=state['tracks'][0]
        self.assertEqual(o['measurement_source'],'local_yolo')
        self.assertEqual(o['bbox'],box(88))
        self.assertAlmostEqual(o['confidence'],.73)
        self.assertEqual(model.kwargs['conf'],.25)

    def test_frame_time_and_unbounded_settings_are_rejected(self):
        t=self.initialized()
        with self.assertRaises(ValueError): t.update(.1,[],image())
        with self.assertRaises(ValueError): t.update(.12,[],np.zeros((10,10,3),dtype=np.uint8))
        for values in ({'max_visual_sec':2},{'min_history':True},{'hue_tolerance':30},{'roi_imgsz':0}):
            with self.assertRaises(ValueError): RecoverySettings(**values)


class RecoveryMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.tools=Toolchain.discover()
        except (ValueError,OSError,RuntimeError) as exc: raise unittest.SkipTest(str(exc))

    def test_real_frames_csv_provenance_and_cached_replay(self):
        with tempfile.TemporaryDirectory(prefix='recovered-disc-test-') as tmp:
            root=Path(tmp)
            raw=root/'raw';raw.mkdir()
            frames=root/'frames';frames.mkdir()
            for i in range(14): cv2.imwrite(str(frames/f'{i:03d}.png'),image(40+8*i))
            source=raw/'disc.mkv'
            subprocess.run([self.tools.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-framerate','50','-i',str(frames/'%03d.png'),
                '-vf','select=lte(n\\,6)+eq(n\\,8)+eq(n\\,10)+gte(n\\,12)','-fps_mode','vfr','-c:v','ffv1',str(source)],capture_output=True,check=True)
            metadata,index,_=scan_video(source,self.tools)
            pack=root/'pack';pack.mkdir()
            write_json(pack/'frames.json',index)
            write_json(pack/'manifest.json',{'videos':[{'id':'disc','source':str(source),'source_sha256':sha256(source),'status':'complete','role':'action',
                'width':400,'height':240,'frames_count':len(index),'duration':metadata['duration'],'metadata':metadata,'paths':{'frame_index':'frames.json'}}]})
            det=root/'detect.jsonl'
            rows=[{'video_id':'disc',**r,'detections':[detection(40+8*round(r['t_sec']*50))] if r['t_sec']<.12 or r['t_sec']>=.24 else []} for r in index]
            det.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
            write_json(det.with_suffix('.json'),{'status':'complete','video_id':'disc','source':str(source),'source_sha256':sha256(source),
                'first_frame':index[0],'last_frame':index[-1],'counts':{'processed_frames':11,'disc_frames':8,'dog_frames':0,'person_frames':0}})
            before=sha256(source)
            output=root/'result'
            summary=run(det,pack,output,ffmpeg_dir=Path(self.tools.ffmpeg).parent)
            self.assertEqual(summary['processed_frames'],11)
            self.assertEqual(summary['track_count'],1)
            self.assertEqual(summary['recovery_counts']['colour_accepted'],3)
            states=[json.loads(s) for s in (output/'states.jsonl').read_text().splitlines()]
            self.assertEqual([s['t_sec'] for s in states],[r['t_sec'] for r in index])
            self.assertAlmostEqual(states[7]['t_sec']-states[6]['t_sec'],.04)
            with (output/'trajectory.csv').open(newline='') as f: rows=list(csv.DictReader(f))
            self.assertEqual(rows[6]['measurement_source'],'local_visual')
            self.assertEqual(rows[6]['confidence'],'')
            self.assertNotEqual(rows[6]['measured_x_px'],'')
            self.assertEqual(sha256(source),before)
            self.assertEqual(run(det,pack,output,ffmpeg_dir=Path(self.tools.ffmpeg).parent)['cache_key'],summary['cache_key'])
            with self.assertRaisesRegex(ValueError,'different input/settings'):
                run(det,pack,output,recovery=RecoverySettings(max_visual_sec=.5),ffmpeg_dir=Path(self.tools.ffmpeg).parent)


if __name__=='__main__': unittest.main()
