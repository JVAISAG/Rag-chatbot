"use client";
import { useEffect, useState } from "react";
import { api, Source, Summary } from "../lib/api";

export function Summaries({ sources }: { sources: Source[] }) {
  const [source, setSource] = useState("");
  const [saved, setSaved] = useState<{ id: string; created_at: string }[]>([]);
  const [selected, setSelected] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (source && !sources.some((item) => item.id === source)) setSource("");
  }, [source, sources]);
  useEffect(() => {
    let active = true;
    setSaved([]); setSummary(null); setSelected(""); setError("");
    setLoading(!!source);
    if (source) api.summaries(source).then((data) => { if (active) setSaved(data); }).catch((caught) => { if (active) setError(caught.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [source]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setSummary(null);
    async function load() {
      try {
        const data = await api.summary(selected);
        if (!active) return;
        setSummary(data);
        if (data.status === "pending") timer = setTimeout(load, 2000);
      } catch (caught) { if (active) setError(caught instanceof Error ? caught.message : "Could not load the summary."); }
    }
    if (selected) load();
    return () => { active = false; clearTimeout(timer); };
  }, [selected]);
  async function create() {
    setBusy(true); setError("");
    try {
      const result = await api.createSummary(source);
      setSaved((value) => value.some((item) => item.id === result.id) ? value : [{ id: result.id, created_at: new Date().toISOString() }, ...value]);
      setSelected(result.id);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Could not start the summary."); }
    finally { setBusy(false); }
  }
  return <section aria-label="Source summaries"><h3>Source summaries</h3>
    <div className="field"><label htmlFor="summary-source">Document to summarize</label><select id="summary-source" value={source} disabled={busy} onChange={(event) => setSource(event.target.value)}><option value="">Choose a document</option>{sources.filter((item) => item.status === "ready").map((item) => <option key={item.id} value={item.id}>{item.title || item.filename}</option>)}</select></div>
    <button className="secondary-button" disabled={!source || busy || loading || summary?.status === "pending"} onClick={create}>Summarize document</button>
    {saved.length > 0 && <div className="field"><label htmlFor="saved-summary">Saved summaries</label><select id="saved-summary" value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">Choose a summary</option>{saved.map((item) => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString()}</option>)}</select></div>}
    {error && <p role="alert">{error}</p>}
    {summary && <article><p>Revision: {summary.revision_id ?? "unavailable"}</p><p role="status">{summary.status} · Extracted passages processed: {summary.processed}/{summary.total}{summary.stage === "reduce" && " · Combining findings"}</p>
      {summary.status === "failed" && <p>The summary could not be completed. You can start a new summary.</p>}
      {summary.result && Object.entries(summary.result).map(([field, claims]) => <section key={field}><h4>{field.charAt(0).toUpperCase() + field.slice(1)}</h4>{claims.length ? claims.map((claim, index) => <p key={index}>{claim.text}{" "}{claim.references.map((number) => <a key={number} href={`#summary-${summary.id}-${number}`}>[{number}] </a>)}</p>) : <p>Not reported in the summary evidence.</p>}</section>)}
      {summary.evidence.map((item) => <details id={`summary-${summary.id}-${item.number}`} key={item.number}><summary>Evidence [{item.number}]{item.page ? ` · Page ${item.page}` : ""}</summary><p style={{ whiteSpace: "pre-wrap" }}>{item.text}</p></details>)}
      <p className="field-hint">Covers extracted text; unreadable scans and figures may leave gaps. References should be checked against the passages.</p>
    </article>}
  </section>;
}
