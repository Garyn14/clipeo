import type { ClienteFuentes, FilaNegocioGlobal, FuentesNicho, ReporteNegocio, ResultadoLink, ResumenEjecucion, TipoFuente, VistaPreviaCanal,
  Canal,
  ClipView,
  CuentaPublicacion,
  DetallePaso,
  DiscardClipBody,
  EditClipBody,
  EnvField,
  CuentaDirecto,
  ResumenDirectos,
  EstadoOperacion,
  CuentaClaude,
  PerfilClaude,
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
  // S14: fuentes estáticas
  getNichosFuentes: () => request<ClienteFuentes[]>("/fuentes"),
  // CLIP-66/67: administrar fuentes
  getTiposFuente: () => request<TipoFuente[]>("/fuentes/tipos"),
  previsualizarCanal: (nicho: string, body: { plataforma: string; entrada: string }) =>
    request<VistaPreviaCanal>(`/fuentes/${nicho}/canales/previsualizar`, { method: "POST", body: JSON.stringify(body) }),
  agregarCanal: (nicho: string, body: { plataforma: string; entrada: string; rol: string; nombre?: string }) =>
    request<unknown>(`/fuentes/${nicho}/canales`, { method: "POST", body: JSON.stringify(body) }),
  editarCanal: (nicho: string, body: { url: string; activo?: boolean; rol?: string; nombre?: string }) =>
    request<unknown>(`/fuentes/${nicho}/canales`, { method: "PATCH", body: JSON.stringify(body) }),
  quitarCanal: (nicho: string, url: string) =>
    request<unknown>(`/fuentes/${nicho}/canales?url=${encodeURIComponent(url)}`, { method: "DELETE" }),
  guardarPalabras: (nicho: string, palabras: string[]) =>
    request<{ palabras: string[] }>(`/fuentes/${nicho}/palabras`, { method: "PUT", body: JSON.stringify({ palabras }) }),
  agregarLinks: (nicho: string, links: string[], rol: string) =>
    request<{ resultados: ResultadoLink[] }>(`/fuentes/${nicho}/manual`, { method: "POST", body: JSON.stringify({ links, rol }) }),
  getFuentes: (nicho: string) => request<FuentesNicho>(`/fuentes/${nicho}`),
  // S17: Negocio
  getNegocioGlobal: (mes?: string) => request<FilaNegocioGlobal[]>(`/negocio${mes ? `?mes=${mes}` : ""}`),
  getNegocio: (nicho: string, mes?: string) => request<ReporteNegocio>(`/negocio/${nicho}${mes ? `?mes=${mes}` : ""}`),
  actualizarNegocio: (nicho: string, mes?: string) =>
    request<ReporteNegocio>(`/negocio/${nicho}/actualizar${mes ? `?mes=${mes}` : ""}`, { method: "POST" }),
  ejecutarFuentes: (nicho: string, body: { dias?: number; ultimos?: number }) =>
    request<ResumenEjecucion>(`/fuentes/${nicho}/ejecutar`, { method: "POST", body: JSON.stringify(body) }),
  descartarFuentes: (nicho: string, ids: string[]) =>
    request<{ descartados: string[] }>(`/fuentes/${nicho}/descartar`, { method: "POST", body: JSON.stringify({ ids }) }),
  procesarFuentes: (nicho: string, ids: string[]) =>
    request<{ iniciado: string[]; log: string }>(`/fuentes/${nicho}/procesar`, {
      method: "POST",
      body: JSON.stringify({ ids }),
    }),

  getCanales: () => request<Canal[]>("/config/canales"),

  getEnvStatus: () => request<EnvField[]>("/config/env"),
  updateEnv: (values: Record<string, string>) =>
    request<EnvField[]>("/config/env", { method: "PUT", body: JSON.stringify({ values }) }),
  // CLIP-90: directos
  getDirectos: () => request<ResumenDirectos>("/directos"),
  agregarCuentaDirecto: (nicho: string, body: { plataforma: string; usuario: string; trozo_min: number; procesar: boolean }) =>
    request<CuentaDirecto>(`/directos/${nicho}/cuentas`, { method: "POST", body: JSON.stringify(body) }),
  actualizarCuentaDirecto: (nicho: string, plataforma: string, usuario: string, cambios: { activo?: boolean; procesar?: boolean; trozo_min?: number }) =>
    request<CuentaDirecto>(`/directos/${nicho}/cuentas/${plataforma}/${usuario}`, { method: "PATCH", body: JSON.stringify(cambios) }),
  quitarCuentaDirecto: (nicho: string, plataforma: string, usuario: string) =>
    request<{ ok: boolean }>(`/directos/${nicho}/cuentas/${plataforma}/${usuario}`, { method: "DELETE" }),
  revisarDirectos: () => request<{ ok: boolean }>("/directos/revisar", { method: "POST" }),
  grabarDirecto: (nicho: string, plataforma: string, usuario: string) =>
    request<{ pid: number }>(`/directos/${nicho}/cuentas/${plataforma}/${usuario}/grabar`, { method: "POST" }),
  detenerCaptura: (carpeta: string) => request<{ ok: boolean }>(`/directos/capturas/${carpeta}/detener`, { method: "POST" }),
  getEstado: (refrescar = false) => request<EstadoOperacion>(`/estado${refrescar ? "?refrescar=true" : ""}`),
  getCuentaClaude: () => request<CuentaClaude>("/config/claude"),
  crearPerfilClaude: (nombre: string) =>
    request<PerfilClaude>("/config/claude/perfiles", { method: "POST", body: JSON.stringify({ nombre }) }),
  activarPerfilClaude: (nombre: string) =>
    request<CuentaClaude>("/config/claude/activo", { method: "PUT", body: JSON.stringify({ nombre }) }),

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
