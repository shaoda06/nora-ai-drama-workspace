from io import BytesIO
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from backend.services.jianying_package import encode_jypack


def restore_package(data):
    """Native import format: restore directory and referenced local headers."""
    data = bytearray(data)
    if data[-22:-18] != b'JY\x05\x06':
        raise AssertionError('Missing native end-of-directory record')
    count = struct.unpack_from('<H', data, len(data) - 12)[0]
    offset = struct.unpack_from('<I', data, len(data) - 6)[0]
    for _ in range(count):
        if data[offset:offset + 4] != b'JY\x01\x02':
            raise AssertionError('Missing native directory record')
        local = struct.unpack_from('<I', data, offset + 42)[0]
        if data[local:local + 4] != b'JY\x03\x04':
            raise AssertionError('Missing native file header')
        data[offset:offset + 2] = data[local:local + 2] = b'PK'
        offset += 46 + sum(struct.unpack_from('<3H', data, offset + 28))
    data[-22:-20] = b'PK'
    return bytes(data)


class JianyingPackageTests(unittest.TestCase):
    def test_native_headers_round_trip_without_rewriting_embedded_signature_bytes(self):
        # MOV/MP4 payloads may themselves contain ZIP or JY signature bytes.
        payload = b'PK\x03\x04JY\x01\x02PK\x05\x06' * 40
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / '测试.jypack'
            with ZipFile(path, 'w', compression=ZIP_STORED) as archive:
                member = ZipInfo('第2场-透明片头.mov')
                member.comment = b'per-file comment'
                archive.writestr(member, payload)
                archive.writestr('draft_info.json', '{"name":"片头"}')
            original = path.read_bytes()
            encode_jypack(path)
            restored = restore_package(path.read_bytes())
            self.assertEqual(restored, original)
            with ZipFile(BytesIO(restored)) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.read(member.filename), payload)

    def test_zip64_extension_records_are_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'large.jypack'
            with patch('zipfile.ZIP64_LIMIT', 32):
                with ZipFile(path, 'w') as archive:
                    archive.writestr('video.mov', b'x' * 128)
                    archive.writestr('draft_info.json', b'{}')
            original = path.read_bytes()
            with ZipFile(path) as archive:
                offsets = [item.header_offset for item in archive.infolist()]
                central = archive.start_dir
                for _ in archive.infolist():
                    offsets.append(central)
                    central += 46 + sum(struct.unpack_from('<3H', original, central + 28))
            offsets.append(len(original) - 22)
            expected = bytearray(original)
            for offset in offsets:
                expected[offset:offset + 2] = b'JY'
            encode_jypack(path)
            self.assertEqual(path.read_bytes(), expected)
            self.assertIn(b'PK\x06\x06', expected)
            self.assertIn(b'PK\x06\x07', expected)
