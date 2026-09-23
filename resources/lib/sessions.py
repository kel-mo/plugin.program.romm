# -*- coding: utf-8 -*-
"""Play-session reporting: heartbeat while a game runs, queue and ingest sessions afterwards."""
import time
import traceback
from datetime import datetime, timezone

import xbmc

from . import device, kodi
from .api import ApiError, RommClient

QUEUE = 'play-sessions.json'
HEARTBEAT_EVERY = 30
BATCH = 100
MAX_ATTEMPTS = 5
FAILED = object()


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class PlayTracker:
    """Driven by service.py: start(rom_id) when a cached game starts, tick() every ~30 s,
    stop() when playback ends. Queues sessions in profile play-sessions.json and flushes
    them with client.ingest_play_sessions(); sessions shorter than MIN_SECONDS are dropped."""

    MIN_SECONDS = 60

    def __init__(self, client=None):
        self.fixed_client = client          # None: fresh RommClient per call, settings may change
        self.rom_id = None
        self.started = None
        self.last_beat = 0
        self.path = kodi.profile_file(QUEUE)
        self.queue = kodi.read_json(self.path) or []

    def _client(self):
        return self.fixed_client or RommClient()

    def _save(self):
        kodi.write_json(self.path, self.queue)

    def _call(self, what, fn):
        """fn(client, device_id); returns FAILED instead of raising."""
        client = self._client()
        try:
            return device.with_device(client, lambda device_id: fn(client, device_id))
        except ApiError as e:
            kodi.log('{} failed: {}'.format(what, e), xbmc.LOGWARNING)
        except Exception:
            kodi.log('{} failed: {}'.format(what, traceback.format_exc()), xbmc.LOGERROR)
        return FAILED

    def start(self, rom_id):
        rom_id = int(rom_id)
        if self.rom_id == rom_id:
            return
        if self.rom_id is not None:
            self.stop()
        self.rom_id = rom_id
        self.started = _now()
        self.last_beat = 0
        self.tick()

    def tick(self):
        if self.rom_id is None or not kodi.setting_bool('report_play'):
            return
        now = time.time()
        if now - self.last_beat < HEARTBEAT_EVERY:
            return
        self.last_beat = now
        rom_id = self.rom_id
        self._call('heartbeat', lambda c, d: c.heartbeat_playing(rom_id, d))

    def stop(self):
        if self.rom_id is None:
            return
        rom_id, started, ended = self.rom_id, self.started, _now()
        self.rom_id = self.started = None
        if not kodi.setting_bool('report_play'):
            return
        duration = ended - started
        if duration.total_seconds() >= self.MIN_SECONDS:
            self.queue.append({'rom_id': rom_id, 'save_slot': 'autosave', 'start_time': _iso(started),
                               'end_time': _iso(ended), 'duration_ms': int(duration.total_seconds() * 1000),
                               'attempts': 0})
            self._save()
        self._call('heartbeat clear', lambda c, d: c.heartbeat_clear(d))
        self.flush()

    def flush(self):
        if not self.queue or not kodi.setting_bool('report_play'):
            return
        pending, keep = self.queue, []
        for i in range(0, len(pending), BATCH):
            batch = pending[i:i + BATCH]
            wire = [{k: v for k, v in s.items() if k != 'attempts'} for s in batch]
            result = self._call('play session upload', lambda c, d: c.ingest_play_sessions(d, wire))
            if result is FAILED:                    # server unreachable: keep the rest for later
                keep.extend(pending[i:])
                break
            status = {r.get('index'): r for r in (result or {}).get('results') or []}
            for n, s in enumerate(batch):
                r = status.get(n) or {}
                if r.get('status') in ('created', 'duplicate'):
                    continue
                s['attempts'] = s.get('attempts', 0) + 1
                if s['attempts'] >= MAX_ATTEMPTS:
                    kodi.log('dropping play session {} after {} attempts: {}'.format(
                        s, s['attempts'], r.get('detail')), xbmc.LOGWARNING)
                else:
                    keep.append(s)
        self.queue = keep
        self._save()
