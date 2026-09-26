"""Run with python -m app.vision from backend/."""

import argparse
import json
import logging
import math
from pathlib import Path
import time

import cv2

from app.config import load_vision_config
from app.vision.capture import VideoSource
from app.vision.localization import ArucoTracker


def main():
    parser = argparse.ArgumentParser(description='Standalone overhead ArUco tracking')
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument('--video', help='Prerecorded video path')
    sources.add_argument('--camera', type=int, help='Live camera index (e.g. 0 or 1)')
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[2] / 'vision_config.json')
    parser.add_argument('--no-display', action='store_true', help='JSON output only; Ctrl-C to quit')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        tracker = ArucoTracker(load_vision_config(args.config))
        with VideoSource(args.camera if args.camera is not None else args.video) as source:
            fps = source.capture.get(cv2.CAP_PROP_FPS)
            delay = 1 / fps if math.isfinite(fps) and fps > 0 else 1 / 30
            if not args.no_display:
                cv2.namedWindow('Overhead tracking', cv2.WINDOW_NORMAL)
            while True:
                started = time.monotonic()
                running, frame = source.read()
                if not running:
                    logging.info('Video ended')
                    break
                if frame is not None:
                    poses, events = tracker.process(frame, draw=not args.no_display)
                    print(json.dumps({'poses': [p.to_dict() for p in poses],
                                      'events': [e.to_dict() for e in events]}), flush=True)
                    if not args.no_display:
                        cv2.imshow('Overhead tracking', frame)
                wait = .1 if frame is None else (0 if source.live else delay - (time.monotonic() - started))
                if args.no_display:
                    time.sleep(max(0, wait))
                elif cv2.waitKey(max(1, int(wait * 1000))) & 0xFF == ord('q'):
                    break
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, cv2.error) as error:
        logging.error('%s', error)
        return 1
    finally:
        if not args.no_display:
            cv2.destroyAllWindows()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
