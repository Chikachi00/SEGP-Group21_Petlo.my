import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import cv2
import numpy as np

from cv.throw_events import EventSettings,analyze_events,observed_points,link_proposals,resolve_links
from cv.analyze_throw_events import crop_bounds,colour_feature,validate_ground,run,make_link_features
from cv.analyze_dog_disc import sha256,write_json
from cv.video_tools.media import Toolchain,scan_video


def fixture(count=75,mode='catch',missing=(),fragment=None):
    frames=[];detections=[]
    for i in range(count):
        t=i*.04
        dog_x=400 if t<.8 else 400+(t-.8)*100
        disc_x=50+450*t if t<.8 else 410+(t-.8)*100
        moving=t<.8
        if mode=='ground':
            if t>=.8:dog_x=650;disc_x=410
        if mode=='return':dog_x=400+100*t;disc_x=410+100*t;moving=True
        dog=[dog_x,170.,dog_x+70.,280.]
        box=[disc_x,200.,disc_x+20.,210.] if i not in missing else None
        identity='disc-002' if fragment is not None and i>=fragment else 'disc-001'
        r={'frame_id':i,'t_sec':t,'pts_sec':2+t,'timestamp_source':'pts_time'}
        d={'disc_id':identity,'state':'detected' if box else 'predicted','bbox':box,
           'prediction_bbox':[420.,200.,440.,210.] if not box else None,'measurement_source':'saved_detector' if box else None,
           'confidence':.9 if box else None,'moving':moving if box else False,'approaching':t<.8 if box else False}
        frames.append({**r,'dog':{'track_id':'dog-001','state':'detected','bbox':dog,'confidence':.9,'prediction_bbox':None},'discs':[d]})
        detections.append({**r,'video_id':'test','detections':[{'label':'person','bbox':[20.,140.,90.,300.],'confidence':.9}]})
    return frames,detections


def analyze(data,**options):return analyze_events(*data,1000,600,**options)


