import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { EstadoSesion, SessionSummary } from "../api/types";
import { ESTADO_SESION_LABEL, PASO_LABEL, formatearDuracion, formatearFecha } from "../pasos";

export function Sesiones() {
  const navigate = useNavigate();
  const [texto, setTexto] = useState("");
  const [estado, setEstado] = useState<EstadoSesion | "">("");
  const [config, setConfig] = useState("");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");

  const sessionsQuery = useQuery({
    queryKey: ["sessions"],
    queryFn: api.getSessions,
    refetchInterval: 5000,
  });

  const sesiones = useMemo(() => sessionsQuery.data ?? [], [sessionsQuery.data]);
  const configs = useMemo(
    () => [...new Set(sesiones.map((s) => s.config).filter(Boolean))].sort(),
    [sesiones],
  );

  const filtradas = sesiones.filter((s) => {
    const fecha = (s.creado ?? "").slice(0, 10);
    return (
      (!texto ||
        `${s.session_id} ${s.url} ${s.video?.titulo ?? ""}`.toLowerCase().includes(texto.toLowerCase())) &&
      (!estado || s.estado === estado) &&
      (!config || s.config === config) &&
      (!desde || (fecha && fecha >= desde)) &&
      (!hasta || (fecha && fecha <= hasta))
    );
  });

  const limpiar = () => {
    setTexto("");
    setEstado("");
    setConfig("");
    setDesde("");
    setHasta("");
  };

  return (
    <section className="panel">
      <h1>Sesiones</h1>

      <div className="filtros">
        <label>
          Sesión / título / URL
          <input value={texto} onChange={(e) => setTexto(e.target.value)} placeholder="Buscar..." />
        </label>
        <label>
          Estado
          <select value={estado} onChange={(e) => setEstado(e.target.value as EstadoSesion | "")}>
            <option value="">Todos</option>
            {Object.entries(ESTADO_SESION_LABEL).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Canal
          <select value={config} onChange={(e) => setConfig(e.target.value)}>
            <option value="">Todos</option>
            {configs.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          Desde
          <input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
        </label>
        <label>
          Hasta
          <input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
        </label>
        <button type="button" className="btn btn-secondary" onClick={limpiar}>
          Limpiar
        </button>
      </div>

      {sessionsQuery.isLoading && <p className="hint">Cargando sesiones...</p>}
      {sessionsQuery.isError && <p className="error">{(sessionsQuery.error as Error).message}</p>}
      {!sessionsQuery.isLoading && filtradas.length === 0 && (
        <p className="hint">No hay sesiones que coincidan.</p>
      )}

      {filtradas.length > 0 && (
        <div className="tabla-scroll">
          <table className="tabla-sesiones tabla-clicable">
            <thead>
              <tr>
                <th>Sesión</th>
                <th>Creada</th>
                <th>Canal</th>
                <th>Estado</th>
                <th>Paso actual</th>
                <th>Lead time</th>
                <th>Chunks</th>
                <th>Clips</th>
              </tr>
            </thead>
            <tbody>
              {filtradas.map((s) => (
                <tr key={s.session_id} onClick={() => navigate(`/sesiones/${s.session_id}`)}>
                  <td>
                    <Link to={`/sesiones/${s.session_id}`} onClick={(e) => e.stopPropagation()}>
                      {s.session_id}
                    </Link>
                    {s.video?.titulo && (
                      <div className="sesion-titulo" title={s.video.titulo}>
                        {s.video.titulo}
                      </div>
                    )}
                  </td>
                  <td>{formatearFecha(s.creado)}</td>
                  <td>{s.config || "—"}</td>
                  <td>
                    <span className={`pill pill-sesion-${s.estado}`}>{ESTADO_SESION_LABEL[s.estado]}</span>
                  </td>
                  <td>{pasoActual(s)}</td>
                  <td>{formatearDuracion(s.lead_time_s)}</td>
                  <td>
                    {s.chunks_total > 0
                      ? `${s.chunks_completados}/${s.chunks_total}${s.chunks_fallidos ? ` (${s.chunks_fallidos} con error)` : ""}`
                      : "—"}
                  </td>
                  <td>{s.clips_a_publicar}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function pasoActual(s: SessionSummary): string {
  if (!s.paso_actual) return s.estado === "finalizado" ? "Fin" : "—";
  const { chunk, paso } = s.paso_actual;
  return chunk ? `${PASO_LABEL[paso]} (${chunk})` : PASO_LABEL[paso];
}
