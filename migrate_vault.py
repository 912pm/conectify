"""Copy an existing vault to a new location without modifying the original."""
from pathlib import Path
import os
import shutil
import sqlite3
import tempfile
from core import Store


def migrate(source, destination):
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    if source == destination or destination.exists():
        raise ValueError('Destination already exists; no data was replaced.')
    if not (source / 'conectify.sqlite3').is_file():
        raise ValueError('Source is not a Conectify vault.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.vault-migration-', dir=str(destination.parent)))
    try:
        store = Store(source)
        with store.lock():
            for name in ('styles', 'games', 'history', 'attachments'):
                if (source / name).is_dir():
                    shutil.copytree(source / name, staging / name)
            with store.db() as original, sqlite3.connect(str(staging / 'conectify.sqlite3')) as target:
                original.backup(target)
                # Uploaded images belong to the vault; external references stay linked.
                for ref_id, path in target.execute('SELECT id,path FROM refs').fetchall():
                    try:
                        relative = Path(path).relative_to(source)
                    except ValueError:
                        continue
                    target.execute('UPDATE refs SET path=? WHERE id=?', (str(destination / relative), ref_id))
                rows = target.execute('SELECT path,hash FROM note_seen').fetchall()
                target.execute('DELETE FROM note_seen')
                for path, digest in rows:
                    try:
                        path = str(destination / Path(path).relative_to(source))
                    except ValueError:
                        pass
                    target.execute('INSERT INTO note_seen VALUES(?,?)', (path, digest))
            os.rename(staging, destination)
        return destination
    finally:
        if staging.exists():
            shutil.rmtree(staging)
