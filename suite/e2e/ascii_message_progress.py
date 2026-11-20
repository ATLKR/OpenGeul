"""Finite read-only ASCII queue evidence, separate from semantic insertion.

GetMsgProc reports queue retrieval, including LibreOffice's internal CHAR peeks.
No dispatch-return, document change or unique SendInput attribution is inferred.
"""
from __future__ import annotations

import copy


MAX_CHARACTER_EVENTS = 32
MAX_SESSION_EVENTS = 4096
US_LAYOUT = 0x04090409
FIELDS = ('sequence', 'actionEpoch', 'origin', 'remove', 'message', 'pid', 'tid',
          'hwnd', 'layout', 'wParam', 'lParam', 'messageTime', 'extraInfo',
          'nativeTick', 'shiftState', 'controlState', 'altState', 'capsState', 'flags')


def _integer(value, low, high):
    assert type(value) is int and low <= value <= high, 'Untyped or out-of-range queue evidence'
    return value


class CharacterProgress:
    """A single armed character, never a parser, input sender or retry loop."""
    def __init__(self, action, target, baseline_sequence):
        self.action = copy.deepcopy(action)
        self.target = dict(target)
        self.baseline = _integer(baseline_sequence, 0, MAX_SESSION_EVENTS - 1)
        self.sequence = self.baseline
        self.index = _integer(action['index'], 0, 255)
        char = action['character']
        assert type(char) is str and len(char) == 1 and char.isascii(), 'Unknown ASCII character intent'
        if char.isalpha() or char.isdigit(): self.main_vk = ord(char.upper())
        else:
            assert char in ('-', ' ', ':'), 'Unknown ASCII character intent'
            self.main_vk = {'-': 0xbd, ' ': 0x20, ':': 0xba}[char]
        events = action['events']
        assert type(events) is list and len(events) in (2, 4), 'Unknown ASCII key event intent'
        assert all(type(event) is dict and event.get('vk') == 0
                   and type(event.get('scan')) is int and 0 < event['scan'] < 128
                   and type(event.get('flags')) is int and event['flags'] in (8, 10)
                   for event in events), 'Unknown ASCII key event intent'
        half = len(events) // 2
        assert all(event['flags'] == 8 for event in events[:half])
        assert events[half:] == [dict(event, flags=10) for event in reversed(events[:half])]
        assert (half == 2) == (char.isupper() or char == ':'), 'ASCII Shift intent differs'
        if half == 2: assert events[0]['scan'] == 0x2a, 'ASCII Shift scan differs'
        self.main_scan = events[half - 1]['scan']
        assert self.main_scan != 0x2a
        for name in ('pid', 'tid'): _integer(target[name], 1, 0xffffffff)
        _integer(target['hwnd'], 1, 0xffffffffffffffff)
        assert target['layout'] == US_LAYOUT, 'ASCII target has a different HKL'
        self.events = []
        self.key_index = 0
        self.character_sequence = None
        self.main_down_sequence = None
        self.complete = False
        self.failed = False

    def observe(self, rows):
        assert not self.failed, 'ASCII character progress already failed'
        try:
            return self._observe(rows)
        except BaseException:
            self.failed = True
            raise

    def _observe(self, rows):
        assert not self.complete, 'ASCII character progress already completed'
        assert type(rows) is list and len(self.events) + len(rows) <= MAX_CHARACTER_EVENTS, 'ASCII character observation bound exceeded'
        for raw in rows:
            assert type(raw) is dict and all(name in raw for name in FIELDS), 'Incomplete queue observation'
            row = {name: raw[name] for name in FIELDS}
            for name in FIELDS:
                _integer(row[name], -32768 if name.endswith('State') else 0,
                         32767 if name.endswith('State') else 0xffffffffffffffff)
            assert row['sequence'] == self.sequence + 1 <= MAX_SESSION_EVENTS, 'Queue sequence is noncontiguous or replayed'
            assert row['actionEpoch'] == self.index + 1, 'Queue action epoch changed'
            assert all(row[key] == self.target[key] for key in ('pid', 'tid', 'hwnd', 'layout')), 'Queue native target changed'
            # PeekMessage permits PM_NOYIELD(2) with PM_NOREMOVE(0) or
            # PM_REMOVE(1). Preserve the raw hook value; only bit0 consumes.
            assert row['origin'] == 1 and row['remove'] & ~0x3 == 0 and row['flags'] == 0, 'Unknown queue source flags'
            consumed = bool(row['remove'] & 0x1)
            assert row['messageTime'] <= 0xffffffff, 'Invalid native message time'
            assert row['message'] in (0x100, 0x101, 0x102), 'Unexpected system or keyboard message'
            if row['message'] == 0x102:
                assert row['wParam'] == ord(self.action['character']), 'Observed ASCII character differs'
                if consumed:
                    assert self.character_sequence is None, 'Duplicate consumed ASCII character'
                    assert self.main_down_sequence is not None, 'ASCII character preceded its keydown'
                    self.character_sequence = row['sequence']
            else:
                assert self.key_index < len(self.action['events']), 'Extra ASCII key message'
                expected = self.action['events'][self.key_index]
                up = bool(expected['flags'] & 2)
                flags = row['lParam'] & 0xffffffff
                assert row['message'] == (0x101 if up else 0x100), 'ASCII key order changed'
                assert row['wParam'] == (0x10 if expected['scan'] == 0x2a else self.main_vk), 'ASCII key VK differs'
                assert flags & 0xffff == 1 and (flags >> 16) & 0xff == expected['scan'], 'ASCII key scan or repeat differs'
                assert flags & (1 << 24 | 1 << 29) == 0, 'ASCII key is extended or a system key'
                assert (flags >> 30) & 3 == (3 if up else 0), 'ASCII key transition flags differ'
                if consumed:
                    if not up and expected['scan'] == self.main_scan:
                        self.main_down_sequence = row['sequence']
                    self.key_index += 1
            self.sequence = row['sequence']
            self.events.append(row)
        if self.key_index == len(self.action['events']) and self.character_sequence is not None:
            self.complete = True
            return dict(queueConsumed=True, semanticInsertionProved=False,
                        baselineSequence=self.baseline, finalSequence=self.sequence,
                        characterSequence=self.character_sequence,
                        attribution='bounded target/epoch/scan/text correlation; original INPUT extraInfo0 is not a unique tag',
                        events=copy.deepcopy(self.events))
        return None
