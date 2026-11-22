export type Account = { id: string };
export type ResearchOptions = { summaries: { analysis_id: string; source_id: string; revision_id: string; filename: string | null; title: string | null; created_at: string }[]; comparisons: { id: string; created_at: string }[] };
export type Comparison = { id: string; caution: string; sources: { analysis_id: string; source_id: string | null; revision_id: string | null; filename: string | null; title: string | null; available: boolean; result: Summary['result']; evidence: Summary['evidence'] }[] };
export type ResearchNote = { id: string; title: string; markdown: string; analysis_ids: string[]; comparison_ids: string[]; version: number; updated_at: string };
export type NoteBody = Pick<ResearchNote, 'title' | 'markdown' | 'analysis_ids' | 'comparison_ids'>;
export type Summary = { id: string; revision_id: string | null; status: string; processed: number; total: number; stage: string; result: Record<string, { text: string; references: number[] }[]> | null; evidence: { number: number; page: number | null; text: string }[] };

export type Collection = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
};

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, options: RequestInit = {}, format: 'json' | 'text' = 'json'): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v2${path}`, {
      ...options,
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new ApiError("Could not reach the workspace. Check that the API is running.", 0);
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = body && typeof body === "object" && "detail" in body ? body.detail : null;
    let message = typeof detail === "string" ? detail : "Something went wrong. Please try again.";
    if (Array.isArray(detail)) {
      const issue = detail.find((item: unknown) => item && typeof item === "object" && "msg" in item);
      if (issue && typeof issue.msg === "string") message = issue.msg.replace(/^Value error, /, "");
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  if (format === 'text') return await response.text() as T;
  return response.json() as Promise<T>;
}

export const api = {
  status: () => request<{ database: boolean; worker: boolean; storage: boolean; model: string; model_available: boolean; jobs: Record<string, number> }>('/status'),
  research: (id: string) => request<ResearchOptions>(`/collections/${id}/research`),
  createComparison: (id: string, summary_ids: string[]) => request<{ id: string }>(`/collections/${id}/comparisons`, { method: 'POST', body: JSON.stringify({ summary_ids }) }),
  comparison: (id: string) => request<Comparison>(`/comparisons/${id}`),
  notes: (id: string) => request<ResearchNote[]>(`/collections/${id}/notes`),
  createNote: (id: string, note: NoteBody) => request<ResearchNote>(`/collections/${id}/notes`, { method: 'POST', body: JSON.stringify(note) }),
  updateNote: (id: string, note: NoteBody & { version: number }) => request<ResearchNote>(`/notes/${id}`, { method: 'PATCH', body: JSON.stringify(note) }),
  deleteNote: (id: string) => request<void>(`/notes/${id}`, { method: 'DELETE' }),
  exportNote: (id: string) => request<string>(`/notes/${id}/export`, {}, 'text'),
  createSummary: (id: string) => request<{ id: string }>(`/sources/${id}/summaries`, { method: "POST" }),
  summaries: (id: string) => request<{ id: string; revision_id: string; created_at: string }[]>(`/sources/${id}/summaries`),
  summary: (id: string) => request<Summary>(`/analyses/${id}`),
  deleteSource: (id: string) => request<void>(`/sources/${id}`, { method: "DELETE" }),
  conversations: (id: string) => request<{ id: string; created_at: string; source_ids?: string[] | null }[]>(`/collections/${id}/conversations`),
  newConversation: (id: string, source_ids?: string[]) => request<{ id: string }>(`/collections/${id}/conversations`, { method: "POST", ...(source_ids?.length ? { body: JSON.stringify({ source_ids }) } : {}) }),
  conversation: (id: string) => request<{ id: string; turns: QuestionTurn[] }>(`/conversations/${id}`),
  ask: (id: string, question: string, requestId: string) => request<{ id: string; job_id: string }>(`/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ question }), headers: { "Idempotency-Key": requestId } }),
  retryIndex: (id: string) => request<{ job_id: string }>(`/sources/${id}/retry-index`, { method: "POST" }),
  library: () => request<{ id: string; filename: string; title: string | null }[]>("/sources"),
  attachSource: (collection: string, source: string) => request<void>(`/collections/${collection}/sources/${source}`, { method: "POST" }),
  detachSource: (collection: string, source: string) => request<void>(`/collections/${collection}/sources/${source}`, { method: "DELETE" }),
  updateSource: (id: string, metadata: { title: string | null; authors: string | null; publication_date: string | null; tags?: string[]; reading_status?: ReadingStatus; expected_revision_id?: string | null }) => request(`/sources/${id}`, { method: "PATCH", body: JSON.stringify(metadata) }),
  search: (id: string, query: string, source_ids?: string[]) => request<SearchHit[]>(`/collections/${id}/search`, { method: "POST", body: JSON.stringify({ query, ...(source_ids?.length ? { source_ids } : {}) }) }),
  sources: (id: string) => request<Source[]>(`/collections/${id}/sources`),
  importUrl: (id: string, url: string) => request<{ job_id: string }>(`/collections/${id}/sources/import-url`, { method: "POST", body: JSON.stringify({ url }) }),
  importStatus: (id: string) => request<{ status: string; source_id: string | null }>(`/jobs/${id}`),
  refreshSource: (id: string) => request<{ job_id: string }>(`/sources/${id}/refresh`, { method: "POST" }),
  sourceText: (id: string) => request<{ revision_id?: string; filename?: string; pages: { text: string; page: number | null }[] }>(`/sources/${id}/text`),
  upload: (id: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<Source>(`/collections/${id}/sources/upload`, { method: "POST", body });
  },
  replaceSource: (id: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ unchanged: boolean }>(`/sources/${id}/replace`, { method: "POST", body });
  },
  me: () => request<Account>("/auth/me"),
  login: (identifier: string, password: string) => request<Account>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ identifier, password }),
  }),
  register: (details: { username?: string; email?: string; password: string }) => request<Account>("/auth/register", {
    method: "POST",
    body: JSON.stringify(details),
  }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  collections: () => request<Collection[]>("/collections"),
  createCollection: (name: string, description: string | null) => request<Collection>("/collections", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  }),
  updateCollection: (id: string, name: string, description: string | null) => request<Collection>(`/collections/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ name, description }),
  }),
  deleteCollection: (id: string) => request<void>(`/collections/${id}`, { method: "DELETE" }),
};

export type ReadingStatus = 'unread' | 'reading' | 'read';
export type Source = { id: string; filename: string; job_id: string; status: string; title: string | null; authors: string | null; publication_date: string | null; tags?: string[]; reading_status?: ReadingStatus; active_revision_id: string | null; replacement_status: string | null; original_url: string | null; refresh_status: string | null; refresh_outcome: string | null };
export type SearchHit = { id: string; text: string; score: number; metadata: { source: string; source_id: string; revision_id: string; page: number | null } };
export type QuestionTurn = { id: string; question: string; answer: string | null; status: string; model: string | null; timings?: Record<string, number>; evidence: { number: number; text: string; available: boolean; metadata: { source: string; source_id?: string; revision_id?: string; page: number | null } }[] };