class EpisodeEvidenceTests(unittest.TestCase):
    def test_release_approach_and_sustained_carry_form_one_unverified_episode(self):
        events,ledger,diagnostics=analyze(fixture())
        self.assertEqual(len(events),1)
        e=events[0]
        self.assertEqual(e['throw_id'],'throw-001')
        self.assertEqual(e['episode_kind'],'throw_candidate')
        self.assertEqual(e['predicted_outcome'],'catch_candidate')
        self.assertIsNone(e['confirmed_throw']);self.assertIsNone(e['verified_outcome']);self.assertIsNone(e['event_probability'])
        self.assertIsNone(diagnostics['metrics']['catch_rate'])
        self.assertFalse(e['carry_evidence']['mouth_localized'])
        self.assertGreaterEqual(e['carry_evidence']['end_sec']-e['carry_evidence']['start_sec'],.3-1e-9)
        self.assertIn('ready',{e['phase'] for r in ledger for e in r['events']})
        self.assertIn('contact_pending',{e['phase'] for r in ledger for e in r['events']})
        self.assertIn('carrying_candidate',{e['phase'] for r in ledger for e in r['events']})

    def test_predictions_and_disappearance_never_become_catch_or_miss(self):
        data=fixture(missing=range(25,75))
        events,ledger,_=analyze(data)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['predicted_outcome'],'uncertain')
        self.assertIsNone(events[0]['carry_evidence'])
        self.assertIn('unobserved',{e['phase'] for r in ledger for e in r['events']})
        self.assertEqual(sum(events[0]['observation_sources'].values()),len([r for r in data[0] if events[0]['start_frame']<=r['frame_id']<=events[0]['end_frame'] and r['discs'][0]['bbox']]))

    def test_returning_with_disc_does_not_create_new_throw_even_with_dog_missing(self):
        data=fixture(mode='return')
        for i,r in enumerate(data[0]):
            if i%3==0:r['dog'].update(state='predicted',bbox=None,prediction_bbox=[400.,170.,470.,280.],confidence=None)
        events,_,diagnostics=analyze(data)
        self.assertEqual(events,[])
        self.assertTrue(diagnostics['suppressed_candidates'])

    def test_held_person_motion_stays_suppressed(self):
        data=fixture(count=30)
        for i,r in enumerate(data[0]):r['discs'][0]['bbox']=[30+i,200.,50+i,210.]
        events,_,d=analyze(data)
        self.assertEqual(events,[])
        self.assertEqual(d['suppressed_candidates'][0]['reason'],'motion_stays_near_person')

    def test_visual_only_near_dog_motion_cannot_supply_carry_model_anchors(self):
        data=fixture()
        for r in data[0]:r['discs'][0].update(measurement_source='local_visual',confidence=None)
        events,_,_=analyze(data)
        self.assertEqual(events[0]['predicted_outcome'],'uncertain')
        self.assertIsNone(events[0]['carry_evidence'])

    def test_static_after_flight_without_verified_ground_stays_uncertain(self):
        events,_,_=analyze(fixture(mode='ground'))
        self.assertEqual(events[0]['predicted_outcome'],'uncertain')
        self.assertIsNone(events[0]['ground_evidence'])

    def test_reviewed_ground_plus_still_disc_and_separate_dog_is_only_miss_candidate(self):
        labels=[{'disc_id':'disc-001','frame_id':20,'verified':True,'reviewer':'Test reviewer'}]
        events,_,_=analyze(fixture(mode='ground'),ground_contacts=labels)
        self.assertEqual(events[0]['predicted_outcome'],'miss_candidate')
        self.assertIsNone(events[0]['verified_outcome'])
        labels[0]['verified']=False
        with self.assertRaises(ValueError):analyze(fixture(mode='ground'),ground_contacts=labels)

    def test_handheld_disables_release_promotion_links_and_outcome_classification(self):
        events,_,d=analyze(fixture(),camera='handheld')
        self.assertTrue(events)
        self.assertTrue(all(e['predicted_outcome']=='uncertain' and e['episode_kind']=='flight_motion_candidate' for e in events))
        self.assertEqual(d['identity_links'],[])

    def test_unique_colour_and_geometry_continue_fragmented_id_without_filling_gap(self):
        data=fixture(fragment=12,missing=range(9,12))
        appearances={(8,'disc-001'):[1.,0.],(12,'disc-002'):[1.,0.]}
        events,ledger,d=analyze(data,appearances=appearances)
        self.assertEqual(d['metrics']['accepted_identity_links'],1)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['disc_ids'],['disc-001','disc-002'])
        for i in (9,10,11):
            self.assertEqual(ledger[i]['events'][0]['phase'],'unobserved')
            self.assertFalse(ledger[i]['events'][0]['disc_observed'])

    def test_ambiguous_colour_match_is_not_forced(self):
        data=fixture(fragment=12,missing=range(9,12))
        points=observed_points(*data)
        points['disc-003']=[dict(p,disc_id='disc-003') for p in points['disc-002']]
        proposals=link_proposals(points,1000,600,'tripod')
        self.assertEqual(len(proposals),2)
        features={(8,'disc-001'):[1.,0.],(12,'disc-002'):[1.,0.],(12,'disc-003'):[1.,0.]}
        links=resolve_links(proposals,features)
        self.assertFalse(any(p['accepted'] for p in links))
        self.assertTrue(all(p['reason']=='ambiguous_continuation' for p in links))

    def test_missing_colour_mismatched_colour_or_long_gap_prevents_identity_join(self):
        data=fixture(fragment=12,missing=range(9,12))
        _,_,none=analyze(data)
        self.assertEqual(none['metrics']['accepted_identity_links'],0)
        _,_,mismatch=analyze(data,appearances={(8,'disc-001'):[1.,0.],(12,'disc-002'):[0.,1.]})
        self.assertEqual(mismatch['metrics']['accepted_identity_links'],0)
        points=observed_points(*fixture(fragment=22,missing=range(9,22)))
        self.assertEqual(link_proposals(points,1000,600,'tripod'),[])

    def test_multiple_motion_groups_before_contact_merge_into_one_episode(self):
        data=fixture()
        for i in range(10,13):data[0][i]['discs'][0]['moving']=False
        events,_,d=analyze(data)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['motion_segments'],2)
        self.assertEqual(d['metrics']['motion_segments_attached'],1)

    def test_new_person_departure_can_start_second_episode_for_same_disc_id(self):
        data=fixture(count=125)
        for i,(r,det) in enumerate(zip(*data)):
            t=r['t_sec']
            if t<2.:continue
            relative=max(0,t-2.2)
            x=50+450*relative if relative<.8 else 410+(relative-.8)*100
            dog_x=400 if relative<.8 else 400+(relative-.8)*100
            r['dog']['bbox']=[dog_x,170.,dog_x+70.,280.]
            r['discs'][0].update(bbox=[x,200.,x+20.,210.],moving=2.2<=t<3.,approaching=2.2<=t<3.)
        events,ledger,_=analyze(data)
        self.assertEqual(len(events),2)
        self.assertTrue(all(e['release_evidence'] for e in events))
        self.assertLess(events[0]['end_frame'],events[1]['start_frame'])
        self.assertEqual({e['disc_ids'][0] for e in events},{'disc-001'})

    def test_true_times_are_preserved_for_nonuniform_frame_intervals(self):
        data=fixture()
        for i,(r,d) in enumerate(zip(*data)):
            now=i*.04+(i%2)*.005
            for v in (r,d):v.update(t_sec=now,pts_sec=2+now)
        events,ledger,_=analyze(data)
        self.assertTrue(events)
        self.assertEqual([r['t_sec'] for r in ledger],[r['t_sec'] for r in data[0]])
        self.assertEqual(events[0]['start_sec'],data[0][events[0]['start_frame']]['t_sec'])

    def test_bad_time_observation_or_settings_are_rejected(self):
        data=fixture();data[1][2]['t_sec']+=.1
        with self.assertRaises(ValueError):analyze(data)
        data=fixture();data[0][2]['discs'][0]['state']='predicted'
        with self.assertRaises(ValueError):analyze(data)
        for options in ({'min_carry_sec':float('nan')},{'identity_link_sec':.01},{'appearance_similarity':1.1}):
            with self.assertRaises(ValueError):EventSettings(**options)

    def test_ground_file_cannot_claim_wrong_source_or_missing_measurement(self):
        data=fixture();points=observed_points(*data)
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'ground.json';v={'id':'test','source_sha256':'original'}
            write_json(p,{'video_id':'wrong','source_sha256':'original','ground_contacts':[]})
            with self.assertRaisesRegex(ValueError,'source mismatch'):validate_ground(p,v,points)
            write_json(p,{'video_id':'test','source_sha256':'original','ground_contacts':[{'disc_id':'disc-001','frame_id':999,'verified':True,'reviewer':'Reviewer'}]})
            with self.assertRaisesRegex(ValueError,'measured disc'):validate_ground(p,v,points)

    def test_native_crop_mapping_and_colour_descriptor(self):
        self.assertEqual(crop_bounds([10.,20.,30.,40.],100,100,.25),[5,15,35,45])
        crop=np.zeros((10,20,3),dtype=np.uint8);crop[:]=[220,140,40]
        colour=colour_feature(crop)
        self.assertAlmostEqual(sum(colour),1.)
        self.assertEqual(len(colour),192)
        with self.assertRaises(ValueError):crop_bounds([-1,2,3,4],100,100)


