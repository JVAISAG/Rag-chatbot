"""Private comparison tables, research notes, and Markdown export."""
from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from src.workspace.auth.dependencies import require_user
from src.workspace.auth.origins import require_trusted_origin
from src.workspace.library.routes import _collection_errors
from src.workspace.models import Analysis, Collection, CollectionSource, Comparison, Note, Source, SourceRevision, User

router = APIRouter(prefix='/api/v2', tags=['research'])
CAUTION = 'Descriptive evidence comparison. Dataset, metric, and evaluation conditions must be checked before comparing numerical results. Summary claims are model-generated and require review.'


def owned_collection(session, owner, identity):
    if session.scalar(select(Collection.id).where(Collection.id == identity, Collection.owner_id == owner)) is None:
        raise HTTPException(404, 'Collection not found.')


def summary_view(session, owner, identity, collection_id):
    analysis = session.scalar(select(Analysis).where(Analysis.id == uuid.UUID(identity), Analysis.owner_id == owner))
    if analysis is None:
        return None
    source = session.scalar(select(Source).where(Source.id == analysis.source_id, Source.owner_id == owner)) if analysis.source_id else None
    revision = session.get(SourceRevision, analysis.revision_id) if analysis.revision_id else None
    member = collection_id and source and session.get(CollectionSource, (collection_id, source.id))
    available = bool(source and revision and revision.source_id == source.id and member and analysis.status == 'completed')
    return {'analysis_id': str(analysis.id), 'source_id': str(source.id) if source else None,
        'revision_id': str(revision.id) if revision else None,
        'filename': revision.filename if revision else None, 'title': source.title if source else None,
        'original_url': revision.original_url if revision else None,
        'available': available, 'result': analysis.result if available else None,
        'evidence': analysis.state['blocks'] if available else [], 'model': analysis.model,
        'created_at': analysis.created_at.isoformat()}


def comparison_view(session, owner, comparison):
    rows = []
    for selected in comparison.selections:
        view = summary_view(session, owner, selected['analysis_id'], comparison.collection_id)
        if view is None or not view['available']:
            rows.append({**selected, 'available': False, 'result': None, 'evidence': []})
        else:
            rows.append(view)
    return {'id': str(comparison.id), 'collection_id': str(comparison.collection_id) if comparison.collection_id else None,
        'sources': rows, 'caution': CAUTION, 'created_at': comparison.created_at.isoformat()}


