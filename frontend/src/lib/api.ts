import { parseManifest, type Manifest } from "./manifest";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_KEY = "dastavez.token";

let memoryToken: string | null = null;

export function getToken(): string | null {
  if (memoryToken) return memoryToken;
  try {
    memoryToken = window.localStorage.getItem(TOKEN_KEY);
  } catch {
    /* storage can be blocked; the session then lasts until the tab closes */
  }
  return memoryToken;
}

export function setToken(token: string | null) {
  memoryToken = token;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

/** An error the operator can act on: a plain message, plus per-field errors when the server sent them. */
export class ApiError extends Error {
  constructor(public status: number, message: string, public errors: Record<string, string> = {}, public code?: string) {
    super(message);
  }
}

export class NetworkError extends Error {
  constructor() {
    super("Can't reach the server. Check your connection and try again.");
  }
}

async function raise(res: Response): Promise<never> {
  let message = `Something went wrong (${res.status}).`;
  let errors: Record<string, string> = {};
  let code: string | undefined;
  try {
    const body = await res.json();
    const d = body?.detail;
    if (typeof d === "string") message = d;
    else if (d && typeof d === "object") {
      message = d.message ?? message;
      errors = d.errors ?? {};
      code = d.code;
    }
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 401) setToken(null);
  throw new ApiError(res.status, message, errors, code);
}

async function raw(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch {
    throw new NetworkError();
  }
  if (!res.ok) await raise(res);
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await raw(path, init);
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const post = <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
  json<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body), headers });

// ------------------------------------------------------------------ types
export type Role = "owner" | "operator" | "viewer";
export interface Session { user: { id: string; name: string; email: string; role: Role }; business: { id: string; name: string; ai_consent: boolean } }
export interface WorkspaceInfo {
  id: string; name: string; tagline: string; description: string; material: string; example_prompt: string;
  disclaimers: string[]; other_workflows: string[];
  documents: { key: string; title: string; formats: string[]; primary: boolean }[];
  fields: { id: string; label: string; type: string; required: boolean }[];
}
export interface CaseDoc { id: string; doc_key: string; title: string; fmt: string; is_sample: boolean; created_at: string }
export interface CaseOut {
  id: string; workspace: string; title: string; status: string; transcript: string | null; created_at: string; updated_at: string;
  pending: { type: string; fields?: string[] } | null; answer_errors: Record<string, string>; export_failures: string[];
  approved_at: string | null; documents: CaseDoc[];
}
export interface CaseRow { id: string; workspace: string; title: string; status: string; created_at: string; updated_at: string }
export interface TemplateInfo {
  id: string; key: string; version: string; workspace: string; title: string; is_demo: boolean; approved: boolean;
  jurisdiction: string | null; verify_fields: string[]; note: string | null; last_verified: string | null;
}
export interface Capabilities { demo_mode: boolean; llm_provider: string; stt_provider: string; server_transcription: boolean; pdf_available: boolean; ai_consent: boolean }
export interface WorkflowEvent { id: number; type: string; message: string; data: Record<string, unknown>; created_at: string }
export interface AuditRow { id: string; action: string; actor_id: string | null; detail: Record<string, unknown>; created_at: string }
export interface Attachment { id: string; name: string; kind: string; size: number; fields: string[]; mapping?: Record<string, string> }

