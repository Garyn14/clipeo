import type { ErrorPaso } from "./api/types";

export interface ExplicacionError {
  /** Qué pasó, en pocas palabras */
  titulo: string;
  /** Qué hacer (o qué pasa solo) */
  accion: string;
}

type ErrorBasico = Pick<ErrorPaso, "tipo" | "mensaje" | "reintentable">;

interface Regla {
  tipos?: string[];
  patron?: RegExp;
  explicacion: ExplicacionError;
}

/**
 * Catálogo de errores conocidos en lenguaje humano. La primera regla que calza gana:
 * las específicas (tipo + patrón en el mensaje) van antes que las genéricas por tipo.
 */
const REGLAS: Regla[] = [
  // ── Colab (transcripción) ──
  {
    tipos: ["ColabError"],
    patron: /no configurada/i,
    explicacion: {
      titulo: "Falta la URL de Colab",
      accion: "Pega la URL del túnel de Colab en Configuración y reintenta.",
    },
  },
  {
    tipos: ["ColabError"],
    patron: /transcribió en '/i,
    explicacion: {
      titulo: "Colab transcribió en otro idioma",
      accion:
        "El notebook no usó el idioma que manda el pipeline (ej. salió italiano en vez de español). " +
        "Revisa que la celda del servidor lea el campo 'language' y reintenta.",
    },
  },
  {
    tipos: ["ColabError"],
    patron: /error 40[13]/i,
    explicacion: {
      titulo: "Colab rechazó el token",
      accion: "El token de Configuración no coincide con el AUTH_TOKEN del notebook. Corrígelo y reintenta.",
    },
  },
  {
    tipos: ["ColabError"],
    patron: /error 404/i,
    explicacion: {
      titulo: "La URL de Colab no es la correcta",
      accion: "Revisa la URL de Colab en Configuración: puede ser de un túnel anterior.",
    },
  },
  {
    tipos: ["ColabError"],
    patron: /no respondi|túnel|tunel|error 5\d\d|error 530/i,
    explicacion: {
      titulo: "Colab no respondió",
      accion:
        "Revisa que el notebook de Colab esté corriendo y que la URL en Configuración sea la actual " +
        "(cambia cada vez que reinicias el notebook). El siguiente intento ya toma la URL nueva.",
    },
  },
  {
    tipos: ["ColabError"],
    patron: /timeout|no terminó/i,
    explicacion: {
      titulo: "Colab tardó demasiado en transcribir",
      accion: "Revisa en el notebook si sigue procesando o si se cayó, y reintenta.",
    },
  },
  {
    tipos: ["ColabError"],
    explicacion: {
      titulo: "Falló la transcripción en Colab",
      accion: "Revisa la salida del notebook de Colab y reintenta.",
    },
  },

  // ── Descarga (yt-dlp / ffmpeg) ──
  {
    tipos: ["DescargaError"],
    patron: /private|unavailable|removed|not available|members-only|terminated/i,
    explicacion: {
      titulo: "El video no está disponible",
      accion: "El video es privado, se eliminó o es solo para miembros. Reintentar no lo va a arreglar.",
    },
  },
  {
    tipos: ["DescargaError"],
    patron: /unsupported url|not a valid url/i,
    explicacion: {
      titulo: "URL no soportada",
      accion: "Revisa que la URL del video sea correcta.",
    },
  },
  {
    tipos: ["DescargaError"],
    patron: /403|forbidden/i,
    explicacion: {
      titulo: "YouTube bloqueó la descarga",
      accion: "Suele resolverse actualizando yt-dlp (pip install -U yt-dlp). Si sigue, avisa para revisar el formato de descarga.",
    },
  },
  {
    tipos: ["DescargaError"],
    patron: /not a bot|sign in/i,
    explicacion: {
      titulo: "YouTube pidió verificar que no eres un bot",
      accion: "Espera un rato antes de reintentar; si se repite, hace falta configurar cookies.",
    },
  },
  {
    tipos: ["DescargaError"],
    explicacion: {
      titulo: "Falló la descarga del video",
      accion: "Suele ser un corte de red; reintentar normalmente lo resuelve.",
    },
  },

  // ── Claude ──
  {
    tipos: ["AIRetryableError"],
    patron: /\[JUEZ\]/,
    explicacion: {
      titulo: "El juez no devolvió un veredicto completo",
      accion: "Claude respondió sin la decisión de todos los candidatos. Se reintenta solo; normalmente se resuelve.",
    },
  },
  {
    tipos: ["AIRetryableError"],
    patron: /l[íi]mite|limit|rate/i,
    explicacion: {
      titulo: "Se alcanzó el límite de uso de Claude",
      accion: "Se reintenta solo; si se agotan los intentos, reintenta cuando se renueve el límite.",
    },
  },
  {
    tipos: ["AIRetryableError"],
    explicacion: {
      titulo: "Claude no respondió bien",
      accion: "Respuesta vacía, cortada o demorada. Se reintenta solo; normalmente se resuelve.",
    },
  },
  {
    tipos: ["AIFatalError"],
    explicacion: {
      titulo: "Claude Code no está disponible",
      accion: "Revisa que Claude Code esté instalado y con la sesión iniciada en esta máquina.",
    },
  },

  // ── Entradas y configuración ──
  {
    tipos: ["EntradaFaltante", "FileNotFoundError"],
    explicacion: {
      titulo: "Falta un archivo de entrada",
      accion: "Lo produce un paso anterior: reintenta desde ese paso.",
    },
  },
  {
    tipos: ["KeyError", "ValueError", "TypeError"],
    explicacion: {
      titulo: "Configuración o datos inválidos",
      accion: "Revisa la configuración del canal o el archivo del paso anterior; reintentar sin corregirlo da el mismo error.",
    },
  },
];

export function explicarError(error: ErrorBasico): ExplicacionError {
  for (const r of REGLAS) {
    if (r.tipos && !r.tipos.includes(error.tipo)) continue;
    if (r.patron && !r.patron.test(error.mensaje)) continue;
    return r.explicacion;
  }
  return {
    titulo: error.mensaje.split("\n")[0].slice(0, 140) || error.tipo,
    accion: error.reintentable
      ? "Parece un error pasajero: reintentar suele resolverlo."
      : "Hay que corregir la causa antes de reintentar (ver detalle técnico).",
  };
}
