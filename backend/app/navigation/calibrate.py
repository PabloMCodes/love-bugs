"""Draw traffic geometry on a frozen camera image before starting navigation.

No BLE connections or backend calls are made by this setup tool.
"""
import argparse
from dataclasses import asdict, replace
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import time

import cv2

from app.navigation.traffic import DEFAULT_TRAFFIC_CONFIG, TrafficConfig
from app.vision.capture import VideoSource

WINDOW = 'Traffic setup'


def rectangle(start, end, width, height):
    x1, x2 = sorted(max(0, min(width, int(p[0]))) for p in (start, end))
    y1, y2 = sorted(max(0, min(height, int(p[1]))) for p in (start, end))
    if x2-x1 < 3 or y2-y1 < 3:
        raise ValueError('Drag a larger box')
    return [x1, y1, x2, y2]


def footprint_radius(box, marker):
    x1, y1, x2, y2 = box
    if not (x1 <= marker[0] <= x2 and y1 <= marker[1] <= y2):
        raise ValueError('Click the marker center inside the robot body box')
    return math.ceil(max(math.hypot(x-marker[0], y-marker[1])
                         for x in (x1, x2) for y in (y1, y2)))


class Editor:
    def __init__(self, config, width, height):
        changed = (width, height) != (config.frame_width, config.frame_height)
        self.config = replace(config, calibrated=False, frame_width=width, frame_height=height,
                              arena=[0, 0, width, height] if changed else config.arena.copy(),
                              obstacles=[] if changed else [box.copy() for box in config.obstacles],
                              radii=config.radii.copy())
        self.mode = 'building'
        self.start = self.cursor = None
        self.body = None
        self.footprints = {}
        self.message = ('Resolution changed: redraw arena/buildings and measure BOTH robots' if changed
                        else 'Drag boxes around buildings, including overhangs')

    def select(self, mode):
        self.mode, self.start, self.body = mode, None, None
        self.message = ('Drag around the ENTIRE robot, then click its marker center'
                        if mode.startswith('robot-') else 'Drag the ' + mode + ' rectangle')

    def mouse(self, event, x, y, _flags, _data):
        self.cursor = (x, y)
        try:
            if self.body is not None and event == cv2.EVENT_LBUTTONDOWN:
                radius = footprint_radius(self.body, (x, y))
                self.config.radii[self.mode] = radius
                self.footprints[self.mode] = ((x,y), radius, self.body)
                self.body = None
                self.message = f'{self.mode}: turning radius {radius}px + margin {self.config.margin}px'
                return
            if self.body is not None:
                return
            if event == cv2.EVENT_LBUTTONDOWN:
                self.start = (x,y)
            elif event == cv2.EVENT_LBUTTONUP and self.start is not None:
                start, self.start = self.start, None
                box = rectangle(start, (x,y), self.config.frame_width, self.config.frame_height)
                if self.mode == 'building':
                    self.config.obstacles.append(box)
                    self.message = f'{len(self.config.obstacles)} buildings; U undoes the last building'
                elif self.mode == 'arena':
                    self.config.arena = box
                    self.message = 'Arena updated'
                else:
                    self.body = box
                    self.message = 'Now CLICK this robot marker center'
        except ValueError as error:
            self.message = str(error)

    def save(self, path, original):
        if self.start is not None or self.body is not None:
            raise ValueError('Finish or cancel the current selection before saving')
        # Validate a fresh object and never silently enable physical movement.
        config = TrafficConfig(**asdict(self.config))
        current = path.read_bytes() if path.exists() else None
        if current != original:
            raise ValueError('Config changed on disk; quit and reopen to preserve those edits')
        payload = (json.dumps(asdict(config), indent=2)+'\n').encode()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
                temporary = Path(out.name)
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
            temporary.replace(path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        self.message = 'Saved. Review speed/margin, then set calibrated=true before phase 3/4'
        return payload

    def draw(self, frame):
        display = frame.copy()
        for index, box in enumerate([self.config.arena, *self.config.obstacles]):
            color = (0,255,255) if index == 0 else (0,80,255)
            cv2.rectangle(display, tuple(map(int, box[:2])), tuple(map(int, box[2:])), color, 2)
            cv2.putText(display, 'Arena' if index == 0 else f'Building {index}',
                        (int(box[0])+4,int(box[1])+20), cv2.FONT_HERSHEY_SIMPLEX, .5, color, 1)
        for center, radius, box in self.footprints.values():
            cv2.rectangle(display, tuple(map(int, box[:2])), tuple(map(int, box[2:])), (255,200,0), 2)
            cv2.circle(display, center, radius, (255,200,0), 2)
            cv2.circle(display, center, math.ceil(radius+self.config.margin), (0,0,255), 1)
            cv2.circle(display, center, 4, (255,255,255), -1)
        if self.body:
            cv2.rectangle(display, tuple(self.body[:2]), tuple(self.body[2:]), (255,200,0), 2)
        if self.start and self.cursor:
            cv2.rectangle(display, self.start, self.cursor, (255,255,255), 1)
        lines = ['FROZEN IMAGE | A arena | B buildings | W WALL-Y body | E Eeva body',
                 'U undo building | S save | Q quit | choose a mode to cancel a selection',
                 f'Mode: {self.mode} | {self.message}']
        for index, text in enumerate(lines):
            position = (10,22+index*25)
            cv2.putText(display,text,position,cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),3)
            cv2.putText(display,text,position,cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1)
        return display


