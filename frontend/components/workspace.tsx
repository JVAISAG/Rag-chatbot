"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError, Collection } from "../lib/api";
import { Brand } from "./brand";
import { Documents } from "./documents";

type Props = { onSignedOut: (expired: boolean) => void };

function CollectionIcon() {
  return <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4.5 6.5h5l1.7 1.8h8.3v9.5a1.7 1.7 0 0 1-1.7 1.7H6.2a1.7 1.7 0 0 1-1.7-1.7V6.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /><path d="M4.5 8.3h15" stroke="currentColor" strokeWidth="1.5" /></svg>;
}

function BookIllustration() {
  return <svg viewBox="0 0 102 88" fill="none" aria-hidden="true"><rect x="15" y="20" width="54" height="52" rx="4" fill="#E8ECDD" stroke="#9AAE99" /><path d="M22 28h36M22 34h27M22 42h36M22 48h31" stroke="#9AAE99" strokeWidth="2" strokeLinecap="round" /><rect x="40" y="12" width="47" height="61" rx="4" fill="#FAFAF4" stroke="#64816D" /><path d="M48 23h23M48 31h30M48 37h30M48 43h24" stroke="#A5B7A7" strokeWidth="2" strokeLinecap="round" /><path d="M48 55h13" stroke="#C4885E" strokeWidth="2" strokeLinecap="round" /><circle cx="75" cy="62" r="8" fill="#DCE9DC" /><path d="M75 58v8M71 62h8" stroke="#527960" strokeWidth="1.5" strokeLinecap="round" /></svg>;
}

