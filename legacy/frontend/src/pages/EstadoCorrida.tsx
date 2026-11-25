import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { PageHeader } from "../components/ui";

const ESTADO_LABEL: Record<string, string> = {
  corriendo: "Corriendo...",
  completado: "Completado",
  fallido: "Fallido",
};

export function EstadoCorrida() {
  const { runId } = useParams<{ runId: string }>();

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data?.estado === "corriendo" ? 3000 : false,
  });

  if (runQuery.isLoading) return <p className="hint">Cargando estado de la corrida...</p>;
  if (runQuery.isError) return <p className="error">{(runQuery.error as Error).message}</p>;

  const run = runQuery.data!;

  return (
    <section className="panel">
      <PageHeader
        seccion="Producción · corrida"
        titulo={<span className="mono">{run.run_id}</span>}
        acciones={<span className={`pill pill-${run.estado}`}>{ESTADO_LABEL[run.estado] ?? run.estado}</span>}
      />

      {run.session_id ? (
        <p>
          Sesión: <Link to={`/sesiones/${run.session_id}`}>{run.session_id}</Link>
        </p>
      ) : (
        <p className="hint">Todavía no se detectó el directorio de sesión en stream_data/...</p>
      )}

      <h2>Log</h2>
      <pre className="log">{run.tail_log || "(sin salida todavía)"}</pre>
    </section>
  );
}
