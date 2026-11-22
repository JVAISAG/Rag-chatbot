"use client";
import { useEffect, useRef, useState } from "react";
import { api, QuestionTurn, Source } from "../lib/api";
const NO_SOURCES: Source[] = [];
const TIMING_STAGES = [['initial_queue_seconds', 'Initial queue wait'], ['retrieval_and_rewrite_seconds', 'Retrieval and follow-up rewrite'], ['generation_and_repair_seconds', 'Latest generation and evidence checks']] as const;

export function Questions({ collectionId, membershipVersion = 0, sources = NO_SOURCES }: { collectionId: string; membershipVersion?: number; sources?: Source[] }) {
  const [conversations, setConversations] = useState<{ id: string; created_at: string; source_ids?: string[] | null }[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [turns, setTurns] = useState<QuestionTurn[]>([]);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [listAttempt, setListAttempt] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [turnsLoading, setTurnsLoading] = useState(false);
  const requestKey = useRef<{ conversation: string; question: string; key: string } | null>(null);
  useEffect(() => {
    let active = true;
    setLoaded(false);
    api.conversations(collectionId).then((items) => {
      if (active) { setConversations(items); setSelected(items.at(-1)?.id ?? ""); setLoaded(true); }
    }).catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "Could not load conversations."); });
    return () => { active = false; };
  }, [collectionId, listAttempt]);
  useEffect(() => {
    setTurns([]);
    if (!selected) { setTurnsLoading(false); return; }
    setTurnsLoading(true);
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const data = await api.conversation(selected);
        if (!active) return;
        setTurns(data.turns); setTurnsLoading(false);
        if (data.turns.some((turn) => turn.status === "pending")) timer = setTimeout(load, 2000);
      } catch (caught) { if (active) { setTurnsLoading(false); setError(caught instanceof Error ? caught.message : "Could not load answers."); } }
    }
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [selected, attempt, membershipVersion]);
  async function ask() {
    setBusy(true); setError("");
    try {
      let identity = selected;
      if (!identity) {
        const created = await api.newConversation(collectionId, selectedSources);
        identity = created.id;
        setConversations((items) => [...items, { id: identity, created_at: new Date().toISOString(), source_ids: selectedSources.length ? selectedSources : null }]);
        setSelected(identity);
      }
      if (requestKey.current?.conversation !== identity || requestKey.current.question !== question) requestKey.current = { conversation: identity, question, key: crypto.randomUUID() };
      await api.ask(identity, question, requestKey.current.key);
      requestKey.current = null;
      setTurnsLoading(true);
      setQuestion(""); setAttempt((value) => value + 1);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not submit the question."); }
    finally { setBusy(false); }
  }
  return <section aria-label="Collection questions" className="questions-panel">
    <h3>Ask your documents</h3>
    <p className="field-hint">Answers use documents that have finished indexing in this collection. Check the cited passages.</p>
    <div className="field"><label htmlFor="conversation">Conversation</label><select id="conversation" value={selected} disabled={busy} onChange={(event) => { setSelected(event.target.value); setError(""); }}>
      <option value="">New conversation</option>{conversations.map((item, index) => <option key={item.id} value={item.id}>Conversation {index + 1}</option>)}
    </select></div>
    {!selected && <fieldset><legend>Limit this new conversation to selected documents (none means the whole collection)</legend>{sources.filter((row) => row.status === 'ready').map((row) => <label key={row.id} style={{ display: 'block' }}><input type="checkbox" checked={selectedSources.includes(row.id)} disabled={busy || (!selectedSources.includes(row.id) && selectedSources.length >= 20)} onChange={(event) => setSelectedSources((old) => event.target.checked ? [...old, row.id] : old.filter((id) => id !== row.id))} />{row.title || row.filename}</label>)}</fieldset>}
    {selected && <p className="field-hint">Conversation scope: {conversations.find((row) => row.id === selected)?.source_ids?.length ? 'selected documents saved with this conversation' : 'this collection'}.</p>}
    {!selected && selectedSources.some((id) => !sources.some((row) => row.id === id)) && <p role="status">A selected question document is unavailable. <button type="button" onClick={() => setSelectedSources([])}>Reset question scope to the whole collection</button></p>}
    {turns.map((turn) => <article key={turn.id} style={{ borderBottom: "1px solid #dce5d9", padding: "16px 0" }}>
      <h4>{turn.question}</h4><p style={{ whiteSpace: "pre-wrap" }}>{turn.status === "pending" ? "Preparing an answer…" : turn.status === "failed" ? "The answer could not be generated. Check that the worker, local models, and Ollama are running." : turn.answer}</p>
      {TIMING_STAGES.some(([key]) => typeof turn.timings?.[key] === 'number' && Number.isFinite(turn.timings[key])) && <details><summary>Processing times</summary><dl>{TIMING_STAGES.map(([key, label]) => {
        const seconds = turn.timings?.[key];
        return typeof seconds === 'number' && Number.isFinite(seconds) ? <div key={key}><dt>{label}</dt><dd>{seconds.toFixed(1)} s</dd></div> : null;
      })}</dl><p className="field-hint">Cold model loading can increase these times. Recorded stages may come from different retry attempts.</p></details>}
      {turn.evidence.map((item) => <details key={item.number}><summary>[{item.number}] {item.metadata.source}{item.metadata.page ? ` · Page ${item.metadata.page}` : ""}{!item.available ? " · Evidence unavailable" : ""}</summary><p style={{ whiteSpace: "pre-wrap" }}>{item.text}</p>{item.available && item.metadata.source_id && item.metadata.revision_id && <a href={`/api/v2/sources/${item.metadata.source_id}/content?revision_id=${item.metadata.revision_id}${item.metadata.page ? `#page=${item.metadata.page}` : ''}`} target="_blank" rel="noopener noreferrer">Open cited original</a>}</details>)}
    </article>)}
    {error && <p role="alert" className="error-message">{error} <button onClick={() => { setError(""); if (!loaded) setListAttempt((value) => value + 1); else setAttempt((value) => value + 1); }}>Refresh answers</button></p>}
    <form className="auth-form" onSubmit={(event) => { event.preventDefault(); ask(); }} style={{ marginTop: 16 }}>
      <div className="field"><label htmlFor="document-question">Your question</label><textarea id="document-question" value={question} disabled={busy} onChange={(event) => setQuestion(event.target.value)} required maxLength={2000} /></div>
      <button className="primary-button" disabled={busy || !loaded || turnsLoading || !question.trim() || (!selected && selectedSources.some((id) => !sources.some((row) => row.id === id))) || turns.some((turn) => turn.status === "pending")}>{busy ? "Submitting…" : "Ask documents"}</button>
    </form>
  </section>;
}
