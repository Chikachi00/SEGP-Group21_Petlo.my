"""Independent offline throw-episode analysis, bounded identity links and crop audit."""
if __package__:
    from .analyze_throw_events import (
        PROJECT, crop_bounds, colour_feature, validate_joint, validate_ground,
        make_link_features, make_contact_crops, _run_analysis,
        review_page as _review_page, main as _main,
    )
    from .throw_events_v3 import EventSettings, observed_points, link_proposals, analyze_events
else:
    from analyze_throw_events import (
        PROJECT, crop_bounds, colour_feature, validate_joint, validate_ground,
        make_link_features, make_contact_crops, _run_analysis,
        review_page as _review_page, main as _main,
    )
    from throw_events_v3 import EventSettings, observed_points, link_proposals, analyze_events


def run(joint_dir,detections,pack,output_dir,preview=None,settings=None,ground_path=None,ffmpeg_dir=None,*,review=True):
    return _run_analysis(joint_dir,detections,pack,output_dir,preview,settings,ground_path,ffmpeg_dir,
                         analyzer=analyze_events,version=3,review=review)


def review_page(video,frames,ledger,events,crops,preview,output):
    return _review_page(video,frames,ledger,events,crops,preview,output,version=3)


def main():
    _main(runner=run,description=__doc__)


if __name__=='__main__':main()
