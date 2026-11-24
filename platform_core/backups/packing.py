"""Lossless text packing in an encrypted, offline staging copy only."""

import struct
import zlib

# These fields contain mutable JSON or text, have no expression indexes, and are
# restored before the database is opened by a business service.
FIELDS = {
    "workspace": ("data",),
    "rounds_reports": ("payload",),
    "dossier_profiles": ("basic", "household"),
    "dossier_relatives": ("details",),
}
TAG = b"AKZ1"
MAX_VALUE = 256 * 1024 * 1024


def pack(value):
    data = value.encode("utf-8")
    if not 512 <= len(data) <= MAX_VALUE:
        return value
    compressed = zlib.compress(data, level=6)
    if len(compressed) + 32 >= len(data):
        return value
    return TAG + struct.pack(">I", len(data)) + compressed


def unpack(value):
    if len(value) < 8 or not value.startswith(TAG):
        raise ValueError("备份中的压缩文本标识无效")
    size = struct.unpack(">I", value[4:8])[0]
    if not 512 <= size <= MAX_VALUE:
        raise ValueError("备份中的文本长度不符")
    decoder = zlib.decompressobj()
    try:
        data = decoder.decompress(value[8:], size + 1)
        if len(data) != size or not decoder.eof or decoder.unused_data:
            raise ValueError("备份的压缩文本不完整")
        return data.decode("utf-8")
    except (zlib.error, UnicodeError):
        raise ValueError("备份中的压缩文本无法读取") from None


def transform(db, *, restore=False):
    tables = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table, columns in FIELDS.items():
        if table not in tables:
            continue
        for column in columns:
            kind = "blob" if restore else "text"
            # Iterate in immutable rowid order. Process a single JSON record at a time.
            cursor = db.execute(
                f'SELECT rowid,"{column}" FROM "{table}" WHERE typeof("{column}")=? ORDER BY rowid',
                (kind,),
            )
            for rowid, value in cursor:
                converted = unpack(value) if restore else pack(value)
                if converted != value:
                    db.execute(
                        f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?',
                        (converted, rowid),
                    )
