import type { EstadoPaso, EstadoSesion, NombrePaso, NombrePasoChunk, Subpaso } from "./api/types";

export const PASOS_CHUNK: NombrePasoChunk[] = [
  "transcripcion",
  "agente0",
  "agente1",
  "agente2",
  "juez",
  "agente3",
  "corte",
];

export const PASO_LABEL: Record<NombrePaso, string> = {
  descarga: "Descarga",
  plan: "Plan",
  transcripcion: "Transcripción",
  agente0: "Speakers · A0",
  agente1: "Picos · A1",
  agente2: "Bordes · A2",
  agente3: "Copy · A3",
  juez: "Juez",
  corte: "Corte · A4",
  revision: "Revisión",
  fin: "Fin",
};

export const ESTADO_PASO_LABEL: Record<EstadoPaso, string> = {
  pendiente: "Pendiente",
  corriendo: "Corriendo",
  ok: "OK",
  omitido: "Omitido",
  error: "Error",
  esperando: "Esperando revisión",
  interrumpido: "Interrumpido",
};

export const ESTADO_SESION_LABEL: Record<EstadoSesion, string> = {
  corriendo: "Corriendo",
  error: "Con errores",
  esperando_revision: "Esperando revisión",
  finalizado: "Finalizado",
  incompleto: "Incompleto",
  sin_procesar: "Sin procesar",
};

/** Pasos que se pueden reintentar (Revisión/Fin se cierran desde la revisión de clips). */
export const esReintentable = (paso: NombrePaso) => paso !== "revision" && paso !== "fin";

export function formatearDuracion(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "—";
  const s = Math.round(segundos);
  if (s < 60) return `${s}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const resto = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(resto).padStart(2, "0")}`
    : `${m}:${String(resto).padStart(2, "0")}`;
}

export function formatearFecha(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("es-PE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatearHora(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatearBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

/** El subpaso en curso (para "Video 45%" en el círculo y el resumen), o null. */
export function subpasoActivo(
  subpasos: Subpaso[] | undefined,
): { id: string; label: string; pct: number | null } | null {
  const s = subpasos?.find((x) => x.estado === "corriendo");
  if (!s) return null;
  return { id: s.id, label: s.label, pct: s.progreso?.pct ?? null };
}

/** Tipos de momento viral de la memoria del nicho (investigacion/<nicho>/referencias.yaml). */
export const TIPO_MOMENTO_LABEL: Record<string, string> = {
  generosidad_con_humilde: "Generosidad",
  relaciones_y_emocion: "Relación / emoción",
  jefe_y_trabajadores: "Jefe y trabajadores",
  rivalidad_y_apuestas: "Rivalidad / reto",
  evento_fuerte: "Evento fuerte",
  humor_picaro: "Humor pícaro",
  ninguno: "Ninguno",
};
