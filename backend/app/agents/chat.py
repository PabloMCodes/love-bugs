"""Bounded public robot conversation shared by planners and spectators."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4


class AgentChat:
    def __init__(self):
        self.session_id = None
        self.messages = []
        self.revision = 0

    def reset(self, session_id):
        if session_id != self.session_id:
            self.session_id = session_id
            self.messages = []
            self.revision += 1

    def context(self, world):
        self.reset(world['session_id'])
        snapshot = deepcopy(world)
        snapshot['agent_messages'] = deepcopy(self.messages[-20:])
        return snapshot

    def publish(self, world, robot_id, decision, *, status):
        self.reset(world['session_id'])
        if not decision.message:
            return
        robot = next(robot for robot in world['robots'] if robot['id'] == robot_id)
        self.messages.append({
            'id': uuid4().hex,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'robot_id': robot_id,
            'name': robot.get('name', robot_id),
            'text': decision.message,
            'action': decision.action,
            'location': decision.location,
            'status': status,
        })
        self.messages = self.messages[-100:]
        self.revision += 1

    def snapshot(self):
        return {'session_id': self.session_id, 'revision': self.revision,
                'messages': deepcopy(self.messages)}
