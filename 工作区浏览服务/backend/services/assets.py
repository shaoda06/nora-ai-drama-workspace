"""Independent asset library. SQLite keeps cards and original images together."""
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import json
import sqlite3
from uuid import uuid4
from PIL import Image, UnidentifiedImageError


class AssetError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


MAX_IMAGE_BYTES = 25 * 1024 * 1024


def image_type(data: bytes) -> str:
    # Inspect the file itself; neither extensions nor client MIME types are trusted.
    types = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif', 'WEBP': 'image/webp'}
    try:
        with Image.open(BytesIO(data), formats=list(types)) as image:
            mime = types[image.format]
            image.verify()
            return mime
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as error:
        raise AssetError(422, '图片无法读取，请上传有效的 PNG、JPG、WebP 或 GIF 图片。') from error


class AssetLibrary:
    def __init__(self, root: Path):
        self.root = root

    @property
    def database(self):
        return self.root / 'assets.sqlite3'

    @contextmanager
    def connection(self):
        self.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
                    category TEXT NOT NULL, profile TEXT NOT NULL,
                    revision INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    slot TEXT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS images_asset ON images(asset_id);
            ''')
            with connection:
                yield connection
        finally:
            connection.close()

    def _read(self, connection, asset_id):
        row = connection.execute('SELECT * FROM assets WHERE id = ?', (asset_id,)).fetchone()
        if row is None:
            raise AssetError(404, '这份资产已不存在，请返回列表。')
        item = dict(row)
        item['profile'] = json.loads(item['profile'])
        item['images'] = [dict(image) for image in connection.execute(
            'SELECT id, slot, name, mime, length(data) AS size FROM images WHERE asset_id = ? ORDER BY rowid',
            (asset_id,))]
        return item

    def _edit(self, connection, asset_id, revision):
        connection.execute('BEGIN IMMEDIATE')
        item = self._read(connection, asset_id)
        if item['revision'] != revision:
            raise AssetError(409, '这份资产已在其他页面修改。请重新载入后再操作；当前输入仍保留。')
        return item

    def _touch(self, connection, asset_id):
        connection.execute('UPDATE assets SET revision = revision + 1, updated_at = ? WHERE id = ?',
                           (datetime.now(timezone.utc).isoformat(), asset_id))

    def list(self):
        if not self.database.exists():
            return []
        with self.connection() as connection:
            return [self._read(connection, row['id']) for row in connection.execute(
                'SELECT id FROM assets ORDER BY updated_at DESC, id')]

    def read(self, asset_id):
        if not self.database.exists():
            raise AssetError(404, '这份资产已不存在，请返回列表。')
        with self.connection() as connection:
            return self._read(connection, asset_id)

    def save(self, data, asset_id=None, revision=None):
        with self.connection() as connection:
            if asset_id:
                item = self._edit(connection, asset_id, revision)
                if item['kind'] != data['kind']:
                    raise AssetError(422, '不能更改资产类型。')
                connection.execute('UPDATE assets SET name = ?, category = ?, profile = ? WHERE id = ?',
                                   (data['name'], data['category'], json.dumps(data['profile'], ensure_ascii=False), asset_id))
                self._touch(connection, asset_id)
            else:
                asset_id = uuid4().hex
                connection.execute('INSERT INTO assets VALUES (?, ?, ?, ?, ?, 1, ?)',
                                   (asset_id, data['kind'], data['name'], data['category'],
                                    json.dumps(data['profile'], ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
            return self._read(connection, asset_id)

    def delete(self, asset_id, revision):
        with self.connection() as connection:
            self._edit(connection, asset_id, revision)
            connection.execute('DELETE FROM assets WHERE id = ?', (asset_id,))

    def upload(self, asset_id, revision, slot, name, data):
        if len(data) > MAX_IMAGE_BYTES:
            raise AssetError(413, '单张图片不能超过 25 MB。')
        mime = image_type(data)
        with self.connection() as connection:
            item = self._edit(connection, asset_id, revision)
            if slot not in ('portrait', 'views', 'album') or (item['kind'] != 'person' and slot != 'album'):
                raise AssetError(422, '图片位置与资产类型不符。')
            # Fixed slots each hold one image; replacement is one transaction.
            if slot != 'album':
                connection.execute('DELETE FROM images WHERE asset_id = ? AND slot = ?', (asset_id, slot))
            filename = name.replace('\\', '/').split('/')[-1][:200]
            connection.execute('INSERT INTO images VALUES (?, ?, ?, ?, ?, ?)',
                               (uuid4().hex, asset_id, slot, filename, mime, data))
            self._touch(connection, asset_id)
            return self._read(connection, asset_id)

    def delete_image(self, asset_id, image_id, revision):
        with self.connection() as connection:
            self._edit(connection, asset_id, revision)
            cursor = connection.execute('DELETE FROM images WHERE asset_id = ? AND id = ?', (asset_id, image_id))
            if cursor.rowcount == 0:
                raise AssetError(404, '图片已不存在。')
            self._touch(connection, asset_id)
            return self._read(connection, asset_id)

    def image(self, asset_id, image_id):
        if not self.database.exists():
            raise AssetError(404, '图片已不存在。')
        with self.connection() as connection:
            row = connection.execute('SELECT name, mime, data FROM images WHERE asset_id = ? AND id = ?',
                                     (asset_id, image_id)).fetchone()
            if row is None:
                raise AssetError(404, '图片已不存在。')
            return dict(row)