class EventMediaTests(unittest.TestCase):
    def test_complete_real_source_pipeline_crops_cache_and_prior_artifacts_unchanged(self):
        tools=Toolchain.discover()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=root/'raw';raw.mkdir();pack=root/'pack';pack.mkdir();joint=root/'joint';joint.mkdir()
            source=raw/'sample.mkv'
            subprocess.run([tools.ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=size=1000x600:rate=25:duration=3',
                            '-c:v','ffv1',str(source)],capture_output=True,check=True)
            metadata,records,_=scan_video(source,tools)
            frames,dets=fixture(len(records))
            for row,det,record in zip(frames,dets,records):row.update(record);det.update(record)
            v={'id':'test','source':str(source),'source_sha256':sha256(source),'status':'complete','role':'action','camera':'tripod',
               'width':1000,'height':600,'frames_count':len(records),'duration':metadata['duration'],'paths':{'frame_index':'frames.json'},'metadata':metadata}
            write_json(pack/'manifest.json',{'videos':[v]});write_json(pack/'frames.json',records)
            detector=root/'detections.jsonl';detector.write_text(''.join(json.dumps(d)+'\n' for d in dets))
            write_json(detector.with_suffix('.json'),{'status':'complete','source':str(source),'source_sha256':v['source_sha256'],'video_id':'test',
                'first_frame':records[0],'last_frame':records[-1],'counts':{'processed_frames':len(records),'dog_frames':0,'disc_frames':0,'person_frames':len(records)}})
            tracker=root/'tracking-summary.json';write_json(tracker,{'provenance':{'detections_sha256':sha256(detector)}})
            states=joint/'joint-states.jsonl';states.write_text(''.join(json.dumps(f)+'\n' for f in frames))
            write_json(joint/'summary.json',{'status':'complete','video_id':'test','metrics':{'processed_frames':len(records)},
                'artifact_sha256':{'joint-states.jsonl':sha256(states)},'provenance':{'source_sha256':v['source_sha256'],
                    'inputs':{str(tracker):sha256(tracker)}}})
            preview=root/'preview.mp4';preview.write_bytes(b'preview fixture bytes; not played in this integration test')
            write_json(preview.with_suffix('.json'),{'status':'complete','signature':{'source_sha256':v['source_sha256'],'source_frames':len(records)},'sha256':sha256(preview)})
            before={str(p):sha256(p) for p in (source,states,joint/'summary.json',detector,tracker)}
            args=(joint,detector,pack,root/'events',preview)
            summary=run(*args,ffmpeg_dir=Path(tools.ffmpeg).parent)
            self.assertEqual(summary['processed_frames'],75)
            self.assertEqual(summary['episode_candidates'],1)
            self.assertEqual(summary['outcome_candidates'],{'catch_candidate':1})
            self.assertGreater(summary['contact_crop_frames'],0)
            index=json.loads((args[3]/'crop-index.json').read_text())['contact_images']
            self.assertLessEqual(len(index),8)
            for p in index:
                image=cv2.imread(str(args[3]/p['file']))
                self.assertEqual(list(image.shape[:2][::-1]),p['crop_size'])
                self.assertEqual(p['crop_xyxy'][2]-p['crop_xyxy'][0],p['crop_size'][0])
                self.assertTrue((args[3]/p['parent_file']).is_file())
            self.assertEqual(before,{p:sha256(p) for p in before})
            fragmented,fragment_det=fixture(fragment=12,missing=range(9,12))
            for row,det,record in zip(fragmented,fragment_det,records):row.update(record);det.update(record)
            points=observed_points(fragmented,fragment_det)
            proposals=link_proposals(points,1000,600,'tripod')
            link_temp=root/'endpoint-test';link_temp.mkdir()
            features,link_index=make_link_features(v,records,points,proposals,tools,link_temp)
            self.assertEqual(set(features),{(8,'disc-001'),(12,'disc-002')})
            self.assertEqual(len(link_index),2)
            for item in link_index:
                self.assertEqual(item['pts_sec'],records[item['frame_id']]['pts_sec'])
                image=cv2.imread(str(link_temp/item['file']))
                self.assertEqual(image.shape[:2],(10,20))
            self.assertEqual(summary['cache_key'],run(*args,ffmpeg_dir=Path(tools.ffmpeg).parent)['cache_key'])
            (args[3]/'events-v2.json').write_text('edited')
            with self.assertRaisesRegex(ValueError,'cache modified'):run(*args,ffmpeg_dir=Path(tools.ffmpeg).parent)
            with self.assertRaisesRegex(ValueError,'independent event'):run(joint,detector,pack,joint/'new',preview,ffmpeg_dir=Path(tools.ffmpeg).parent)


if __name__=='__main__':unittest.main()
