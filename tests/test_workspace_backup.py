import hashlib
import json
import pytest
from scripts.backup_workspace import validate_backup
from src.workspace.models import Base


def fixture_backup(root):
    root.mkdir()
    (root / 'originals').mkdir()
    dump = root / 'database.dump'
    dump.write_bytes(b'synthetic dump for checksum validation')
    key = 'a' * 32 + '.txt'
    (root / 'originals' / key).write_bytes(b'synthetic original')
    manifest = {'format': 1, 'database_sha256': hashlib.sha256(dump.read_bytes()).hexdigest(),
        'files': {key: hashlib.sha256(b'synthetic original').hexdigest()},
        'tables': {table.name: 0 for table in Base.metadata.tables.values()}, 'migration': '20261120_01'}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    return manifest, key


def test_backup_checksums_reject_modified_originals(tmp_path):
    root = tmp_path / 'backup'
    manifest, key = fixture_backup(root)
    assert validate_backup(root) == manifest
    (root / 'originals' / key).write_bytes(b'modified')
    with pytest.raises(ValueError): validate_backup(root)


def test_backup_rejects_traversal_and_modified_dump(tmp_path):
    root = tmp_path / 'backup'
    manifest, key = fixture_backup(root)
    manifest['files'] = {'../outside.txt': manifest['files'][key]}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError): validate_backup(root)
    manifest['files'] = {}
    (root / 'manifest.json').write_text(json.dumps(manifest))
    (root / 'database.dump').write_bytes(b'changed dump')
    with pytest.raises(ValueError): validate_backup(root)