// ------------------------------------------------------------------ endpoints
export const api = {
  login: (email: string, password: string) => post<Session & { token: string }>("/api/auth/login", { email, password }),
  me: () => json<Session>("/api/me"),
  capabilities: () => json<Capabilities>("/api/capabilities"),
  setConsent: (ai_consent: boolean) => json<{ ai_consent: boolean }>("/api/tenant/consent", { method: "PUT", body: JSON.stringify({ ai_consent }) }),
  workspaces: () => json<WorkspaceInfo[]>("/api/workspaces"),
  templates: (workspace?: string) => json<TemplateInfo[]>(`/api/templates${workspace ? `?workspace=${workspace}` : ""}`),
  parties: (kind?: string) => json<{ id: string; kind: string; full_name: string; address: string | null }[]>(`/api/parties${kind ? `?kind=${kind}` : ""}`),

  cases: () => json<CaseRow[]>("/api/cases"),
  createCase: (workspace: string, idempotencyKey: string) =>
    post<CaseOut & { created: boolean }>("/api/cases", { workspace }, { "Idempotency-Key": idempotencyKey }),
  getCase: (id: string) => json<CaseOut>(`/api/cases/${id}`),
  manifest: async (id: string, view?: string): Promise<Manifest> =>
    parseManifest(await json(`/api/cases/${id}/manifest${view ? `?view=${view}` : ""}`)),
  startIntake: (id: string, transcript: string) => post<{ status: string }>(`/api/cases/${id}/intake`, { transcript }),
  retry: (id: string) => post<{ status: string }>(`/api/cases/${id}/retry`),
  answers: (id: string, body: { answers?: Record<string, unknown>; confirm?: string[]; conflict_choices?: Record<string, unknown> }) =>
    post<CaseOut>(`/api/cases/${id}/answers`, body),
  editInReview: (id: string, answers: Record<string, unknown>) => post<CaseOut>(`/api/cases/${id}/review/edit`, { answers }),
  approve: (id: string, confirm: string[], note?: string) => post<CaseOut>(`/api/cases/${id}/approve`, { confirm, note }),
  exportDocs: (id: string, formats: Record<string, string[]>) => post<CaseOut>(`/api/cases/${id}/export`, { formats }),
  reopen: (id: string) => post<CaseOut>(`/api/cases/${id}/reopen`),
  finish: (id: string) => post<CaseOut>(`/api/cases/${id}/finish`),
  cancel: (id: string) => post<CaseOut>(`/api/cases/${id}/cancel`),
  remove: (id: string) => json<void>(`/api/cases/${id}`, { method: "DELETE" }),
  events: (id: string, after = 0) => json<WorkflowEvent[]>(`/api/cases/${id}/events?after=${after}`),
  audit: (id: string) => json<AuditRow[]>(`/api/cases/${id}/audit`),

  upload: (id: string, file: File, kind: "supporting" | "form") => {
    const form = new FormData();
    form.append("file", file);
    return json<Attachment>(`/api/cases/${id}/attachments?kind=${kind}`, { method: "POST", body: form });
  },
  sampleForm: (id: string) => post<Attachment>(`/api/cases/${id}/attachments/sample-form`),
  setMapping: (id: string, mapping: Record<string, string | null>) =>
    json<{ mapping: Record<string, string> }>(`/api/cases/${id}/form-mapping`, { method: "PUT", body: JSON.stringify({ mapping }) }),
  transcribe: (id: string, audio: Blob) => {
    const form = new FormData();
    form.append("file", audio, "speech.webm");
    return json<{ transcript: string }>(`/api/cases/${id}/transcribe`, { method: "POST", body: form });
  },

  /** Authenticated download. Links cannot carry the bearer token, so the file is fetched and saved from a blob. */
  async download(documentId: string, fallbackName: string) {
    const res = await raw(`/api/documents/${documentId}/download`);
    const disposition = res.headers.get("content-disposition") ?? "";
    const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
    const name = match ? decodeURIComponent(match[1]) : fallbackName;
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  },
};

/**
 * Subscribe to typed progress events (Server-Sent Events over fetch, so the bearer token can be sent).
 * Returns a function that stops the stream.
 */
export function streamEvents(caseId: string, onEvent: (e: WorkflowEvent) => void, after = 0): () => void {
  const controller = new AbortController();
  (async () => {
    let last = after;
    while (!controller.signal.aborted) {
      try {
        const res = await raw(`/api/cases/${caseId}/events/stream?after=${last}`, { signal: controller.signal });
        const reader = res.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const chunk = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            const data = chunk.split("\n").find((l) => l.startsWith("data: "));
            if (data) {
              const ev = JSON.parse(data.slice(6)) as WorkflowEvent;
              last = Math.max(last, ev.id);
              onEvent(ev);
            }
          }
        }
      } catch {
        if (controller.signal.aborted) return;
      }
      await new Promise((r) => setTimeout(r, 1500)); // reconnect, resuming after the last event seen
    }
  })();
  return () => controller.abort();
}
