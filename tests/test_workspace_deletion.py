"""Source deletion revokes work and removes access before file cleanup."""
import uuid
from sqlalchemy import select
from test_workspace_collections import collection_api, use_session
from test_workspace_replacements import prepare
from src.workspace.jobs.worker import Worker
from src.workspace.library.deletion import cleanup_source_handler
from src.workspace.models import Chunk, Job, Source, SourceRevision


def test_delete_is_private_removes_all_memberships_and_cleans_files(collection_api, tmp_path):
    client, database, first, other, collection, source_id, _, extract, index = prepare(collection_api, tmp_path)
    endpoint = f'/api/v2/sources/{source_id}'
    with database.transaction() as session:
        key = session.get(Source, uuid.UUID(source_id)).storage_key
    another = client.post('/api/v2/collections', json={'name': 'Another'}).json()['id']
    assert client.post(f'/api/v2/collections/{another}/sources/{source_id}').status_code == 204
    use_session(client, other)
    assert client.delete(endpoint).status_code == 404
    use_session(client, first)
    assert client.delete(endpoint, headers={'origin': 'http://evil.test'}).status_code == 403
    # Deletion must also revoke an in-flight replacement's extraction task.
    replacement = client.post(endpoint + '/replace', files={'file': ('update.txt', b'New evidence.')}).json()
    assert client.delete(endpoint).status_code == 204
    assert client.get(endpoint + '/text').status_code == 404
    assert client.get(f'/api/v2/collections/{another}/sources').json() == []
    assert all(row['id'] != source_id for row in client.get('/api/v2/sources').json())
    with database.transaction() as session:
        assert session.get(Source, uuid.UUID(source_id)) is None
        assert not session.scalars(select(SourceRevision).where(SourceRevision.source_id == uuid.UUID(source_id))).all()
        assert session.get(Job, uuid.UUID(replacement['job_id'])).status == 'failed'
    assert (tmp_path / key).exists()
    assert Worker(database, {'cleanup_source': cleanup_source_handler(database, tmp_path)}).run_once()
    assert not (tmp_path / key).exists()
    assert not extract.run_once()
    assert client.delete(endpoint).status_code == 404


def test_saved_answer_retains_text_but_deleted_evidence_is_unavailable(collection_api, tmp_path):
    from test_workspace_questions import setup_question, cited
    from src.workspace.library.questions import answer_handler
    client, database, _, conversation, _, hits, generator = setup_question(collection_api, tmp_path)
    assert Worker(database, {'answer': answer_handler(database, retrieve=lambda *args: hits,
        generator_factory=lambda: generator, generate=lambda prompt: cited('Supported result.'))}).run_once()
    with database.transaction() as session:
        source_id = session.scalar(select(Source.id))
    assert client.delete(f'/api/v2/sources/{source_id}').status_code == 204
    turn = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][0]
    assert turn['answer'] == 'Supported result. [1]'
    assert not turn['evidence'][0]['available'] and turn['evidence'][0]['text'] == ''