def run(source, path):
    original = path.read_bytes() if path.exists() else None
    config = TrafficConfig(**json.loads(original)) if original is not None else TrafficConfig()
    cv2.namedWindow(WINDOW, cv2.WINDOW_AUTOSIZE)
    try:
        # Freeze deliberately, after the camera exposure has settled. Release the
        # source before editing; this tool cannot issue any motor commands.
        with VideoSource(source) as camera:
            while True:
                running, frame = camera.read()
                if not running:
                    raise ValueError('Video ended before an image was selected')
                if frame is not None:
                    display = frame.copy()
                    cv2.putText(display, 'SPACE freeze for setup | Q quit', (10,25),
                                cv2.FONT_HERSHEY_SIMPLEX,.7,(0,255,255),2)
                    cv2.imshow(WINDOW,display)
                key = cv2.waitKey(1) & 0xff
                if key in (ord('q'),ord('Q')) or cv2.getWindowProperty(WINDOW,cv2.WND_PROP_VISIBLE)<1:
                    return
                if key == ord(' ') and frame is not None:
                    break
                time.sleep(.02)
        editor = Editor(config, frame.shape[1], frame.shape[0])
        cv2.setMouseCallback(WINDOW,editor.mouse)
        while True:
            cv2.imshow(WINDOW,editor.draw(frame))
            key = cv2.waitKey(20) & 0xff
            if ord('A') <= key <= ord('Z'):
                key += ord('a') - ord('A')
            if key in (ord('q'),ord('Q')) or cv2.getWindowProperty(WINDOW,cv2.WND_PROP_VISIBLE)<1:
                return
            mode = {ord('a'):'arena',ord('b'):'building',ord('w'):'robot-a',ord('e'):'robot-b'}.get(key)
            if mode:
                editor.select(mode)
            elif key == ord('u') and editor.config.obstacles:
                editor.config.obstacles.pop()
                editor.message = 'Last building removed'
            elif key == ord('s'):
                try:
                    original = editor.save(path,original)
                    logging.info('Saved traffic geometry to %s (calibrated=false)', path)
                except (ValueError, OSError) as error:
                    editor.message = str(error)
    finally:
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--camera',type=int,default=0)
    source.add_argument('--video')
    parser.add_argument('--config',type=Path,default=DEFAULT_TRAFFIC_CONFIG)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(levelname)s: %(message)s')
    try:
        run(args.video if args.video else args.camera,args.config)
    except KeyboardInterrupt:
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        logging.error('%s',error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
