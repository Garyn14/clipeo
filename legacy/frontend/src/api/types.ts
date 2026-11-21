export interface Canal {
  canal_id: string;
  descripcion: string;
  sistema: "v1" | "v1-ecosistema" | "v2";
}

// ── Pasos (círculos) ────────────────────────────────────────

export type NombrePasoSesion = "descarga" | "plan" | "revision" | "fin";
export type NombrePasoChunk = "transcripcion" | "agente0" | "agente1" | "agente2" | "agente3" | "juez" | "corte";
export type NombrePaso = NombrePasoSesion | NombrePasoChunk;

export type EstadoPaso =
  | "pendiente"
  | "corriendo"
  | "ok"
  | "omitido"
  | "error"
  | "esperando"
  | "interrumpido";

export interface ErrorPaso {
  tipo: string;
  mensaje: string;
  reintentable: boolean;
  detalle: string;
  fecha: string | null;
}

export type ResultadoIntento = "corriendo" | "ok" | "omitido" | "error" | "interrumpido";

/** Un intento de correr el paso (core/pasos.py). */
export interface IntentoPaso {
  tipo: "intento";
  n: number;
  /** inicial: primer intento · automatico: tras una espera · relanzado: corrida nueva (reintento manual o reanudación) */
  origen: "inicial" | "automatico" | "relanzado";
  espera_previa_s: number | null;
  inicio: string;
  fin: string | null;
  duracion_s: number | null;
  resultado: ResultadoIntento;
  error: Omit<ErrorPaso, "detalle"> | null;
  /** Rango [desde, hasta] de números de llamada a Claude hechas en este intento */
  llamadas: [number, number] | null;
}

/** El paso volvió a pendiente por un "Reintentar desde <desde>". */
export interface ReinicioPaso {
  tipo: "reinicio";
  fecha: string;
  desde: NombrePaso;
  chunk: string | null;
}

export type EventoHistorial = IntentoPaso | ReinicioPaso;

export interface Paso {
  estado: EstadoPaso;
  inicio: string | null;
  fin: string | null;
  duracion_s: number | null;
  intentos: number;
  error: ErrorPaso | null;
  salidas: string[];
  nota: string | null;
  ia: { llamadas: number; errores: number; trazas: string } | null;
  /** Ausente en sesiones anteriores al historial de intentos */
  historial?: EventoHistorial[];
  /** Tareas internas del paso (hoy solo la Descarga); se reinician en cada intento */
  subpasos?: Subpaso[];
}

export interface ProgresoSubpaso {
  pct: number | null;
  bytes?: number | null;
  total?: number | null;
  velocidad?: number | null;
  eta_s?: number | null;
  pista?: number | null;
  pistas?: number | null;
}

export interface Subpaso {
  id: string;
  label: string;
  estado: "pendiente" | "corriendo" | "ok" | "error";
  detalle: string | null;
  progreso: ProgresoSubpaso | null;
}

/** Lo esencial del video de la sesión, leído al empezar la descarga */
export interface VideoSesion {
  titulo: string;
  canal: string;
  duracion_s: number | null;
  miniatura: string | null;
}

export interface ChunkEstado {
  inicio_segundos: number;
  fin_segundos: number;
  inicio_ts: string;
  fin_ts: string;
  estado: "pendiente" | "completado" | "fallido";
  error?: string;
  pasos: Record<NombrePasoChunk, Paso>;
}

// ── Sesiones ────────────────────────────────────────────────

export type EstadoSesion =
  | "corriendo"
  | "error"
  | "esperando_revision"
  | "finalizado"
  | "incompleto"
  | "sin_procesar";

export interface PasoActual {
  chunk: string | null;
  paso: NombrePaso;
  estado: EstadoPaso;
}

export interface SessionSummary {
  session_id: string;
  url: string;
  config: string;
  modo: string;
  creado: string | null;
  video?: VideoSesion | null;
  estado: EstadoSesion;
  paso_actual: PasoActual | null;
  run_activo: string | null;
  lead_time_s: number | null;
  chunks_total: number;
  chunks_completados: number;
  chunks_fallidos: number;
  tiene_contenido_final: boolean;
  clips_a_publicar: number;
}

export interface SessionDetail extends SessionSummary {
  pasos: Record<NombrePasoSesion, Paso>;
  chunks: Record<string, ChunkEstado>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  contenido: any[];
}

