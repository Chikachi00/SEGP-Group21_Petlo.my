"""Run the precise local video packet tools from the existing CV module."""
if __package__:
    from .video_tools.cli import main
else:
    from video_tools.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
