"""Occasional two-line social exchanges; never submit or modify robot tasks."""

import asyncio
import logging
import time

from app.agents.planner import Decision

logger = logging.getLogger(__name__)


class BanterCoordinator:
    def __init__(self, planner, chat, *, clock=time.monotonic,
                 quiet_seconds=12, cooldown=35, reply_delay=4):
        self.planner, self.chat, self.clock = planner, chat, clock
        self.quiet_seconds, self.cooldown, self.reply_delay = quiet_seconds, cooldown, reply_delay
        self.session = None
        self.revision = None
        self.last_speech = clock()
        self.next_exchange = clock()
        self.exchange = 0
        self.reply = None
        self.pending = None
        self.pending_info = None

    async def close(self):
        if self.pending:
            self.pending.cancel()
            await asyncio.gather(self.pending, return_exceptions=True)
        self.pending = None
        self.reply = None

    async def tick(self, world, *, task_activity=False):
        now = self.clock()
        if world['session_id'] != self.session:
            await self.close()
            self.session = world['session_id']
            self.exchange = 0
            self.last_speech = self.next_exchange = now
            self.revision = self.chat.revision
        healthy = [r for r in world['robots'] if r['physical']['online']
                   and not r['physical']['stopped'] and not r['physical']['blocked']
                   and r['physical']['tracking'] == 'TRACKED' and r['physical'].get('pose') is not None]
        if world['game']['status'] != 'RUNNING' or len(healthy) < 2 or not hasattr(self.planner, 'converse'):
            await self.close()
            self.last_speech = now
            return
        if self.chat.revision != self.revision:
            # Work communication and new assignments always win over small talk.
            await self.close()
            self.last_speech = now
            self.revision = self.chat.revision
            return
        if task_activity:
            await self.close()
            return
        if self.pending:
            if not self.pending.done():
                return
            speaker, is_reply, topic, peer = self.pending_info
            try:
                message = self.pending.result()
            except (Exception, asyncio.CancelledError) as error:
                logger.warning('Banter skipped (%s)', type(error).__name__)
                message = None
            self.pending = None
            if message and message.strip():
                decision = Decision(action='WAIT', reason='Social conversation only', message=message)
                before = self.chat.revision
                self.chat.publish(world, speaker, decision, status='conversation', kind='banter')
                if self.chat.revision != before:
                    self.revision = self.chat.revision
                    self.last_speech = now
                    if not is_reply:
                        self.reply = (peer, message, topic, now + self.reply_delay)
            return
        if self.reply:
            speaker, opener, topic, due = self.reply
            if now < due:
                return
            self.reply = None
            peer = None
            is_reply = True
        else:
            if now < self.next_exchange or now - self.last_speech < self.quiet_seconds:
                return
            index = self.exchange % 2
            speaker, peer = healthy[index]['id'], healthy[1 - index]['id']
            opener, topic, is_reply = None, self.exchange, False
            self.exchange += 1
            self.next_exchange = now + self.cooldown
        self.pending_info = (speaker, is_reply, topic, peer)
        # Generation runs separately so a slow joke cannot block task planning.
        self.pending = asyncio.create_task(asyncio.wait_for(
            self.planner.converse(self.chat.context(world), speaker, opener, topic), timeout=8))
