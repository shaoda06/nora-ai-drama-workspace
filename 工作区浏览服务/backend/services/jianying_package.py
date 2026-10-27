"""Jianying 11.6 draft archive headers, leaving media and JSON untouched.

The native importer's rewriteDraftPackageZipSignature restores JY to PK for
local file headers, central directory headers and the end-of-directory record.
ZIP64 extension records retain their standard signatures. This is a container
format, not a replacement for Jianying's own import/entitlement checks.
"""
from struct import unpack_from
from zipfile import ZipFile


def encode_jypack(path):
    """Convert a ZIP produced by our exporter (no archive comment) in place."""
    with ZipFile(path) as archive:
        members = archive.infolist()
        central_offset = archive.start_dir
    with path.open('r+b') as stream:
        for member in members:
            stream.seek(member.header_offset)
            stream.write(b'JY')
            stream.seek(central_offset)
            header = stream.read(46)
            stream.seek(central_offset)
            stream.write(b'JY')
            central_offset += 46 + sum(unpack_from('<3H', header, 28))
        stream.seek(-22, 2)
        stream.write(b'JY')
