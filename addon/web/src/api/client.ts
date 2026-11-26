export type FaceStatus = "none" | "pending" | "accepted" | "verified" | "rejected" | string;

export type Person = {
  user_id: string;
  display_name: string;
  face_status: FaceStatus;
  enabled?: boolean;
  has_thumb?: boolean;
  source?: string;
  verify_ok_count?: number;
  verify_fail_streak?: number;
};

export type AuditRow = {
  id: number;
  user_id: string | null;
  camera: string;
  similarity: number;
  decision: string;
  detail: Record<string, unknown>;
  created_at: number;
};

export type Health = {
  ok: boolean;
  embedder_ready: boolean;
  model_version?: string;
  disk_full?: boolean;
  mqtt_enabled?: boolean;
  mqtt_host?: string;
  store?: Record<string, number>;
  open_sessions?: number;
};

export type Dashboard = {
  persons: {
    total: number;
    enabled_door: number;
    by_status: Record<string, number>;
    pending_recollect: { user_id: string; display_name: string; face_status: string; updated_at: number }[];
  };
  access: {
    h24: { grant: number; deny: number; skip: number };
    d7: { grant: number; deny: number; skip: number };
    top_grant_7d: { user_id: string; n: number }[];
  };
  store: Record<string, number>;
  runtime: {
    embedder_ready: boolean;
    model_version?: string;
    mqtt_enabled?: boolean;
    mqtt_host?: string;
    disk_full?: boolean;
    open_sessions?: number;
  };
};

export type PersonDetail = Person & {
  frame_count: number;
  frames: { index: number; url: string }[];
};

function apiBase(): string {
  const q = new URLSearchParams(location.search).get("api");
  const raw = (q || window.SMARTCENTER_API || "").replace(/\/$/, "");
  return raw;
}

export function apiUrl(path: string): string {
  return `${apiBase()}${path}`;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(apiUrl(path), init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = (body as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : r.statusText || "request_failed");
  }
  return body as T;
}

export const api = {
  health: () => json<Health>("/healthz"),
  stats: () => json<Dashboard>("/api/stats"),
  searchPersons: (q: string) => json<{ items: Person[] }>(`/api/persons/search?q=${encodeURIComponent(q)}`),
  listPersons: (q = "") =>
    json<{ items: Person[] }>(`/api/persons${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  personDetail: (uid: string) => json<PersonDetail>(`/api/persons/${encodeURIComponent(uid)}`),
  renamePerson: (uid: string, display_name: string) =>
    json<Person>(`/api/persons/${encodeURIComponent(uid)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name }),
    }),
  enablePerson: (uid: string) => json(`/api/persons/${encodeURIComponent(uid)}/enable`, { method: "POST" }),
  disablePerson: (uid: string) => json(`/api/persons/${encodeURIComponent(uid)}/disable`, { method: "POST" }),
  deletePerson: (uid: string) => json(`/api/persons/${encodeURIComponent(uid)}`, { method: "DELETE" }),
  thumbUrl: (uid: string) => apiUrl(`/api/persons/${encodeURIComponent(uid)}/thumb`),
  frameUrl: (uid: string, index: number) => apiUrl(`/api/persons/${encodeURIComponent(uid)}/frame/${index}`),
  audit: (decision = "", limit = 80) =>
    json<{ items: AuditRow[] }>(
      `/api/audit?limit=${limit}${decision ? `&decision=${encodeURIComponent(decision)}` : ""}`,
    ),
  enrollStart: (user_id: string, display_name: string) =>
    json<{ session_id: string; needed: number }>("/api/enroll/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id, display_name, channel: "staff" }),
    }),
  enrollFrame: async (sessionId: string, blob: Blob) => {
    const fd = new FormData();
    fd.append("file", blob, "frame.jpg");
    return json<{
      ok: boolean;
      reason?: string;
      hint?: string;
      progress?: number;
      needed?: number;
      done?: boolean;
      face_status?: string;
    }>(`/api/enroll/${sessionId}/frame`, { method: "POST", body: fd });
  },
  enrollCancel: (sessionId: string) =>
    json(`/api/enroll/${sessionId}/cancel`, { method: "POST" }),
};
