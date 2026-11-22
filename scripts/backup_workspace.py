"""Consistent local database/file backup and restore into a new isolated database."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from src.workspace.database import database_url
from src.workspace.library.cleanup import GENERATED_KEY
from src.workspace.library.imports import DEFAULT_STORAGE, lock_storage
from src.workspace.models import Base, Source, SourceReplacement, SourceRevision


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def container():
    process = subprocess.run(['docker', 'compose', '-f', str(ROOT / 'compose.workspace.yaml'), 'ps', '-q', 'postgres'],
        cwd=ROOT, capture_output=True, text=True, check=True)
    identity = process.stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{12,64}', identity):
        raise RuntimeError('The local workspace PostgreSQL container is unavailable.')
    return identity


def local_url():
    url = database_url()
    if url.host not in {'localhost', '127.0.0.1'}:
        raise RuntimeError('This helper only supports local workspace databases.')
    return url


def create_backup(destination):
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(DEFAULT_STORAGE.resolve()):
        raise ValueError('Choose a new backup directory outside private original storage.')
    url, identity = local_url(), container()
    engine = create_engine(url, isolation_level='REPEATABLE READ', poolclass=NullPool)
    destination.mkdir(parents=True)
    try:
        with Session(engine) as session, session.begin():
            lock_storage(session)
            snapshot = session.scalar(text('SELECT pg_export_snapshot()'))
            # Files are immutable; the shared lock postpones cleanup and staging
            # until pg_dump and the file copy have captured this snapshot.
            required = set(session.scalars(select(Source.storage_key)))
            required.update(session.scalars(select(SourceRevision.storage_key).where(SourceRevision.embedding_model.is_not(None))))
            required.update(session.scalars(select(SourceReplacement.storage_key).where(SourceReplacement.status != 'abandoned')))
            required.discard(None)
            originals = destination / 'originals'
            originals.mkdir()
            files = {}
            root = DEFAULT_STORAGE.resolve()
            for key in sorted(required):
                if not GENERATED_KEY.fullmatch(key):
                    raise ValueError('A database record has an invalid storage key.')
                source = root / key
                if source.is_symlink() or not source.is_file() or source.resolve().parent != root:
                    raise ValueError('A referenced original is missing or unsafe; backup refused.')
                target = originals / key
                shutil.copy2(source, target)
                files[key] = digest(target)
            dump = destination / 'database.dump'
            with dump.open('xb') as output:
                subprocess.run(['docker', 'exec', identity, 'pg_dump', '-U', url.username, '-d', url.database,
                    '--format=custom', '--no-owner', '--no-privileges', '--snapshot', snapshot], stdout=output,
                    stderr=subprocess.PIPE, check=True)
            tables = {table.name: session.scalar(select(text('count(*)')).select_from(table)) for table in Base.metadata.tables.values()}
            manifest = {'format': 1, 'database_sha256': digest(dump), 'files': files, 'tables': tables,
                'migration': session.scalar(text('SELECT version_num FROM alembic_version'))}
            (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'Backup created: {destination}')
    finally:
        engine.dispose()


def validate_backup(directory):
    directory = directory.resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Unsupported backup manifest.')
    dump = directory / 'database.dump'
    if dump.is_symlink() or digest(dump) != manifest.get('database_sha256'):
        raise ValueError('Database backup checksum failed.')
    for key, expected in manifest['files'].items():
        if not isinstance(key, str) or not GENERATED_KEY.fullmatch(key):
            raise ValueError('Invalid original filename in backup.')
        path = directory / 'originals' / key
        if path.is_symlink() or digest(path) != expected:
            raise ValueError('Original backup checksum failed.')
    if set(manifest.get('tables', {})) != {table.name for table in Base.metadata.tables.values()}:
        raise ValueError('Backup schema differs from this application version.')
    return manifest


def restore_new(directory, files_root, *, verify_only=False):
    manifest = validate_backup(directory)
    files_root = files_root.resolve()
    if files_root.exists():
        raise ValueError('Restore requires a new originals directory.')
    url, identity = local_url(), container()
    name = 'research_restore_' + uuid.uuid4().hex[:12]
    admin = create_engine(url, isolation_level='AUTOCOMMIT', poolclass=NullPool)
    restored = None
    created = False
    completed = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        with (directory / 'database.dump').open('rb') as stream:
            subprocess.run(['docker', 'exec', '-i', identity, 'pg_restore', '-U', url.username, '-d', name,
                '--no-owner', '--no-privileges', '--exit-on-error'], stdin=stream, stderr=subprocess.PIPE, check=True)
        files_root.mkdir(parents=True)
        for key in manifest['files']:
            shutil.copy2(directory / 'originals' / key, files_root / key)
        restored = create_engine(url.set(database=name), poolclass=NullPool)
        with restored.connect() as connection:
            for table in Base.metadata.tables.values():
                if connection.scalar(select(text('count(*)')).select_from(table)) != manifest['tables'][table.name]:
                    raise RuntimeError('Restored record counts differ from the backup.')
            if connection.scalar(text('SELECT version_num FROM alembic_version')) != manifest['migration']:
                raise RuntimeError('Restored migration differs from the backup.')
        if any(digest(files_root / key) != expected for key, expected in manifest['files'].items()):
            raise RuntimeError('Restored originals differ from the backup.')
        completed = True
        print(f'Restored and verified database: {name}')
        print(f'Restored originals: {files_root}')
        if not verify_only:
            print('To use this separate instance, set WORKSPACE_DB_NAME to the restored name and WORKSPACE_SOURCE_STORAGE to its originals directory.')
    finally:
        if restored is not None: restored.dispose()
        if created and (verify_only or not completed):
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
            print('Removed isolated restore verification database.')
        admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    backup = sub.add_parser('create')
    backup.add_argument('directory', type=Path)
    restore = sub.add_parser('restore-new')
    restore.add_argument('directory', type=Path)
    restore.add_argument('--files-root', type=Path, required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.mode == 'create': create_backup(args.directory)
    elif args.mode == 'restore-new': restore_new(args.directory.resolve(), args.files_root)
    else:
        with TemporaryDirectory(prefix='restore-check-', dir=ROOT / '.cache') as temporary:
            restore_new(args.directory.resolve(), Path(temporary) / 'originals', verify_only=True)


if __name__ == '__main__':
    main()