export interface LlamadaIA {
  n: number;
  request: { modelo: string | null; system: string; mensajes: string };
  response: {
    texto: string;
    duracion_s: number | null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    meta: Record<string, any> | null;
  } | null;
  error: { tipo: string; mensaje: string; duracion_s: number } | null;
}

export interface DetallePaso extends Omit<Paso, "salidas"> {
  session_id: string;
  chunk: string | null;
  paso: NombrePaso;
  salidas: { ruta: string; existe: boolean; bytes: number | null }[];
  llamadas: LlamadaIA[];
  run_activo: boolean;
  /** Solo en el paso "juez": veredicto por candidato (juez.json) */
  decisiones?: DecisionJuez[];
}

export interface DecisionJuez {
  n: number;
  inicio: string | null;
  fin: string | null;
  publicar: boolean;
  linea1: string | null;
  linea2: string | null;
  tipo: string | null;
  en_juego: string | null;
  parecidos: string[] | null;
  fuerza: number | null;
  por_que: string | null;
}

export interface ErrorFila {
  session_id: string;
  config: string;
  chunk: string | null;
  paso: NombrePaso;
  tipo: string;
  mensaje: string;
  reintentable: boolean;
  fecha: string | null;
  intentos: number;
  run_activo: boolean;
}

export interface ReintentoLoteResultado {
  session_id: string;
  paso: NombrePaso;
  run_id?: string;
  error?: string;
}

// ── Corridas ────────────────────────────────────────────────

export type RunEstado = "corriendo" | "completado" | "fallido" | "terminado";

export interface RunLaunchBody {
  modo: "video" | "test";
  url_o_path: string;
  canal_id?: string;
}

export interface RunStatus {
  run_id: string;
  estado: RunEstado;
  session_id: string | null;
  accion: string;
  inicio: string | null;
  tail_log: string;
}

// ── Clips ───────────────────────────────────────────────────

export interface RangoOriginal {
  inicio?: string;
  fin?: string;
  duracion_segundos?: number;
}

export interface JuezClip {
  tipo: string | null;
  en_juego: string | null;
  parecidos: string[] | null;
  fuerza: number | null;
  por_que: string | null;
}

