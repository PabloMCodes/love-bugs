"""Bounded public robot conversation shared by planners and spectators."""

from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import re
from uuid import uuid4


def conversation_focus(world, robot_id):
    """Bounded, factual context; public speech is not evidence of task completion."""
    messages = world.get('agent_messages', [])[-20:]
    own = [m for m in messages if m.get('robot_id') == robot_id]
    last_own = next((i for i in range(len(messages) - 1, -1, -1)
                     if messages[i].get('robot_id') == robot_id), -1)
    return {
        'your_recent_messages': own[-4:],
        'peer_messages_since_your_last_public_message': [
            m for m in messages[last_own + 1:] if m.get('robot_id') != robot_id
        ],
        'recent_confirmed_events': [
            {key: event[key] for key in ('type', 'robot_id', 'task_id', 'message', 'timestamp')
             if key in event}
            for event in world.get('events', [])[-10:]
        ],
    }


def normalized_message(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


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
        parameters = ({'item': decision.item, 'quantity': decision.quantity}
                      if decision.action in ('BUY', 'SELL') else {})
        text = normalized_message(decision.message)
        own = [m for m in self.messages if m['robot_id'] == robot_id][-6:]
        for previous in own:
            if (previous['action'], previous['location'], previous['parameters'], previous['status']) != (
                decision.action, decision.location, parameters, status
            ):
                continue
            if SequenceMatcher(None, normalized_message(previous['text']), text).ratio() >= .9:
                return  # Silence repeated speech, never reject the associated task.
        robot = next(robot for robot in world['robots'] if robot['id'] == robot_id)
        self.messages.append({
            'id': uuid4().hex,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'robot_id': robot_id,
            'name': robot.get('name', robot_id),
            'text': decision.message,
            'action': decision.action,
            'location': decision.location,
            'parameters': parameters,
            'status': status,
        })
        self.messages = self.messages[-100:]
        self.revision += 1

    def snapshot(self):
        return {'session_id': self.session_id, 'revision': self.revision,
                'messages': deepcopy(self.messages)}
