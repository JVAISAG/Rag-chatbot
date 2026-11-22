"""Opt-in PostgreSQL checks for private collections and concurrent conflicts."""

from concurrent.futures import ThreadPoolExecutor
import os
import re
from threading import Barrier
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import NullPool

from src.workspace.auth.cookies import SESSION_COOKIE
from src.workspace.auth.sessions import issue_session
from src.workspace.auth.settings import AuthSettings
from src.workspace.database import WorkspaceDatabase, database_url
from src.workspace.library.collections import CollectionCreate, CollectionNameUnavailable, create_collection
from src.workspace.main import create_app
from src.workspace.models import Base, Collection, User


@pytest.mark.skipif(
    os.environ.get("WORKSPACE_RUN_POSTGRES_TESTS") != "1",
    reason="Set WORKSPACE_RUN_POSTGRES_TESTS=1 for isolated PostgreSQL tests.",
)
def test_postgres_concurrent_names_and_account_isolation(tmp_path):
    url = database_url()
    if url.host not in {"127.0.0.1", "localhost"} or not re.fullmatch(r"research_test_[0-9a-f]{12}", url.database or ""):
        pytest.fail("PostgreSQL collection tests require a dedicated local research_test_<12 hex digits> database.")

    schema = f"workspace_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 3})
    workspace_engine = None
    database = None
    created = False
    try:
        with admin_engine.begin() as connection:
            connection.exec_driver_sql('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True
        workspace_engine = create_engine(
            url,
            poolclass=NullPool,
            connect_args={"connect_timeout": 3, "options": f"-csearch_path={schema},public"},
        )
        Base.metadata.create_all(workspace_engine)
        database = WorkspaceDatabase(engine_factory=lambda: workspace_engine)
        owner, other = uuid.uuid4(), uuid.uuid4()
        with database.transaction() as session:
            session.add_all([User(id=owner, password_hash="example"), User(id=other, password_hash="example")])

        barrier = Barrier(2)

        def attempt(name):
            barrier.wait(timeout=10)
            try:
                return create_collection(database, owner, CollectionCreate(name=name))
            except CollectionNameUnavailable:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ["Café", "CAFE\u0301"]))
        successes = [result for result in results if result is not None]
        assert len(successes) == 1
        winning = successes[0]

        other_collection = create_collection(database, other, CollectionCreate(name="CAFÉ"))
        assert other_collection.id != winning.id
        owner_token = issue_session(database, owner).token
        other_token = issue_session(database, other).token
        app = create_app(lambda: database, lambda: AuthSettings(cookie_secure=False))
        with TestClient(app, headers={"origin": "http://localhost:3000"}) as client:
            client.cookies.set(SESSION_COOKIE, other_token)
            path = f"/api/v2/collections/{winning.id}"
            assert client.get(path).status_code == 404
            assert client.patch(path, json={"name": "Changed"}).status_code == 404
            assert client.delete(path).status_code == 404
            assert [item["id"] for item in client.get("/api/v2/collections").json()] == [str(other_collection.id)]
            client.cookies.clear()
            client.cookies.set(SESSION_COOKIE, owner_token)
            assert client.get(path).status_code == 200
            assert client.get(path).json()["name"] == winning.name

            from src.workspace.jobs.worker import Worker
            from src.workspace.library.imports import extraction_handler
            app.state.source_storage = tmp_path
            uploaded = client.post(path + "/sources/upload", files={"file": ("paper.txt", b"Research evidence.")})
            assert uploaded.status_code == 202
            membership = path + "/sources/" + uploaded.json()["id"]
            membership_barrier = Barrier(2)
            def concurrent_membership(method):
                membership_barrier.wait(timeout=10)
                return client.request(method, membership)
            with ThreadPoolExecutor(max_workers=2) as pool:
                membership_results = list(pool.map(concurrent_membership, ["POST", "DELETE"]))
            assert all(result.status_code == 204 for result in membership_results)
            assert client.post(membership).status_code == 204
            metadata = client.patch(f"/api/v2/sources/{uploaded.json()['id']}", json={"title": "Research paper", "publication_date": "2024-02-29", 'tags': ['Reviewed'], 'reading_status': 'read'})
            assert metadata.status_code == 200
            assert client.get(path + "/sources").json()[0]["publication_date"] == "2024-02-29"
            assert Worker(database, {"extract": extraction_handler(database, tmp_path)}).run_once()
            assert client.get(f"/api/v2/sources/{uploaded.json()['id']}/text").json()["pages"][0]["text"] == "Research evidence."
            from src.workspace.library.indexing import indexing_handler
            from src.workspace.library.search import search_collection
            embed = lambda texts: [[1.0] + [0.0] * 383 for _ in texts]
            split = lambda docs: [{"text": docs[0]["text"], "metadata": {"page": 1}}]
            assert Worker(database, {"index": indexing_handler(database, embed=embed, split=split)}).run_once()
            tracked = client.get(path + '/sources').json()[0]
            assert tracked['tags'] == ['Reviewed'] and tracked['reading_status'] == 'read'
            hits = search_collection(database, owner, winning.id, "evidence", embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert len(hits) == 1
            assert hits[0]["metadata"]["source_id"] == uploaded.json()["id"]
            for mode in ('dense', 'bm25', 'hybrid', 'reranked'):
                configured_hits = search_collection(database, owner, winning.id, 'evidence', embed=embed,
                    rerank=lambda query, candidates, top_k: candidates[:top_k], mode=mode)
                assert configured_hits and all(hit['metadata']['source_id'] == uploaded.json()['id'] for hit in configured_hits)
            # A retained, fully indexed revision must not enter search or the reader
            # until it is explicitly selected as the active revision.
            from src.workspace.models import Chunk, Source, SourceRevision
            source_id = uuid.UUID(uploaded.json()["id"])
            historical_id = uuid.uuid4()
            with database.transaction() as session:
                source = session.get(Source, source_id)
                original_id = source.active_revision_id
                assert original_id is not None
                session.add(SourceRevision(id=historical_id, source_id=source_id,
                    pages=[{"text": "Earlier evidence.", "page": 1}], extraction_version="loader-v1", embedding_model="all-MiniLM-L6-v2"))
                session.flush()
                session.add(Chunk(id=uuid.uuid4(), revision_id=historical_id, ordinal=0, page=1,
                    text="Earlier evidence.", embedding=embed(["evidence"])[0]))
            assert len(client.get(path + "/sources").json()) == 1
            assert client.get(f"/api/v2/sources/{source_id}/text").json()["pages"][0]["text"] == "Research evidence."
            hits = search_collection(database, owner, winning.id, "evidence", embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert [hit["metadata"]["revision_id"] for hit in hits] == [str(original_id)]
            with database.transaction() as session:
                session.get(Source, source_id).active_revision_id = historical_id
            assert client.get(f"/api/v2/sources/{source_id}/text").json()["pages"][0]["text"] == "Earlier evidence."
            hits = search_collection(database, owner, winning.id, "evidence", embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert [hit["metadata"]["revision_id"] for hit in hits] == [str(historical_id)]
            assert search_collection(database, other, other_collection.id, "evidence", embed=embed) == []
            client.cookies.clear()
            client.cookies.set(SESSION_COOKIE, other_token)
            assert client.patch(f"/api/v2/sources/{uploaded.json()['id']}", json={"title": "Not mine"}).status_code == 404
            other_upload = client.post(f"/api/v2/collections/{other_collection.id}/sources/upload", files={"file": ("other.txt", b"Other research evidence.")})
            assert other_upload.status_code == 202
            assert Worker(database, {"extract": extraction_handler(database, tmp_path)}).run_once()
            assert Worker(database, {"index": indexing_handler(database, embed=embed, split=split)}).run_once()
            other_hits = search_collection(database, other, other_collection.id, "evidence", embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert len(other_hits) == 1
            assert other_hits[0]["metadata"]["source_id"] == other_upload.json()["id"]
            assert other_hits[0]["metadata"]["source_id"] != uploaded.json()["id"]
            from types import SimpleNamespace
            from src.workspace.library.questions import answer_handler
            conversation = client.post(f"/api/v2/collections/{other_collection.id}/conversations").json()["id"]
            key = str(uuid.uuid4())
            def ask_duplicate(_):
                return client.post(f"/api/v2/conversations/{conversation}/messages", json={"question": "What is the evidence?"}, headers={"Idempotency-Key": key})
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(ask_duplicate, range(2)))
            assert all(response.status_code == 202 for response in responses)
            assert responses[0].json() == responses[1].json()
            generator = SimpleNamespace(_prepare_context=lambda question, items: ("prompt", items), condense_query=lambda query, history: query)
            retrieve = lambda database, user, collection, question: search_collection(database, user, collection, question, embed=embed, rerank=lambda query, candidates, top_k: candidates[:top_k])
            from test_workspace_questions import cited
            assert Worker(database, {"answer": answer_handler(database, retrieve=retrieve, generator_factory=lambda: generator, generate=lambda prompt: cited('Supported evidence.'))}).run_once()
            result = client.get(f"/api/v2/conversations/{conversation}").json()["turns"][0]
            assert result["status"] == "completed" and result["evidence"][0]["available"]

            # Quoted fallbacks persist with their original reference and still
            # obey membership masking after publication.
            import json
            assert client.post(f'/api/v2/conversations/{conversation}/messages', json={'question': 'Which passage supports it?'}).status_code == 202
            outputs = iter([json.dumps({'claims': [], 'insufficient_evidence': True}),
                json.dumps({'quote': 'Other research evidence.', 'reference': 1})])
            assert Worker(database, {'answer': answer_handler(database, retrieve=retrieve,
                generator_factory=lambda: generator, generate=lambda prompt: next(outputs))}).run_once()
            quoted = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][-1]
            assert quoted['status'] == 'quoted_evidence' and 'Other research evidence.' in quoted['answer']
            member_path = f"/api/v2/collections/{other_collection.id}/sources/{other_upload.json()['id']}"
            assert client.delete(member_path).status_code == 204
            hidden = client.get(f'/api/v2/conversations/{conversation}').json()['turns'][-1]['evidence'][0]
            assert not hidden['available'] and hidden['text'] == ''
            assert client.post(member_path).status_code == 204

            # Account-level locking serializes competing replacements with the
            # same bytes, even when they target two different documents.
            from src.workspace.library.imports import ReplacementConflict, stage_replacement
            use_owner = issue_session(database, owner).token
            client.cookies.clear()
            client.cookies.set(SESSION_COOKIE, use_owner)
            second_source = client.post(path + "/sources/upload", files={"file": ("second.txt", b"Second document.")}).json()["id"]
            assert Worker(database, {"extract": extraction_handler(database, tmp_path)}).run_once()
            assert Worker(database, {"index": indexing_handler(database, embed=embed, split=split)}).run_once()
            race = Barrier(2)
            def replace_concurrently(target):
                race.wait(timeout=10)
                try:
                    return stage_replacement(database, tmp_path, owner, uuid.UUID(target), "same.txt", b"Concurrent replacement.")
                except ReplacementConflict:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(replace_concurrently, [uploaded.json()["id"], second_source]))
            assert sum(item is not None for item in outcomes) == 1
            winner = [uploaded.json()["id"], second_source][next(i for i, item in enumerate(outcomes) if item)]
            assert Worker(database, {"extract": extraction_handler(database, tmp_path)}).run_once()
            assert Worker(database, {"index": indexing_handler(database, embed=embed, split=split)}).run_once()
            assert client.get(f"/api/v2/sources/{winner}/text").json()["pages"][0]["text"] == "Concurrent replacement."
            final_hits = search_collection(database, owner, winning.id, "replacement", embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert any(hit["metadata"]["source_id"] == winner and hit["text"] == "Concurrent replacement." for hit in final_hits)
            selected_hits = search_collection(database, owner, winning.id, 'evidence', embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k], source_ids=[second_source])
            assert selected_hits and all(hit['metadata']['source_id'] == second_source for hit in selected_hits)
            with pytest.raises(LookupError):
                search_collection(database, owner, winning.id, 'evidence', embed=embed, source_ids=[other_upload.json()['id']])

            from src.workspace.library.url_imports import url_import_handler
            from src.workspace.library.web_fetch import FetchedPage
            article = b'<html><body><article><p>Researchers measured the performance of a new classifier using controlled experimental evidence.</p></article></body></html>'
            imported = client.post(path + '/sources/import-url', json={'url': 'https://example.com/article'}).json()['job_id']
            assert Worker(database, {'url_import': url_import_handler(database, tmp_path,
                fetch=lambda url: FetchedPage(url, 'text/html', article))}).run_once()
            imported_source = client.get(f'/api/v2/jobs/{imported}').json()['source_id']
            assert imported_source
            assert Worker(database, {'extract': extraction_handler(database, tmp_path)}).run_once()
            assert Worker(database, {'index': indexing_handler(database, embed=embed, split=split)}).run_once()
            hits = search_collection(database, owner, winning.id, 'classifier', embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert any(hit['metadata']['source_id'] == imported_source and 'classifier' in hit['text'] for hit in hits)
            from src.workspace.library.url_imports import url_refresh_handler
            assert client.post(f'/api/v2/sources/{imported_source}/refresh').status_code == 202
            assert client.post(f'/api/v2/sources/{imported_source}/replace', files={'file': ('other.txt', b'new file')}).status_code == 409
            updated_article = b'<html><body><article><p>The updated study evaluates a different classifier and reports fresh experimental results.</p></article></body></html>'
            assert Worker(database, {'url_refresh': url_refresh_handler(database, tmp_path,
                fetch=lambda url: FetchedPage(url, 'text/html', updated_article))}).run_once()
            assert 'controlled experimental evidence' in client.get(f'/api/v2/sources/{imported_source}/text').json()['pages'][0]['text']
            assert Worker(database, {'extract': extraction_handler(database, tmp_path)}).run_once()
            assert Worker(database, {'index': indexing_handler(database, embed=embed, split=split)}).run_once()
            assert 'fresh experimental results' in client.get(f'/api/v2/sources/{imported_source}/text').json()['pages'][0]['text']
            hits = search_collection(database, owner, winning.id, 'fresh', embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert any(hit['metadata']['source_id'] == imported_source and 'fresh experimental results' in hit['text'] for hit in hits)
            from src.workspace.library.summaries import summary_handler
            from test_workspace_summaries import generated
            summary_id = client.post(f'/api/v2/sources/{imported_source}/summaries').json()['id']
            assert Worker(database, {'summary': summary_handler(database, generate=generated)}).run_once()
            assert client.get(f'/api/v2/analyses/{summary_id}').json()['status'] == 'completed'
            second_summary = client.post(f"/api/v2/sources/{uploaded.json()['id']}/summaries").json()['id']
            assert Worker(database, {'summary': summary_handler(database, generate=generated)}).run_once()
            comparison = client.post(f'/api/v2/collections/{winning.id}/comparisons', json={'summary_ids': [summary_id, second_summary]})
            assert comparison.status_code == 201
            comparison_id = comparison.json()['id']
            note = client.post(f'/api/v2/collections/{winning.id}/notes', json={'title': 'Research', 'markdown': 'Saved observations.', 'comparison_ids': [comparison_id]})
            assert note.status_code == 201
            note_id = note.json()['id']
            assert 'Saved observations.' in client.get(f'/api/v2/notes/{note_id}/export').text
            barrier = Barrier(2)
            def edit_note(value):
                barrier.wait(timeout=10)
                return client.patch(f'/api/v2/notes/{note_id}', json={'title': 'Research', 'markdown': value,
                    'version': note.json()['version'], 'comparison_ids': [comparison_id]}).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:
                edits = list(pool.map(edit_note, ['First editor', 'Second editor']))
            assert sorted(edits) == [200, 409]
            from src.workspace.library.deletion import cleanup_source_handler
            assert client.delete(f'/api/v2/sources/{imported_source}').status_code == 204
            from src.workspace.library.sparse_cache import SPARSE_CACHE
            assert all(key[0] != str(owner) for key in SPARSE_CACHE.entries)
            assert client.get(f'/api/v2/sources/{imported_source}/text').status_code == 404
            assert client.get(f'/api/v2/analyses/{summary_id}').json()['status'] == 'unavailable'
            assert not client.get(f'/api/v2/comparisons/{comparison_id}').json()['sources'][0]['available']
            assert 'Evidence unavailable.' in client.get(f'/api/v2/notes/{note_id}/export').text
            hits = search_collection(database, owner, winning.id, 'fresh', embed=embed,
                rerank=lambda query, candidates, top_k: candidates[:top_k])
            assert all(hit['metadata']['source_id'] != imported_source for hit in hits)
            assert Worker(database, {'cleanup_source': cleanup_source_handler(database, tmp_path)}).run_once()

            with database.transaction() as session:
                assert len(session.scalars(select(Collection)).all()) == 2
    finally:
        if database is not None:
            database.close()
        elif workspace_engine is not None:
            workspace_engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin_engine.dispose()
