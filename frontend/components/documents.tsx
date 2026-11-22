"use client";
import { useEffect, useRef, useState } from "react";
import { api, Source, SearchHit, ReadingStatus } from "../lib/api";
import { Questions } from "./questions";
import { Summaries } from "./summaries";
import { Research } from "./research";
const READING_LABELS = { unread: 'Unread', reading: 'Reading', read: 'Read' };

export function Documents({ collectionId, name, close, onDirtyChange }: { collectionId: string; name: string; close: () => void; onDirtyChange: (dirty: boolean) => void }) {
  const [items, setItems] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [pages, setPages] = useState<{ text: string; page: number | null }[]>([]);
  const [readerName, setReaderName] = useState("");
  const [readerLink, setReaderLink] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [searchSources, setSearchSources] = useState<string[]>([]);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searched, setSearched] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [authors, setAuthors] = useState("");
  const [publicationDate, setPublicationDate] = useState("");
  const [tags, setTags] = useState('');
  const [readingStatus, setReadingStatus] = useState<ReadingStatus>('unread');
  const [editingRevision, setEditingRevision] = useState<string | null>(null);
  const [savingMetadata, setSavingMetadata] = useState(false);
  const [library, setLibrary] = useState<{ id: string; filename: string; title: string | null }[] | null>(null);
  const [selectedSource, setSelectedSource] = useState("");
  const [changingMembership, setChangingMembership] = useState(false);
  const [membershipVersion, setMembershipVersion] = useState(0);
  const [researchDirty, setResearchDirty] = useState(false);
  useEffect(() => { onDirtyChange(researchDirty); return () => onDirtyChange(false); }, [researchDirty, onDirtyChange]);
  const [serviceStatus, setServiceStatus] = useState('');
  const [deleting, setDeleting] = useState<Source | null>(null);
  const [articleUrl, setArticleUrl] = useState("");
  const [importJob, setImportJob] = useState<string | null>(null);
  const readerRequest = useRef(0);
  const searchRequest = useRef(0);
  const revisions = useRef<Record<string, string | null>>({});
  async function search() {
    const requestId = ++searchRequest.current;
    setBusy(true); setError(""); setSearched(false); setHits([]);
    try { const results = await api.search(collectionId, query, searchSources); if (requestId === searchRequest.current) { setHits(results); setSearched(true); } }
    catch (caught) { if (requestId === searchRequest.current) setError(caught instanceof Error ? caught.message : "Search failed."); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const data = await api.sources(collectionId);
        if (!active) return;
        if (data.some((item) => item.id in revisions.current && revisions.current[item.id] !== item.active_revision_id)) {
          readerRequest.current++; searchRequest.current++; setPages([]); setReaderName(""); setHits([]); setSearched(false);
        }
        revisions.current = Object.fromEntries(data.map((item) => [item.id, item.active_revision_id]));
        setItems(data); setError("");
        if (data.some((item) => ["pending", "running", "indexing"].includes(item.status) || ["processing", "indexing"].includes(item.replacement_status ?? "") || ["pending", "running"].includes(item.refresh_status ?? ""))) timer = setTimeout(load, 2000);
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : "Could not load documents."); }
    }
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [collectionId, attempt]);
  useEffect(() => {
    if (!importJob) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await api.importStatus(importJob!);
        if (!active) return;
        if (result.status === "completed") { setImportJob(null); setArticleUrl(""); setAttempt((value) => value + 1); }
        else if (result.status === "failed") { setImportJob(null); setError("Could not import this article. Check the URL and try again."); }
        else timer = setTimeout(poll, 2000);
      } catch (caught) { if (active) { setImportJob(null); setError(caught instanceof Error ? caught.message : "Could not check the import."); } }
    }
    poll();
    return () => { active = false; clearTimeout(timer); };
  }, [importJob]);
  async function importArticle() {
    if (!articleUrl.trim() || importJob) return;
    setBusy(true); setError("");
    try { const result = await api.importUrl(collectionId, articleUrl.trim()); setImportJob(result.job_id); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not start the import."); }
    finally { setBusy(false); }
  }
  async function upload(file?: File) {
    if (!file) return;
    setBusy(true); setError("");
    try { await api.upload(collectionId, file); setAttempt((value) => value + 1); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Upload failed."); }
    finally { setBusy(false); }
  }
  async function replace(item: Source, file?: File) {
    if (!file) return;
    setBusy(true); setError("");
    try { await api.replaceSource(item.id, file); setAttempt((value) => value + 1); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Replacement failed."); }
    finally { setBusy(false); }
  }
  async function refresh(item: Source) {
    setBusy(true); setError("");
    try { await api.refreshSource(item.id); setAttempt((value) => value + 1); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not refresh the article."); }
    finally { setBusy(false); }
  }
  async function deleteDocument() {
    if (!deleting) return;
    setBusy(true); setError("");
    try {
      await api.deleteSource(deleting.id);
      readerRequest.current++; searchRequest.current++;
      setPages([]); setReaderName(""); setHits([]); setSearched(false);
      setEditing(null); setLibrary(null); setDeleting(null);
      setMembershipVersion((value) => value + 1); setAttempt((value) => value + 1);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not delete the document."); }
    finally { setBusy(false); }
  }
  async function read(item: Source) {
    const requestId = ++readerRequest.current;
    try { const data = await api.sourceText(item.id); if (requestId === readerRequest.current) { setPages(data.pages); setReaderName(data.filename || item.filename); const revision = data.revision_id || item.active_revision_id; setReaderLink(revision ? `/api/v2/sources/${item.id}/content?revision_id=${revision}` : ''); } }
    catch (caught) { if (requestId === readerRequest.current) setError(caught instanceof Error ? caught.message : "Could not read document."); }
  }
  async function retryIndex(item: Source) {
    try { await api.retryIndex(item.id); setAttempt((value) => value + 1); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Retry failed."); }
  }
  function editMetadata(item: Source) {
    setEditing(item.id); setTitle(item.title ?? ""); setAuthors(item.authors ?? "");
    setPublicationDate(item.publication_date ?? ""); setError("");
    setTags((item.tags ?? []).join(', ')); setReadingStatus(item.reading_status ?? 'unread');
    setEditingRevision(item.active_revision_id ?? null);
  }
  async function saveMetadata() {
    if (!editing || savingMetadata) return;
    setSavingMetadata(true); setError("");
    try {
      await api.updateSource(editing, { title: title.trim() || null, authors: authors.trim() || null, publication_date: publicationDate || null,
        tags: tags.split(',').map((tag) => tag.trim()).filter(Boolean), reading_status: readingStatus, expected_revision_id: editingRevision });
      setEditing(null); setAttempt((value) => value + 1);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not save document details."); }
    finally { setSavingMetadata(false); }
  }
  async function showLibrary() {
    setChangingMembership(true); setError("");
    try { setLibrary(await api.library()); setSelectedSource(""); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Could not load your library."); }
    finally { setChangingMembership(false); }
  }
  async function changeMembership(sourceId: string, attach: boolean) {
    setChangingMembership(true); setError("");
    try {
      if (attach) await api.attachSource(collectionId, sourceId);
      else await api.detachSource(collectionId, sourceId);
      if (!attach) { readerRequest.current++; setPages([]); setReaderName(""); }
      if (!attach && editing === sourceId) setEditing(null);
      searchRequest.current++; setHits([]); setSearched(false); setMembershipVersion((value) => value + 1);
      setLibrary(null); setSelectedSource(""); setAttempt((value) => value + 1);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not update the collection."); }
    finally { setChangingMembership(false); }
  }
  return <section className="collection-editor" aria-label="Collection documents">
    <div className="editor-heading"><h2>Documents in {name}</h2><button className="close-button" onClick={() => { if (!researchDirty || window.confirm('Discard unsaved research note edits?')) close(); }} aria-label="Close documents">×</button></div>
    <button className="text-button" onClick={async () => { try { const health = await api.status(); setServiceStatus(`Database: ${health.database ? 'ready' : 'unavailable'} · Worker: ${health.worker ? 'recent heartbeat' : 'no recent heartbeat'} · Storage: ${health.storage ? 'writable' : 'check storage'} · Model ${health.model}: ${health.model_available ? 'installed' : 'unavailable'}`); } catch (caught) { setServiceStatus(caught instanceof Error ? caught.message : 'Could not check services.'); } }}>Check workspace services</button>{serviceStatus && <p role="status">{serviceStatus}</p>}
    <div className="field"><label htmlFor="document-file">Upload a document</label><input id="document-file" type="file" accept=".pdf,.docx,.txt,.md" disabled={busy} onChange={(event) => { upload(event.target.files?.[0]); event.target.value = ""; }} /><p className="field-hint">PDF, DOCX, TXT, or Markdown. Up to 10 MB per file.</p></div>
    <form className="auth-form" onSubmit={(event) => { event.preventDefault(); importArticle(); }}><div className="field"><label htmlFor="article-url">Import an article URL</label><input id="article-url" type="url" required maxLength={4096} value={articleUrl} onChange={(event) => setArticleUrl(event.target.value)} placeholder="https://example.com/article" /></div><button className="secondary-button" disabled={busy || !!importJob || !articleUrl.trim()}>Import article</button></form>
    {importJob && <p role="status">Importing article…</p>}
    {busy && <p role="status">Working…</p>}
    {error && <p className="error-message" role="alert">{error} <button onClick={() => setAttempt((value) => value + 1)}>Retry</button></p>}
    <button className="secondary-button" disabled={changingMembership} onClick={showLibrary}>Add from library</button>
    <div className="field"><label htmlFor="delete-source">Delete a document from your library</label><select id="delete-source" value={deleting?.id ?? ""} disabled={busy} onChange={(event) => setDeleting(items.find((item) => item.id === event.target.value) ?? null)}><option value="">Choose a document</option>{items.map((item) => <option key={item.id} value={item.id}>{item.title || item.filename}</option>)}</select></div>
    {deleting && <div role="alert"><p>Delete {deleting.title || deleting.filename} from every collection? Its files will be removed and saved references will become unavailable.</p><button disabled={busy} onClick={deleteDocument}>Delete permanently</button> <button className="secondary-button" disabled={busy} onClick={() => setDeleting(null)}>Cancel deletion</button></div>}
    {library && <div className="field"><label htmlFor="library-source">Choose a document</label><select id="library-source" value={selectedSource} onChange={(event) => setSelectedSource(event.target.value)}><option value="">Choose a document</option>{library.filter((item) => !items.some((current) => current.id === item.id)).map((item) => <option key={item.id} value={item.id}>{item.title || item.filename}</option>)}</select><button className="secondary-button" disabled={!selectedSource || changingMembership} onClick={() => changeMembership(selectedSource, true)}>Add document</button></div>}
    <ul>{items.map((item) => <li key={item.id} style={{ padding: "12px 0" }}>{item.title || item.filename} — {item.status === "extracted" ? "Text extracted" : item.status}{" "}{["extracted", "indexing", "indexing_failed", "ready"].includes(item.status) && <button className="text-button" onClick={() => read(item)}>Read text</button>} <button className="text-button" disabled={savingMetadata} onClick={() => editMetadata(item)}>Edit details</button> <button className="text-button" disabled={changingMembership || savingMetadata} onClick={() => changeMembership(item.id, false)}>Remove from collection</button>{item.original_url && <p><a href={item.original_url} target="_blank" rel="noopener noreferrer">Open original article</a>{" "}<button className="text-button" disabled={busy || item.status !== "ready" || ["pending", "running"].includes(item.refresh_status ?? "") || ["processing", "indexing"].includes(item.replacement_status ?? "")} onClick={() => refresh(item)}>Refresh article</button></p>}{item.original_url && (["pending", "running"].includes(item.refresh_status ?? "") ? <p role="status">Checking the article for updates; the current version remains available.</p> : item.refresh_status === "failed" ? <p role="status">Article refresh failed. The current version is unchanged.</p> : item.refresh_outcome === "unchanged" ? <p role="status">The article has not changed.</p> : item.refresh_outcome === "duplicate" ? <p role="status">The updated article matches another document in your library. Both remain unchanged.</p> : item.refresh_outcome === "conflict" ? <p role="status">Another update is processing. Try the refresh again later.</p> : null)}{item.status === "ready" && <div className="field"><label htmlFor={`replace-${item.id}`}>Replace {item.title || item.filename}</label><input id={`replace-${item.id}`} type="file" accept=".pdf,.docx,.txt,.md" disabled={busy || ["processing", "indexing"].includes(item.replacement_status ?? "") || ["pending", "running"].includes(item.refresh_status ?? "")} onChange={(event) => { replace(item, event.target.files?.[0]); event.target.value = ""; }} /></div>}{item.replacement_status === "processing" || item.replacement_status === "indexing" ? <p role="status">Replacement is processing; the current document remains available.</p> : item.replacement_status === "failed" ? <p role="status">Update failed. The current document is unchanged; refresh again or choose another file.</p> : null}{item.authors && <p>Authors: {item.authors}</p>}{item.publication_date && <p>Published: {item.publication_date}</p>}
      <p className="field-hint">Reading progress: {READING_LABELS[item.reading_status ?? 'unread']}</p>
      {item.tags && item.tags.length > 0 && <p className="field-hint">Tags: {item.tags.join(' · ')}</p>}
    </li>)}</ul>
    {editing && <form className="auth-form" onSubmit={(event) => { event.preventDefault(); saveMetadata(); }}>
      <h3>Edit document details</h3>
      <p className="field-hint">These details apply wherever this document appears in your collections.</p>
      <div className="field"><label htmlFor="source-title">Title</label><input id="source-title" value={title} maxLength={500} disabled={savingMetadata} onChange={(event) => setTitle(event.target.value)} /></div>
      <div className="field"><label htmlFor="source-authors">Authors</label><input id="source-authors" value={authors} maxLength={1000} disabled={savingMetadata} onChange={(event) => setAuthors(event.target.value)} /></div>
      <div className="field"><label htmlFor="source-publication-date">Publication date</label><input id="source-publication-date" type="date" value={publicationDate} disabled={savingMetadata} onChange={(event) => setPublicationDate(event.target.value)} /></div>
      <div className="field"><label htmlFor="source-tags">Tags</label><input id="source-tags" value={tags} maxLength={680} disabled={savingMetadata} onChange={(event) => setTags(event.target.value)} /><p className="field-hint">Up to 20 comma-separated tags, 32 characters each.</p></div>
      <div className="field"><label htmlFor="source-reading-status">Reading progress</label><select id="source-reading-status" value={readingStatus} disabled={savingMetadata} onChange={(event) => setReadingStatus(event.target.value as ReadingStatus)}><option value="unread">Unread</option><option value="reading">Reading</option><option value="read">Read</option></select><p className="field-hint">Changed revisions become unread. Tags are preserved.</p></div>
      <button disabled={savingMetadata}>Save details</button> <button type="button" className="secondary-button" disabled={savingMetadata} onClick={() => setEditing(null)}>Cancel</button>
    </form>}
    {items.filter((item) => item.status === "indexing_failed").map((item) => <button className="secondary-button" key={item.id} onClick={() => retryIndex(item)}>Retry indexing {item.filename}</button>)}
    <form onSubmit={(event) => { event.preventDefault(); search(); }} className="auth-form">
      <div className="field"><label htmlFor="collection-search">Search this collection</label><input id="collection-search" value={query} onChange={(event) => setQuery(event.target.value)} required maxLength={2000} /></div>
      <fieldset><legend>Search selected documents (none means the whole collection)</legend>{items.filter((row) => row.status === 'ready').map((row) => <label key={row.id} style={{ display: 'block' }}><input type="checkbox" checked={searchSources.includes(row.id)} disabled={!searchSources.includes(row.id) && searchSources.length >= 20} onChange={(event) => { searchRequest.current++; setHits([]); setSearched(false); setSearchSources((old) => event.target.checked ? [...old, row.id] : old.filter((id) => id !== row.id)); }} />{row.title || row.filename}</label>)}</fieldset>
      {searchSources.some((id) => !items.some((row) => row.id === id)) && <p role="status">A selected search document is unavailable. <button type="button" onClick={() => setSearchSources([])}>Reset to the whole collection</button></p>}
      <button className="secondary-button" disabled={busy || !query.trim() || searchSources.some((id) => !items.some((row) => row.id === id))}>Search documents</button>
    </form>
    {searched && hits.length === 0 && <p role="status">No searchable passages found. Documents must finish indexing first.</p>}
    {hits.map((hit) => <article key={hit.id}><h3>{hit.metadata.source}{hit.metadata.page ? ` · Page ${hit.metadata.page}` : ""}</h3><p style={{ whiteSpace: "pre-wrap" }}>{hit.text}</p></article>)}
    <div className="reading-workspace">
      <section className="source-reader" aria-label="Source reader">
        <h3>Source reader</h3>
        {readerName ? <article><h4>{readerName}</h4>{readerLink && <a href={readerLink} target="_blank" rel="noopener noreferrer">Open original file</a>}<div className="source-reader-pages" role="region" aria-label="Extracted pages" tabIndex={0}>{pages.map((page, index) => <section key={index}>{page.page && <h4>Page {page.page}</h4>}<p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{page.text}</p></section>)}</div></article> : <p className="field-hint">Choose Read text on a document to inspect its pages while asking questions.</p>}
      </section>
      <Questions collectionId={collectionId} membershipVersion={membershipVersion} sources={items} />
    </div>
    <Summaries sources={items} />
    <Research collectionId={collectionId} membershipVersion={membershipVersion} onDirtyChange={setResearchDirty} />
  </section>;
}
