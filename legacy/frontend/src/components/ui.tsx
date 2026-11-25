import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../api/client";

/** CLIP-84: encabezado único de página (sección, título, descripción y acciones a la derecha). */
export function PageHeader({
  seccion,
  titulo,
  descripcion,
  acciones,
}: {
  seccion?: string;
  titulo: ReactNode;
  descripcion?: ReactNode;
  acciones?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="page-header-texto">
        {seccion && <p className="page-eyebrow">{seccion}</p>}
        <h1>{titulo}</h1>
        {descripcion && <p className="page-descripcion">{descripcion}</p>}
      </div>
      {acciones && <div className="page-acciones">{acciones}</div>}
    </header>
  );
}

/** Estado vacío con una frase de qué falta y, opcional, qué hacer. */
export function Vacio({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <div className="vacio">
      <strong>{titulo}</strong>
      {children && <span>{children}</span>}
    </div>
  );
}

/** Pie de la barra lateral: Colab, cuenta de Claude del pipeline. Se refresca solo cada minuto. */
export function EstadoOperacion() {
  const q = useQuery({ queryKey: ["estado"], queryFn: () => api.getEstado(), refetchInterval: 60000 });
  const e = q.data;
  return (
    <div className="estado-operacion" aria-label="Estado de la operación">
      <div className="estado-operacion-fila">
        <span>Colab</span>
        <span
          className={`pill ${e ? (e.colab.vivo ? "pill-ok" : "pill-error") : "pill-muted"}`}
          title={e?.colab.motivo || undefined}
        >
          {e ? (e.colab.vivo ? "vivo" : "apagado") : "…"}
        </span>
      </div>
      <div className="estado-operacion-fila">
        <span>Claude</span>
        <span className="estado-operacion-valor" title={e?.claude.cuenta || undefined}>
          {e ? (e.claude.sesion ? e.claude.perfil || "por defecto" : "sin sesión") : "…"}
        </span>
      </div>
    </div>
  );
}

/** Cantidad de pasos en error, para el contador del menú. */
export function useErroresPendientes(): number {
  const q = useQuery({ queryKey: ["estado"], queryFn: () => api.getEstado(), refetchInterval: 60000 });
  return q.data?.errores ?? 0;
}