@router.get('/collections/{collection_id}/research')
def research_options(request: Request, response: Response, collection_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        owned_collection(session, owner, collection_id)
        ids = session.scalars(select(Analysis.id).join(Source, Source.id == Analysis.source_id)
            .join(CollectionSource, CollectionSource.source_id == Source.id).where(Analysis.owner_id == owner,
                Source.owner_id == owner, Analysis.status == 'completed', Analysis.revision_id.is_not(None),
                CollectionSource.collection_id == collection_id).order_by(Analysis.created_at.desc(), Analysis.id.desc())).all()
        summaries = []
        for identity in ids:
            view = summary_view(session, owner, str(identity), collection_id)
            if view and view['available']:
                summaries.append({key: view[key] for key in ('analysis_id', 'source_id', 'revision_id', 'filename', 'title', 'created_at')})
        comparisons = session.scalars(select(Comparison).where(Comparison.owner_id == owner, Comparison.collection_id == collection_id)
            .order_by(Comparison.created_at.desc(), Comparison.id.desc())).all()
        result = {'summaries': summaries, 'comparisons': [{'id': str(row.id), 'created_at': row.created_at.isoformat()} for row in comparisons]}
    response.headers['Cache-Control'] = 'no-store'
    return result


class ComparisonCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    summary_ids: list[uuid.UUID] = Field(min_length=2, max_length=5)


@router.post('/collections/{collection_id}/comparisons', status_code=201, dependencies=[Depends(require_trusted_origin)])
def create_comparison(request: Request, collection_id: uuid.UUID, details: ComparisonCreate, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        session.scalar(select(User.id).where(User.id == owner).with_for_update())
        owned_collection(session, owner, collection_id)
        selected = [summary_view(session, owner, str(identity), collection_id) for identity in details.summary_ids]
        if any(view is None or not view['available'] for view in selected):
            raise HTTPException(404, 'A selected summary is unavailable in this collection.')
        if len({view['source_id'] for view in selected}) != len(selected):
            raise HTTPException(422, 'Choose summaries from different sources.')
        identity = uuid.uuid4()
        selections = [{key: view[key] for key in ('analysis_id', 'source_id', 'revision_id', 'filename', 'title')} for view in selected]
        session.add(Comparison(id=identity, owner_id=owner, collection_id=collection_id, selections=selections))
        return {'id': str(identity)}


@router.get('/comparisons/{comparison_id}')
def read_comparison(request: Request, response: Response, comparison_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        row = session.scalar(select(Comparison).where(Comparison.id == comparison_id, Comparison.owner_id == owner))
        if row is None:
            raise HTTPException(404, 'Comparison not found.')
        result = comparison_view(session, owner, row)
    response.headers['Cache-Control'] = 'no-store'
    return result


class NoteBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    markdown: str = Field(default='', max_length=50000)
    analysis_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    comparison_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5)

    @field_validator('title', 'markdown')
    @classmethod
    def text_valid(cls, value):
        if '\x00' in value:
            raise ValueError('Text contains an invalid character.')
        try:
            value.encode('utf-8')
        except UnicodeError:
            raise ValueError('Text contains invalid Unicode.') from None
        return value

    @field_validator('title')
    @classmethod
    def title_valid(cls, value):
        if not value.strip():
            raise ValueError('Enter a title.')
        return value.strip()


class NoteUpdate(NoteBody):
    version: int = Field(ge=1)


def validate_attachments(session, owner, collection_id, details, *, retained_analysis_ids=()):
    for identity in details.analysis_ids:
        row = session.scalar(select(Analysis).where(Analysis.id == identity, Analysis.owner_id == owner))
        if row is None:
            raise HTTPException(404, 'Summary not found.')
        if (row.source_id is not None and str(identity) not in retained_analysis_ids
                and not session.get(CollectionSource, (collection_id, row.source_id))):
            raise HTTPException(404, 'Summary not in this collection.')
    for identity in details.comparison_ids:
        if session.scalar(select(Comparison.id).where(Comparison.id == identity, Comparison.owner_id == owner, Comparison.collection_id == collection_id)) is None:
            raise HTTPException(404, 'Comparison not found.')


def note_view(row):
    return {'id': str(row.id), 'collection_id': str(row.collection_id) if row.collection_id else None,
        'title': row.title, 'markdown': row.markdown, 'analysis_ids': row.analysis_ids,
        'comparison_ids': row.comparison_ids, 'version': row.version, 'updated_at': row.updated_at.isoformat()}


@router.get('/collections/{collection_id}/notes')
def list_notes(request: Request, response: Response, collection_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        owned_collection(session, owner, collection_id)
        result = [note_view(row) for row in session.scalars(select(Note).where(Note.owner_id == owner, Note.collection_id == collection_id).order_by(Note.updated_at.desc(), Note.id.desc()))]
    response.headers['Cache-Control'] = 'no-store'
    return result


@router.post('/collections/{collection_id}/notes', status_code=201, dependencies=[Depends(require_trusted_origin)])
def create_note(request: Request, collection_id: uuid.UUID, details: NoteBody, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        session.scalar(select(User.id).where(User.id == owner).with_for_update())
        owned_collection(session, owner, collection_id)
        validate_attachments(session, owner, collection_id, details)
        row = Note(id=uuid.uuid4(), owner_id=owner, collection_id=collection_id, title=details.title, markdown=details.markdown,
            analysis_ids=list(dict.fromkeys(str(value) for value in details.analysis_ids)),
            comparison_ids=list(dict.fromkeys(str(value) for value in details.comparison_ids)))
        session.add(row)
        session.flush()
        return note_view(row)


@router.get('/notes/{note_id}')
def read_note(request: Request, response: Response, note_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        row = session.scalar(select(Note).where(Note.id == note_id, Note.owner_id == owner))
        if row is None: raise HTTPException(404, 'Note not found.')
        result = note_view(row)
    response.headers['Cache-Control'] = 'no-store'
    return result


@router.patch('/notes/{note_id}', dependencies=[Depends(require_trusted_origin)])
def update_note(request: Request, note_id: uuid.UUID, details: NoteUpdate, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        session.scalar(select(User.id).where(User.id == owner).with_for_update())
        row = session.scalar(select(Note).where(Note.id == note_id, Note.owner_id == owner).with_for_update())
        if row is None: raise HTTPException(404, 'Note not found.')
        if row.version != details.version: raise HTTPException(409, 'This note changed in another window. Reload it before saving.')
        # Existing references remain editable as unavailable evidence after detach.
        # Newly attached references still require current collection membership.
        validate_attachments(session, owner, row.collection_id, details, retained_analysis_ids=row.analysis_ids)
        row.title, row.markdown = details.title, details.markdown
        row.analysis_ids = list(dict.fromkeys(str(value) for value in details.analysis_ids))
        row.comparison_ids = list(dict.fromkeys(str(value) for value in details.comparison_ids))
        row.version += 1
        row.updated_at = datetime.now(timezone.utc)
        return note_view(row)


@router.delete('/notes/{note_id}', status_code=204, dependencies=[Depends(require_trusted_origin)])
def delete_note(request: Request, note_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        row = session.scalar(select(Note).where(Note.id == note_id, Note.owner_id == owner).with_for_update())
        if row is None: raise HTTPException(404, 'Note not found.')
        session.delete(row)
    return Response(status_code=204, headers={'Cache-Control': 'no-store'})


def markdown_summary(view):
    if not view or not view['available']:
        return ['Evidence unavailable.']
    label = (view['title'] or view['filename'] or 'Source').replace('\n', ' ')
    lines = [f"Source: {label} · revision {view['revision_id']}"]
    if view.get('original_url'):
        lines.append('Original URL: <' + view['original_url'] + '>')
    referenced = set()
    for field, claims in (view['result'] or {}).items():
        for claim in claims:
            referenced.update(claim['references'])
            lines.append(f"- {field}: {claim['text']} " + ' '.join(f"[{view['analysis_id']}/{number}]" for number in claim['references']))
    # Export locators only, never whole imported passages.
    for block in view['evidence']:
        if block['number'] in referenced:
            lines.append(f"[{view['analysis_id']}/{block['number']}]: revision {view['revision_id']}, passage {block['number']}, page {block.get('page') or 'not reported'}")
    return lines


@router.get('/notes/{note_id}/export')
def export_note(request: Request, note_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        row = session.scalar(select(Note).where(Note.id == note_id, Note.owner_id == owner))
        if row is None: raise HTTPException(404, 'Note not found.')
        lines = ['# ' + row.title.replace('\n', ' '), '', row.markdown]
        if row.analysis_ids or row.comparison_ids:
            lines += ['', '## Selected findings', '', CAUTION]
        for identity in row.analysis_ids:
            lines += ['', *markdown_summary(summary_view(session, owner, identity, row.collection_id))]
        for identity in row.comparison_ids:
            comparison = session.scalar(select(Comparison).where(Comparison.id == uuid.UUID(identity), Comparison.owner_id == owner))
            if comparison is None:
                lines += ['', 'Comparison unavailable.']
            else:
                lines += ['', '### Comparison ' + identity]
                for selected in comparison.selections:
                    lines += ['', *markdown_summary(summary_view(session, owner, selected['analysis_id'], comparison.collection_id))]
        content = '\n'.join(lines) + '\n'
    return Response(content, media_type='text/markdown', headers={'Cache-Control': 'no-store', 'Content-Disposition': f'attachment; filename="research-note-{note_id}.md"'})
