"""Luigi's Balloon World flow/message replacement, on synthetic files only."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_odyssey_aspect as common
import prepare_odyssey_balloon as balloon
import prepare_odyssey_phone as phone

VOICE = struct.pack('<4H', 0x0E, 4, 0, 16) + struct.pack('<H', 14) + 'Talk025'.encode('utf-16-le')


def byml(root) -> bytes:
    """Minimal little-endian BYML v3 writer: dict, list, str, int, bool, None."""
    keys, strings = set(), set()

    def collect(value):
        if isinstance(value, dict):
            keys.update(value)
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)
        elif isinstance(value, str):
            strings.add(value)
    collect(root)
    keys, strings = sorted(keys), sorted(strings)
    out = bytearray(16)

    def table(items):
        node = bytearray([0xC2]) + len(items).to_bytes(3, 'little')
        blob, offsets = bytearray(), []
        for item in items:
            offsets.append(4 + 4 * (len(items) + 1) + len(blob))
            blob += item.encode() + b'\0'
        offsets.append(4 + 4 * (len(items) + 1) + len(blob))
        node += b''.join(struct.pack('<I', o) for o in offsets) + blob
        return node + bytes(-len(node) % 4)

    def scalar(value):
        if isinstance(value, bool):
            return 0xD0, int(value)
        if isinstance(value, int):
            return 0xD1, value & 0xffffffff
        if isinstance(value, str):
            return 0xA0, strings.index(value)
        return 0xFF, 0

    def write(value):
        pos = len(out)
        if isinstance(value, dict):
            items = sorted(value.items(), key=lambda kv: keys.index(kv[0]))
            out.extend(bytes([0xC1]) + len(items).to_bytes(3, 'little') + bytes(8 * len(items)))
            for i, (k, v) in enumerate(items):
                kind, raw = (0xC1 if isinstance(v, dict) else 0xC0, write(v)) if isinstance(v, (dict, list)) else scalar(v)
                struct.pack_into('<I', out, pos + 4 + 8 * i, keys.index(k) | kind << 24)
                struct.pack_into('<I', out, pos + 8 + 8 * i, raw)
        else:
            n = len(value)
            base = pos + 4 + ((n + 3) & ~3)
            out.extend(bytes([0xC0]) + n.to_bytes(3, 'little') + bytes(base - pos - 4 + 4 * n))
            for i, v in enumerate(value):
                kind, raw = (0xC1 if isinstance(v, dict) else 0xC0, write(v)) if isinstance(v, (dict, list)) else scalar(v)
                out[pos + 4 + i] = kind
                struct.pack_into('<I', out, base + 4 * i, raw)
        return pos
    keys_at = len(out); out += table(keys)
    strings_at = len(out); out += table(strings)
    root_at = write(root)
    out[:16] = b'YB' + struct.pack('<HIII', 3, keys_at, strings_at, root_at)
    return bytes(out)


def message(label):
    return {'Text': {'MessageData': {'LabelName': label, 'MessageFileName': 'TimeBalloon', 'MessageType': 'SystemMessage'}}}


def flow(no_target=2, message_next=45):
    nodes = [
        {'Id': 71, 'Type': 'JudgeSavedCostume', 'Base': 'QueryJudge',
         'CaseEventList': [{'Index': 0, 'Name': 'Yes', 'NextId': 43}, {'Index': 1, 'Name': 'No', 'NextId': 43}]},
        {'Id': 43, 'Type': 'JudgeSeparatePlay', 'Base': 'QueryJudge',
         'CaseEventList': [{'Index': 0, 'Name': 'Yes', 'NextId': 44}, {'Index': 1, 'Name': 'No', 'NextId': no_target}]},
        {'Id': 44, 'Type': 'MessageTalk', 'NextId': message_next, 'Param': message('TimeBalloon_Separate')},
        {'Id': 45, 'Type': 'JumpEntry', 'JumpEntryName': 'TalkEnd'},
        {'Id': 2, 'Type': 'SelectYesNo', 'CaseEventList': [{'Index': 0, 'NextId': 21}, {'Index': 1, 'NextId': 45}]},
        {'Id': 21, 'Type': 'StartConnect', 'Base': 'Event'},
        {'Id': 7, 'Type': 'MessageTalk', 'NextId': 50, 'Param': message('TimeBalloon_End')},
        {'Id': 50, 'Type': 'CameraEnd', 'NextId': 8, 'Param': {'CameraName': 'Default'}},
        {'Id': 8, 'Type': 'EndTalk', 'Base': 'Event'},
    ]
    return byml({'EntryList': [{'Name': 'Talk', 'NodeId': 71}, {'Name': 'TalkEnd', 'NodeId': 7}], 'NodeList': nodes})


def msbt(messages) -> bytes:
    labels = bytearray(struct.pack('<III', 1, len(messages), 12))
    for i, (label, _) in enumerate(messages):
        labels += bytes([len(label)]) + label.encode() + struct.pack('<I', i)
    text = bytearray(struct.pack('<I', len(messages)))
    at = 4 + 4 * len(messages)
    for _, body in messages:
        text += struct.pack('<I', at)
        at += len(body)
    text += b''.join(body for _, body in messages)
    out = bytearray(b'MsgStdBn\xff\xfe\0\0\x01\x03' + struct.pack('<HHI', 2, 0, 0) + bytes(10))
    for tag, section in ((b'LBL1', labels), (b'TXT2', text)):
        out += tag + struct.pack('<I', len(section)) + bytes(8) + section
        out += b'\xab' * (-len(out) % 16)
    struct.pack_into('<I', out, 0x12, len(out))
    return bytes(out)


def sarc(members, alignment=0x80) -> bytes:
    names = bytearray()
    nodes = []
    for name, _ in members:
        nodes.append(len(names) // 4)
        names += name.encode() + b'\0'
        names += bytes(-len(names) % 4)
    header = 0x14 + 12 + 16 * len(members) + 8 + len(names)
    start = -(-header // alignment) * alignment
    data, ranges = bytearray(), []
    for _, body in members:
        data += bytes(-len(data) % alignment)
        ranges.append((len(data), len(data) + len(body)))
        data += body
    out = bytearray(b'SARC' + struct.pack('<H', 0x14) + b'\xff\xfe' + struct.pack('<IIHH', start + len(data), start, 0x100, 0))
    out += b'SFAT' + struct.pack('<HHI', 12, len(members), 0x65)
    for i, (lo, hi) in enumerate(ranges):
        out += struct.pack('<4I', i, 0x01000000 | nodes[i], lo, hi)
    out += b'SFNT' + struct.pack('<HH', 8, 0) + names
    out += bytes(start - len(out)) + data
    return bytes(out)


def strings(data):
    """Return {label: raw text bytes} from a synthetic one-slot MSBT."""
    lbl_size = struct.unpack_from('<I', data, 0x24)[0]
    lbl = data[0x30:0x30 + lbl_size]
    labels, pos = {}, 12
    for _ in range(struct.unpack_from('<I', lbl, 4)[0]):
        n = lbl[pos]; labels[struct.unpack_from('<I', lbl, pos + 1 + n)[0]] = lbl[pos + 1:pos + 1 + n].decode(); pos += 5 + n
    txt_at = (0x30 + lbl_size + 15) & ~15
    assert data[txt_at:txt_at + 4] == b'TXT2'
    size = struct.unpack_from('<I', data, txt_at + 4)[0]
    txt = data[txt_at + 16:txt_at + 16 + size]
    count = struct.unpack_from('<I', txt, 0)[0]
    offsets = [struct.unpack_from('<I', txt, 4 + 4 * i)[0] for i in range(count)] + [size]
    return {labels[i]: txt[offsets[i]:offsets[i + 1]] for i in range(count)}


class BalloonWorldTests(unittest.TestCase):
    def test_flow_routes_every_talk_to_one_message_and_never_connects(self):
        before = flow()
        after = balloon.patch_flow(before)
        self.assertEqual(len(after), len(before))
        b = balloon.Byml(after)
        nodes, entries = balloon._flow_nodes(b)
        self.assertEqual(b.value(0xC1, nodes[43])['CaseEventList'][1]['NextId'], 44)
        self.assertEqual(b.value(0xC1, nodes[44])['NextId'], 50)
        self.assertNotIn('StartConnect', balloon._reachable_types(b, nodes, entries))
        self.assertEqual(sum(x != y for x, y in zip(before, after)), 2)  # two low bytes of two NextIds

    def test_unexpected_flow_is_rejected(self):
        for changed in (flow(no_target=3), flow(message_next=46)):
            with self.assertRaisesRegex(ValueError, 'differs'):
                balloon.patch_flow(changed)

    def test_message_keeps_voice_tag_and_other_messages(self):
        other = 'Hi'.encode('utf-16-le') + b'\0\0'
        before = msbt([('TimeBalloon_Other', other), ('TimeBalloon_Separate', VOICE + 'Sorry'.encode('utf-16-le') + b'\0\0')])
        after = balloon.replace_message(before, 'TimeBalloon_Separate', balloon.MESSAGE)
        self.assertEqual(struct.unpack_from('<I', after, 0x12)[0], len(after))
        self.assertEqual(len(after) % 16, 0)
        texts = strings(after)
        self.assertEqual(texts['TimeBalloon_Other'], other)
        self.assertEqual(texts['TimeBalloon_Separate'], VOICE + balloon.MESSAGE.encode('utf-16-le') + b'\0\0')
        with self.assertRaisesRegex(ValueError, 'voice tag'):
            balloon.replace_message(msbt([('TimeBalloon_Separate', other)]), 'TimeBalloon_Separate', balloon.MESSAGE)

    def test_repack_keeps_other_members_and_their_alignment(self):
        members = [('a.msbt', b'A' * 0x40), ('TimeBalloon.msbt', b'B' * 0x40), ('c.msbt', b'C' * 0x40), ('d.msbt', b'D' * 0x30)]
        before = sarc(members)
        after = balloon.replace_member(before, 'TimeBalloon.msbt', b'N' * 0x150)
        start = struct.unpack_from('<I', after, 12)[0]
        found = {name: (lo, after[lo:hi]) for name, lo, hi in phone.members(after, 'test')}
        self.assertEqual(found['TimeBalloon.msbt'][1], b'N' * 0x150)
        for name, body in members:
            if name != 'TimeBalloon.msbt':
                self.assertEqual(found[name][1], body)
                self.assertEqual((found[name][0] - start) % 0x80, 0)
        self.assertEqual(struct.unpack_from('<I', after, 8)[0], len(after))

    def test_prepare_writes_flow_and_every_language(self):
        with tempfile.TemporaryDirectory() as temp:
            romfs, overlay = Path(temp) / 'RomFS', Path(temp) / 'overlay'
            def yaz0(data):
                return common.yaz0_literal(data, b'Yaz0' + bytes(4) + struct.pack('>I', 0x80) + bytes(4))
            (romfs / 'EventData').mkdir(parents=True)
            (romfs / 'EventData/BalloonGame.szs').write_bytes(yaz0(sarc([('NpcStandby.byml', flow())])))
            separate = VOICE + 'Sorry'.encode('utf-16-le') + b'\0\0'
            languages = [f'L{i:02d}' for i in range(balloon.LANGUAGES)]
            for language in languages:
                path = romfs / 'LocalizedData' / language / 'MessageData'
                path.mkdir(parents=True)
                (path / 'SystemMessage.szs').write_bytes(yaz0(sarc([
                    ('Other.msbt', b'O' * 0x20), ('TimeBalloon.msbt', msbt([('TimeBalloon_Separate', separate)]))])))
            sources = {p: p.read_bytes() for p in romfs.rglob('*.szs')}
            records = balloon.prepare(romfs, overlay)
            self.assertEqual(len(records), 1 + balloon.LANGUAGES)
            self.assertEqual({p: p.read_bytes() for p in romfs.rglob('*.szs')}, sources)  # inputs untouched
            for record in records:
                output = common.yaz0_decode((overlay / record['relative_path']).read_bytes())
                self.assertEqual(common.sha((overlay / record['relative_path']).read_bytes()), record['output_sha256'])
                body = {name: output[lo:hi] for name, lo, hi in phone.members(output, 'out')}
                if record['member'] == 'TimeBalloon.msbt':
                    self.assertTrue(strings(body['TimeBalloon.msbt'])['TimeBalloon_Separate'].startswith(VOICE + 'Hey, Bro!'.encode('utf-16-le')))
                    self.assertEqual(body['Other.msbt'], b'O' * 0x20)
            (romfs / 'LocalizedData' / languages[0] / 'MessageData/SystemMessage.szs').unlink()
            with self.assertRaisesRegex(ValueError, 'SystemMessage'):
                balloon.prepare(romfs, Path(temp) / 'overlay2')


if __name__ == '__main__':
    unittest.main()