export function Workspace({ onSignedOut }: Props) {
  const [opened, setOpened] = useState<Collection | null>(null);
  const [documentsDirty, setDocumentsDirty] = useState(false);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Collection | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const nameInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api.collections().then((items) => {
      if (active) { setCollections(items); setLoaded(true); }
    }).catch((caught: unknown) => {
      if (!active) return;
      setLoaded(false);
      if (caught instanceof ApiError && caught.status === 401) onSignedOut(true);
      else setError(caught instanceof Error ? caught.message : "Could not load your collections.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // The callback belongs to the current session; explicit retries reload data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadAttempt]);

  useEffect(() => {
    if (editorOpen) nameInput.current?.focus();
  }, [editorOpen]);

  function handleError(caught: unknown, forForm = false) {
    if (caught instanceof ApiError && caught.status === 401) {
      onSignedOut(true);
      return;
    }
    const message = caught instanceof Error ? caught.message : "Something went wrong. Please try again.";
    if (forForm) setFormError(message);
    else setError(message);
  }

  function openEditor(collection?: Collection) {
    setEditing(collection ?? null);
    setName(collection?.name ?? "");
    setDescription(collection?.description ?? "");
    setFormError("");
    setError("");
    setEditorOpen(true);
    if (editorOpen) nameInput.current?.focus();
  }

  async function saveCollection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    const trimmedName = name.trim();
    const trimmedDescription = description.trim();
    if (!trimmedName) { setFormError("Give your collection a name."); return; }
    if (Array.from(trimmedName).length > 100) { setFormError("Collection names can be up to 100 characters."); return; }
    if (Array.from(trimmedDescription).length > 2000) { setFormError("Descriptions can be up to 2,000 characters."); return; }
    setBusy(true);
    try {
      if (editing) {
        const updated = await api.updateCollection(editing.id, trimmedName, trimmedDescription || null);
        setCollections((items) => items.map((item) => item.id === updated.id ? updated : item));
      } else {
        const created = await api.createCollection(trimmedName, trimmedDescription || null);
        setCollections((items) => [created, ...items]);
      }
      setEditorOpen(false);
      setEditing(null);
    } catch (caught) {
      handleError(caught, true);
    } finally {
      setBusy(false);
    }
  }

  async function removeCollection(collection: Collection) {
    if (opened?.id === collection.id && documentsDirty && !window.confirm('Discard unsaved research note edits?')) return;
    if (!window.confirm(`Delete “${collection.name}”? This cannot be undone.`)) return;
    setError("");
    setBusy(true);
    try {
      await api.deleteCollection(collection.id);
      setCollections((items) => items.filter((item) => item.id !== collection.id));
      if (opened?.id === collection.id) setOpened(null);
      if (editing?.id === collection.id) { setEditorOpen(false); setEditing(null); }
    } catch (caught) {
      handleError(caught);
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    if (documentsDirty && !window.confirm('Discard unsaved research note edits and sign out?')) return;
    setSigningOut(true);
    setError("");
    try {
      await api.logout();
      onSignedOut(false);
    } catch (caught) {
      handleError(caught);
      setSigningOut(false);
    }
  }

  return (
    <div className="workspace-shell">
      <aside className="sidebar">
        <Brand />
        <div className="sidebar-section-label">WORKSPACE</div>
        <nav aria-label="Workspace navigation">
          <div className="nav-current" aria-current="page"><CollectionIcon /><span>Collections</span><span className="nav-count">{loaded ? collections.length : "—"}</span></div>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note"><span className="note-symbol">✳</span><p>A little more space<br /><strong>for good ideas.</strong></p></div>
          <button className="signout-button" onClick={signOut} disabled={signingOut}><span className="account-avatar" aria-hidden="true">R</span><span><strong>Your workspace</strong><small>{signingOut ? "Signing out…" : "Sign out"}</small></span><span className="signout-arrow" aria-hidden="true">↗</span></button>
        </div>
      </aside>
      <main className="workspace-main">
        <div className="mobile-bar"><Brand /><button onClick={signOut} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button></div>
        <div className="workspace-content">
          <div className="breadcrumb">WORKSPACE <span>/</span> COLLECTIONS</div>
          <div className="workspace-heading">
            <div><div className="eyebrow"><span className="eyebrow-dot" /> YOUR PRIVATE LIBRARY</div><h1>Your collections<span>.</span></h1><p>Give your research a little room to breathe.</p></div>
            <button className="primary-button new-button" onClick={() => openEditor()} disabled={busy || !loaded}><span aria-hidden="true">＋</span> New collection</button>
          </div>
          {opened && <Documents key={opened.id} collectionId={opened.id} name={opened.name} close={() => setOpened(null)} onDirtyChange={setDocumentsDirty} />}
          {editorOpen && <section className="collection-editor" aria-labelledby="editor-heading">
            <div className="editor-heading"><div><span className="section-kicker">{editing ? "MAKE A CHANGE" : "A NEW SPACE"}</span><h2 id="editor-heading">{editing ? "Edit collection" : "Create a collection"}</h2></div><button type="button" className="close-button" aria-label="Close collection form" onClick={() => setEditorOpen(false)} disabled={busy}>×</button></div>
            <form onSubmit={saveCollection}>
              <div className="field"><label htmlFor="collection-name">Name</label><input ref={nameInput} id="collection-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Language models" required /><p className="field-hint">Up to 100 characters.</p></div>
              <div className="field"><label htmlFor="collection-description">Description <span>optional</span></label><textarea id="collection-description" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What are you exploring?" rows={3} /><p className="field-hint">Up to 2,000 characters.</p></div>
              {formError && <p className="form-message error-message" role="alert">{formError}</p>}
              <div className="form-actions"><button className="primary-button" disabled={busy} type="submit">{busy ? "Saving…" : editing ? "Save changes" : "Create collection"}<span aria-hidden="true">↗</span></button><button className="text-button" type="button" disabled={busy} onClick={() => setEditorOpen(false)}>Cancel</button></div>
            </form>
          </section>}
          <div className="section-heading"><div><span className="section-kicker">THE LIBRARY</span><h2>Collections</h2></div><span className="section-count">{loading || !loaded ? "—" : `${collections.length} ${collections.length === 1 ? "collection" : "collections"}`}</span></div>
          {error && <div className="inline-error" role="alert">{error}<button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
          {loading ? <div className="loading-state" role="status">Loading your collections…</div> : !loaded ? (
            <div className="loading-state"><button className="secondary-button" onClick={() => setLoadAttempt((value) => value + 1)}>Try again</button></div>
          ) : collections.length === 0 ? (
            <section className="empty-state"><BookIllustration /><span className="section-kicker">A FRESH PAGE</span><h3>It starts with a collection.</h3><p>Create a space for a subject, a project, or anything you’re curious about.</p><button className="secondary-button" onClick={() => openEditor()} disabled={busy}>＋ <span>Create your first collection</span></button></section>
          ) : (
            <div className="collection-grid">
              {collections.map((collection, index) => <article className="collection-card" key={collection.id}>
                <div className="collection-card-top"><span className="collection-icon"><CollectionIcon /></span><span className="collection-number">{String(index + 1).padStart(2, "0")}</span></div>
                <h3>{collection.name}</h3><p>{collection.description || "No description added yet."}</p>
                <button className="secondary-button" onClick={() => { if (opened?.id === collection.id || !documentsDirty || window.confirm('Discard unsaved research note edits?')) setOpened(collection); }}>Open documents</button>
                <div className="collection-card-footer"><span>CREATED {new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(new Date(collection.created_at)).toUpperCase()}</span><div><button onClick={() => openEditor(collection)} disabled={busy}>Edit</button><button className="delete-button" onClick={() => removeCollection(collection)} disabled={busy}>Delete</button></div></div>
              </article>)}
            </div>
          )}
          <div className="workspace-footer"><span>MADE FOR THOUGHTFUL WORK</span><span>✳</span></div>
        </div>
      </main>
    </div>
  );
}
