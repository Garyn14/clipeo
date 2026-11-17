import type {
  Canal,
  ClipView,
  CuentaPublicacion,
  DetallePaso,
  DiscardClipBody,
  EditClipBody,
  EnvField,
  ErrorFila,
  NombrePaso,
  Plataforma,
  Publicacion,
  PublicacionDetalle,
  ReintentoLoteResultado,
  ResumenPublicaciones,
  RevisionMotor,
  RunLaunchBody,
  RunStatus,
  SessionDetail,
  SessionSummary,
} from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

// En la URL, un paso de sesión (descarga, plan...) va con chunk "_"
const SIN_CHUNK = "_";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body.detail;
    const mensaje =
      typeof detail === "string" ? detail : detail?.mensaje ?? `Error ${res.status} en ${path}`;
    throw new Error(mensaje);
  }
  return res.json() as Promise<T>;
}

function query(params: Record<string, string | boolean | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const api = {
  getCanales: () => request<Canal[]>("/config/canales"),

  getEnvStatus: () => request<EnvField[]>("/config/env"),
  updateEnv: (values: Record<string, string>) =>
    request<EnvField[]>("/config/env", { method: "PUT", body: JSON.stringify({ values }) }),

  launchRun: (body: RunLaunchBody) =>
    request<{ run_id: string; session_id: string }>("/runs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  getRun: (runId: string, lineas = 40) => request<RunStatus>(`/runs/${runId}?lineas=${lineas}`),

  getSessions: () => request<SessionSummary[]>("/sessions"),
  getSession: (sessionId: string) => request<SessionDetail>(`/sessions/${sessionId}`),
  getSessionRuns: (sessionId: string) => request<RunStatus[]>(`/sessions/${sessionId}/runs`),

  getPaso: (sessionId: string, chunk: string | null, paso: NombrePaso) =>
    request<DetallePaso>(`/sessions/${sessionId}/pasos/${chunk ?? SIN_CHUNK}/${paso}`),
  reintentar: (sessionId: string, paso: NombrePaso, chunks?: string[]) =>
    request<{ run_id: string }>(`/sessions/${sessionId}/reintentar`, {
      method: "POST",
      body: JSON.stringify({ paso, chunks }),
    }),
  reanudar: (sessionId: string) =>
    request<{ run_id: string }>(`/sessions/${sessionId}/reanudar`, { method: "POST" }),
  reintentarLote: (items: { session_id: string; paso: NombrePaso; chunk: string | null }[]) =>
    request<ReintentoLoteResultado[]>("/sessions/reintentar-lote", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),
  finalizarRevision: (sessionId: string) =>
    request<SessionDetail>(`/sessions/${sessionId}/revision/finalizar`, { method: "POST" }),

  getErrores: (filtros: { paso?: string; reintentable?: boolean; config?: string } = {}) =>
    request<ErrorFila[]>(`/errores${query(filtros)}`),

  getClips: (sessionId: string) => request<ClipView[]>(`/sessions/${sessionId}/clips`),
  clipVideoUrl: (sessionId: string, clipId: string) =>
    `${API_BASE}/sessions/${sessionId}/clips/${clipId}/video`,
  approveClip: (sessionId: string, clipId: string) =>
    request<ClipView>(`/sessions/${sessionId}/clips/${clipId}/approve`, { method: "POST" }),
  editClip: (sessionId: string, clipId: string, body: EditClipBody) =>
    request<ClipView>(`/sessions/${sessionId}/clips/${clipId}/edit`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  registrarPublicado: (sessionId: string, clipId: string, url: string) =>
    request<ClipView>(`/sessions/${sessionId}/clips/${clipId}/publicado`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  discardClip: (sessionId: string, clipId: string, body: DiscardClipBody) =>
    request<{ ok: boolean }>(`/sessions/${sessionId}/clips/${clipId}/discard`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getResumenPublicaciones: () => request<ResumenPublicaciones>("/publicaciones/resumen"),
  getPublicaciones: (plataforma: Plataforma, nicho?: string) =>
    request<Publicacion[]>(`/publicaciones${query({ plataforma, nicho })}`),
  getPublicacion: (id: number) => request<PublicacionDetalle>(`/publicaciones/${id}`),
  getRevisionesMotor: (plataforma: Plataforma, nicho: string) =>
    request<RevisionMotor[]>(`/publicaciones/revisiones${query({ plataforma, nicho })}`),
  moverPublicacion: (id: number, direccion: "arriba" | "abajo") =>
    request<PublicacionDetalle>(`/publicaciones/${id}/mover`, {
      method: "POST",
      body: JSON.stringify({ direccion }),
    }),
  quitarPublicacion: (id: number) =>
    request<PublicacionDetalle>(`/publicaciones/${id}/quitar`, { method: "POST" }),
  reintentarPublicacion: (id: number) =>
    request<PublicacionDetalle>(`/publicaciones/${id}/reintentar`, { method: "POST" }),
  marcarRecibido: (id: number) =>
    request<PublicacionDetalle>(`/publicaciones/${id}/marcar-recibido`, { method: "POST" }),
  revisarAhora: () => request<{ ok: boolean }>("/publicaciones/acciones/revisar-ahora", { method: "POST" }),
  enviarAhora: (plataforma: Plataforma, nicho: string) =>
    request<PublicacionDetalle>("/publicaciones/acciones/enviar-ahora", {
      method: "POST",
      body: JSON.stringify({ nicho, plataforma }),
    }),
  conectarCuentaSimulada: (plataforma: Plataforma, nicho: string) =>
    request<CuentaPublicacion>("/publicaciones/cuentas/simulada", {
      method: "POST",
      body: JSON.stringify({ nicho, plataforma }),
    }),
  autorizarYouTube: (nicho: string) =>
    request<{ url: string }>(`/publicaciones/cuentas/youtube/autorizar${query({ nicho })}`),
  autorizarTikTok: (nicho: string) =>
    request<{ url: string }>(`/publicaciones/cuentas/tiktok/autorizar${query({ nicho })}`),
  conectarTikTok: (nicho: string, url_pegada: string) =>
    request<CuentaPublicacion>("/publicaciones/cuentas/tiktok/conectar", {
      method: "POST",
      body: JSON.stringify({ nicho, url_pegada }),
    }),
  reanudarCuenta: (cuentaId: number) =>
    request<CuentaPublicacion>(`/publicaciones/cuentas/${cuentaId}/reanudar`, { method: "POST" }),
};
