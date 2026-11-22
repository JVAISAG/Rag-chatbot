"use client";
import { useEffect, useRef, useState } from 'react';
import { api, Comparison, ResearchNote, ResearchOptions } from '../lib/api';

export function Research({ collectionId, membershipVersion, onDirtyChange }: { collectionId: string; membershipVersion: number; onDirtyChange: (dirty: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ResearchOptions>({ summaries: [], comparisons: [] });
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [notes, setNotes] = useState<ResearchNote[]>([]);
  const [noteId, setNoteId] = useState('');
  const [title, setTitle] = useState('');
  const [markdown, setMarkdown] = useState('');
  const [analysisIds, setAnalysisIds] = useState<string[]>([]);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [version, setVersion] = useState(1);
  const [dirty, setDirty] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);
  const compareRequest = useRef(0);
  useEffect(() => { onDirtyChange(dirty); return () => onDirtyChange(false); }, [dirty, onDirtyChange]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    compareRequest.current++; setComparison(null);
    Promise.all([api.research(collectionId), api.notes(collectionId)]).then(([data, saved]) => {
      if (active) { setOptions(data); setNotes(saved); setSelected((old) => old.filter((id) => data.summaries.some((row) => row.analysis_id === id))); }
    }).catch((caught) => { if (active) setError(caught.message); });
    return () => { active = false; };
  }, [collectionId, open, reload, membershipVersion]);
  async function viewComparison(id: string) {
    const request = ++compareRequest.current;
    setComparison(null); setError('');
    if (!id) return;
    try { const result = await api.comparison(id); if (compareRequest.current === request) setComparison(result); }
    catch (caught) { if (compareRequest.current === request) setError(caught instanceof Error ? caught.message : 'Could not load comparison.'); }
  }
  async function compare() {
    setBusy(true); setError('');
    try {
      const result = await api.createComparison(collectionId, selected);
      setOptions((old) => ({ ...old, comparisons: [{ id: result.id, created_at: new Date().toISOString() }, ...old.comparisons] }));
      await viewComparison(result.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Comparison failed.'); }
    finally { setBusy(false); }
  }
  function loadNote(id: string) {
    const row = notes.find((item) => item.id === id);
    setNoteId(row?.id ?? ''); setTitle(row?.title ?? ''); setMarkdown(row?.markdown ?? '');
    setAnalysisIds(row?.analysis_ids ?? []); setComparisonIds(row?.comparison_ids ?? []);
    setVersion(row?.version ?? 1); setDirty(false); setConfirmDelete(false); setError('');
  }
  async function save() {
    setBusy(true); setError('');
    try {
      const body = { title, markdown, analysis_ids: analysisIds, comparison_ids: comparisonIds };
      const saved = noteId ? await api.updateNote(noteId, { ...body, version }) : await api.createNote(collectionId, body);
      setNotes((old) => [saved, ...old.filter((row) => row.id !== saved.id)]);
      setNoteId(saved.id); setVersion(saved.version); setTitle(saved.title); setDirty(false);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save note.'); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!noteId) return;
    setBusy(true); setError('');
    try { await api.deleteNote(noteId); setNotes((old) => old.filter((row) => row.id !== noteId)); loadNote(''); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not delete note.'); }
    finally { setBusy(false); }
  }
  async function exportMarkdown() {
    setBusy(true); setError('');
    try {
      const content = await api.exportNote(noteId);
      const url = URL.createObjectURL(new Blob([content], { type: 'text/markdown;charset=utf-8' }));
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `research-note-${noteId}.md`;
      document.body.appendChild(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not export note.'); }
    finally { setBusy(false); }
  }
  return <section aria-label="Research comparisons and notes"><button className="secondary-button" onClick={() => setOpen((value) => !value)}>{open ? 'Hide research tools' : 'Research comparisons and notes'}</button>
    {open && <><h3>Compare sources</h3><p>Choose saved summaries from 2–5 different sources. Complete source summaries first, then refresh this list.</p>
      <button className="text-button" onClick={() => setReload((value) => value + 1)}>Refresh research list</button>
      {error && <p role="alert">{error}</p>}
      <fieldset><legend>Summaries to compare</legend>{options.summaries.map((row) => <label key={row.analysis_id} style={{ display: 'block' }}><input type="checkbox" checked={selected.includes(row.analysis_id)} disabled={busy || (!selected.includes(row.analysis_id) && selected.length >= 5)} onChange={(event) => setSelected((old) => event.target.checked ? [...old, row.analysis_id] : old.filter((id) => id !== row.analysis_id))} /> {row.title || row.filename} · {new Date(row.created_at).toLocaleString()} · revision {row.revision_id}</label>)}</fieldset>
      <button className="secondary-button" disabled={busy || selected.length < 2} onClick={compare}>Compare selected summaries</button>
      <div className="field"><label htmlFor="saved-comparison">Saved comparisons</label><select id="saved-comparison" value={comparison?.id ?? ''} onChange={(event) => viewComparison(event.target.value)}><option value="">Choose a comparison</option>{options.comparisons.map((row) => <option key={row.id} value={row.id}>{new Date(row.created_at).toLocaleString()}</option>)}</select></div>
      {comparison && <article><p>{comparison.caution}</p><div style={{ overflowX: 'auto' }}><table><thead><tr><th>Dimension</th>{comparison.sources.map((row) => <th key={row.analysis_id}>{row.title || row.filename || 'Source'}<br />Revision {row.revision_id}</th>)}</tr></thead><tbody>{['question', 'approach', 'evidence', 'findings', 'limitations'].map((field) => <tr key={field}><th>{field}</th>{comparison.sources.map((row) => <td key={row.analysis_id}>{!row.available ? 'Evidence unavailable' : row.result?.[field]?.length ? row.result[field].map((claim, index) => <p key={index}>{claim.text} {claim.references.map((number) => <a key={number} href={`#compare-${comparison.id}-${row.analysis_id}-${number}`}>[{number}] </a>)}</p>) : 'Not reported in summary evidence'}</td>)}</tr>)}</tbody></table></div>{comparison.sources.flatMap((row) => row.evidence.map((block) => <details key={`${row.analysis_id}-${block.number}`} id={`compare-${comparison.id}-${row.analysis_id}-${block.number}`}><summary>{row.title || row.filename} [{block.number}]{block.page ? ` · Page ${block.page}` : ''}</summary><p style={{ whiteSpace: 'pre-wrap' }}>{block.text}</p></details>))}</article>}
      <h3>Research notes</h3><div className="field"><label htmlFor="saved-note">Saved notes</label><select id="saved-note" disabled={dirty || busy} value={noteId} onChange={(event) => loadNote(event.target.value)}><option value="">New note</option>{notes.map((row) => <option key={row.id} value={row.id}>{row.title}</option>)}</select></div>
      <form className="auth-form" onSubmit={(event) => { event.preventDefault(); save(); }}><div className="field"><label htmlFor="note-title">Note title</label><input id="note-title" disabled={busy} required maxLength={200} value={title} onChange={(event) => { setTitle(event.target.value); setDirty(true); }} /></div><div className="field"><label htmlFor="note-markdown">Note Markdown</label><textarea id="note-markdown" disabled={busy} rows={10} maxLength={50000} value={markdown} onChange={(event) => { setMarkdown(event.target.value); setDirty(true); }} /></div>
      <button type="button" className="secondary-button" disabled={!selected.length || busy} onClick={() => { setAnalysisIds((old) => Array.from(new Set([...old, ...selected])).slice(0, 10)); setDirty(true); }}>Attach selected summary findings</button>
      <button type="button" className="secondary-button" disabled={!comparison || busy} onClick={() => { if (comparison) setComparisonIds((old) => Array.from(new Set([...old, comparison.id])).slice(0, 5)); setDirty(true); }}>Attach current comparison</button>
      <p>Attached summaries: {analysisIds.length} · comparisons: {comparisonIds.length}</p><button type="button" className="text-button" disabled={busy} onClick={() => { setAnalysisIds([]); setComparisonIds([]); setDirty(true); }}>Clear attachments</button>
      <button disabled={busy || !title.trim() || (!dirty && !!noteId)}>Save note</button><button type="button" className="secondary-button" disabled={busy || !dirty} onClick={() => loadNote(noteId)}>Discard unsaved edits</button></form>
      {noteId && !dirty && <button className="secondary-button" disabled={busy} onClick={exportMarkdown}>Export Markdown</button>}
      {noteId && <button className="text-button" disabled={busy || dirty} onClick={() => setConfirmDelete(true)}>Delete note</button>}
      {confirmDelete && <div role="alert"><p>Permanently delete this research note?</p><button disabled={busy} onClick={remove}>Confirm note deletion</button><button className="text-button" onClick={() => setConfirmDelete(false)}>Cancel</button></div>}
    </>}
  </section>;
}