export interface ClipView {
  clip_id: string;
  score: number;
  texto_linea1: string;
  texto_linea2: string;
  hashtags: string[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  publicacion: Record<string, any>;
  rango_original: RangoOriginal;
  /** Veredicto del juez (null en clips anteriores al juez) */
  juez?: JuezClip | null;
  descartado: boolean;
  tiene_video: boolean;
  listo_para_publicar: boolean;
  /** CLIP-33: link del video ya publicado, por plataforma */
  publicado?: Record<string, { url: string; video_id: string }>;
  /** CLIP-27: de dónde viene el video (null en streams del cliente) */
  fuente?: FuenteClip | null;
  /** CLIP-51/52: avisos del control de calidad (vacío si está todo bien) */
  control_calidad?: { codigo: string; detalle: string }[];
}

export interface FuenteClip {
  tipo: string;
  sobre?: string | null;
  canal_origen?: string | null;
  url?: string | null;
}

export interface EditClipBody {
  canal_id?: string;
  texto_linea1?: string;
  texto_linea2?: string;
  inicio?: string;
  fin?: string;
}

export interface DiscardClipBody {
  canal_id?: string;
  razon?: string;
}

// ── Publicaciones (colas de TikTok y YouTube) ────────────────

export type Plataforma = "tiktok" | "youtube";

export type EstadoPublicacion =
  | "en_cola"
  | "enviando"
  | "en_bandeja"
  | "sin_confirmar"
  | "error"
  | "cancelado";

export type EstadoCuenta = "conectada" | "pausada" | "requiere_reconexion";

export interface CuentaPublicacion {
  id: number;
  plataforma: Plataforma;
  nicho: string;
  modo: "real" | "simulado";
  nombre: string | null;
  estado: EstadoCuenta;
  motivo: string | null;
  pausada_hasta: string | null;
  access_vence: string | null;
  refresh_vence: string | null;
  horarios: string;
  creada: string;
  actualizada: string;
}

export interface RevisionMotor {
  id: number;
  plataforma: Plataforma;
  nicho: string;
  desde: string;
  hasta: string;
  veces: number;
  decision: string;
  envio: number;
}

export interface ProximoEnvio {
  id: number;
  clip_id: string;
  titulo: string | null;
  /** Hora en que sale (revisión del reloj), según las reglas del motor */
  sale: string;
  /** Horario de la grilla que cubre */
  horario: string;
}

export interface ResumenNicho {
  plataforma: Plataforma;
  nicho: string;
  cuenta: CuentaPublicacion | null;
  proximo_envio: ProximoEnvio | null;
  /** Por qué no hay estimación (sin cuenta, reconectar) */
  proximo_envio_motivo: string | null;
  /** Con la cola vacía: cuándo saldría un clip aprobado ahora */
  siguiente_libre: string | null;
  proximo_horario: string | null;
  conteos: Partial<Record<EstadoPublicacion, number>>;
  dias_cola: number | null;
  ultima_revision: RevisionMotor | null;
  alertas: { nivel: "warn" | "error"; texto: string }[];
}

export interface ResumenPublicaciones {
  ahora: string;
  intervalo_s: number;
  nichos: ResumenNicho[];
}

export interface Publicacion {
  id: number;
  plataforma: Plataforma;
  session_id: string;
  clip_id: string;
  nicho: string;
  ruta_video: string;
  titulo: string | null;
  /** TikTok: descripción + # para pegar al activar el borrador. YouTube: título/descripción/tags enviados.
   *  null: clip sin copy */
  texto: string | null;
  /** YouTube: JSON {titulo, descripcion, tags} que va por la API */
  metadatos: string | null;
  orden: number;
  estado: EstadoPublicacion;
  slot: string | null;
  publish_id: string | null;
  subida_completa: number;
  intentos: number;
  error_codigo: string | null;
  error_mensaje: string | null;
  encolada_en: string;
  enviada_en: string | null;
  confirmada_en: string | null;
  actualizada_en: string;
  /** Solo en cola: cuándo sale y qué horario cubre (estimación con las reglas del motor) */
  sale_aprox?: string | null;
  horario_estimado?: string | null;
}

export interface EventoPublicacion {
  ts: string;
  tipo: string;
  mensaje: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  detalle: Record<string, any> | null;
}

export interface PublicacionDetalle extends Publicacion {
  eventos: EventoPublicacion[];
}

export interface EnvField {
  key: string;
  label: string;
  help: string;
  secret: boolean;
  is_set: boolean;
  value: string;
  masked_value: string;
}

// ── S14: fuentes estáticas por nicho ──
export interface CanalFuente {
  nombre: string;
  plataforma: string;
  url: string;
  rol: "propio" | "medios";
  activo?: boolean;
  ultima_revision?: string | null;
  aportes?: { nuevo?: number; procesado?: number; descartado?: number; error?: number };
}

// CLIP-66/67: tipos de fuente desacoplados
export interface TipoFuente {
  clave: string;
  nombre: string;
  implementado: boolean;
  automatico: boolean;
  pide: string;
}

export interface VistaPreviaCanal {
  nombre: string;
  url: string;
  plataforma: string;
  videos: { id: string; titulo: string; url?: string; publicado?: string | null }[];
}

export interface ResultadoLink {
  link: string;
  ok: boolean;
  motivo?: string;
  id?: string;
  titulo?: string;
}

export interface SugerenciaCanal {
  canal: string;
  apariciones: number;
  url: string;
}

export interface VideoFuente {
  id: string;
  url?: string;
  titulo?: string;
  canal?: string;
  rol?: string;
  publicado?: string | null;
  detectado?: string;
  estado: string;
  motivo?: string;
  sesion?: string;
}

export interface ClienteFuentes {
  nicho: string;
  cliente: string;
  canales: number;
  candidatos: number;
}

export interface FuentesNicho {
  nicho: string;
  cliente: string;
  activo: boolean;
  ventana_inicial_dias: number;
  canales: CanalFuente[];
  palabras_clave: string[];
  sugerencias: SugerenciaCanal[];
  candidatos: VideoFuente[];
  historial: VideoFuente[];
  colab: { vivo: boolean; motivo: string };
}

export interface ResumenEjecucion {
  activo: boolean;
  canales: { canal: string; nuevos: number; descartados: number; error?: string }[];
}
