import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { NombrePaso, NombrePasoSesion } from "../api/types";
import { CirculoPaso } from "../components/CirculoPaso";
import { PasoModal } from "../components/PasoModal";
import { ESTADO_SESION_LABEL, PASOS_CHUNK, formatearDuracion, formatearFecha } from "../pasos";

interface Seleccion {
  chunk: string | null;
  paso: NombrePaso;
}

export function DetalleSesion() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [seleccion, setSeleccion] = useState<Seleccion | null>(null);

  const sessionQuery = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.getSession(sessionId!),
    enabled: !!sessionId,
    // También reintenta si dio error: una sesión recién lanzada puede no existir aún en disco
    refetchInterval: (q) => (q.state.data?.estado === "corriendo" || q.state.error ? 3000 : false),
  });

  const corriendo = sessionQuery.data?.estado === "corriendo";
  const runsQuery = useQuery({
    queryKey: ["session-runs", sessionId],
    queryFn: () => api.getSessionRuns(sessionId!),
    enabled: !!sessionId,
    refetchInterval: corriendo ? 3000 : false,
  });
  const ultimoRun = runsQuery.data?.[0];
  const logQuery = useQuery({
    queryKey: ["run-log", ultimoRun?.run_id],
    queryFn: () => api.getRun(ultimoRun!.run_id, 150),
    enabled: !!ultimoRun,
    refetchInterval: corriendo ? 3000 : false,
  });

  const reanudarMutation = useMutation({
    mutationFn: () => api.reanudar(sessionId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["session-runs", sessionId] });
    },
  });

  if (sessionQuery.isLoading) return <p className="hint">Cargando sesión...</p>;
  if (sessionQuery.isError) return <p className="error">{(sessionQuery.error as Error).message}</p>;

  const s = sessionQuery.data!;
  const chunks = Object.entries(s.chunks);
  const hayPendientes =
    s.estado === "incompleto" ||
    Object.values(s.chunks).some((c) => Object.values(c.pasos).some((p) => p.estado === "interrumpido"));

  const abrir = (chunk: string | null, paso: NombrePaso) => {
    // Revisión en espera → directo a la revisión de clips (el "click al círculo y apruebo")
    if (paso === "revision" && s.pasos.revision.estado === "esperando") {
      navigate(`/sesiones/${s.session_id}/revision`);
      return;
    }
    setSeleccion({ chunk, paso });
  };

  const circuloSesion = (paso: NombrePasoSesion) => (
    <CirculoPaso nombre={paso} paso={s.pasos[paso]} onClick={() => abrir(null, paso)} />
  );

  return (
    <section className="panel">
      <p className="migas">
        <Link to="/sesiones">← Sesiones</Link>
      </p>
      {s.video?.titulo ? (
        <header className="cabecera-video">
          {s.video.miniatura && (
            <img
              className="cabecera-miniatura"
              src={s.video.miniatura}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={(e) => (e.currentTarget.style.display = "none")}
            />
          )}
          <div>
            <h1>{s.video.titulo}</h1>
            <p className="hint">{s.session_id}</p>
          </div>
        </header>
      ) : (
        <h1>{s.session_id}</h1>
      )}

      <dl className="ficha ficha-sesion">
        <dt>Estado</dt>
        <dd>
          <span className={`pill pill-sesion-${s.estado}`}>{ESTADO_SESION_LABEL[s.estado]}</span>
        </dd>
        {s.video?.canal && (
          <>
            <dt>Canal del video</dt>
            <dd>{s.video.canal}</dd>
          </>
        )}
        {s.video?.duracion_s ? (
          <>
            <dt>Duración</dt>
            <dd>{formatearDuracion(s.video.duracion_s)}</dd>
          </>
        ) : null}
        <dt>Origen</dt>
        <dd className="origen">{s.url || "—"}</dd>
        <dt>Canal</dt>
        <dd>{s.config || "—"}</dd>
        <dt>Creada</dt>
        <dd>{formatearFecha(s.creado)}</dd>
        <dt>Lead time</dt>
        <dd>{formatearDuracion(s.lead_time_s)}</dd>
        <dt>Clips</dt>
        <dd>{s.clips_a_publicar} para publicar</dd>
      </dl>

      <div className="acciones">
        {hayPendientes && !corriendo && (
          <button
            className="btn btn-primary"
            onClick={() => reanudarMutation.mutate()}
            disabled={reanudarMutation.isPending}
          >
            {reanudarMutation.isPending ? "Lanzando..." : "Reanudar pendientes"}
          </button>
        )}
        {(s.pasos.revision.estado === "esperando" || s.pasos.revision.estado === "ok") && (
          <Link className="btn btn-secondary" to={`/sesiones/${s.session_id}/revision`}>
            Revisar clips
          </Link>
        )}
        {reanudarMutation.isError && (
          <span className="error">{(reanudarMutation.error as Error).message}</span>
        )}
      </div>

      <h2 className="subtitulo">Detalle de operación</h2>
      <div className="flujo">
        <div className="flujo-fila">
          <span className="flujo-etiqueta">Sesión</span>
          <div className="flujo-circulos">
            {circuloSesion("descarga")}
            <span className="conector" />
            {circuloSesion("plan")}
          </div>
        </div>

        {chunks.map(([chunkId, chunk]) => (
          <div className="flujo-fila" key={chunkId}>
            <span className="flujo-etiqueta">
              {chunkId}
              {chunk.fin_segundos > 0 && (
                <span className="hint">
                  {chunk.inicio_ts} → {chunk.fin_ts}
                </span>
              )}
            </span>
            <div className="flujo-circulos">
              {PASOS_CHUNK.map((paso, i) => (
                <span className="flujo-paso" key={paso}>
                  {i > 0 && <span className="conector" />}
                  <CirculoPaso nombre={paso} paso={chunk.pasos[paso]} onClick={() => abrir(chunkId, paso)} />
                </span>
              ))}
            </div>
          </div>
        ))}

        <div className="flujo-fila">
          <span className="flujo-etiqueta">Cierre</span>
          <div className="flujo-circulos">
            {circuloSesion("revision")}
            <span className="conector" />
            {circuloSesion("fin")}
          </div>
        </div>
      </div>

      {ultimoRun && (
        <details className="panel-log" open={corriendo}>
          <summary>
            Log de la última corrida · {ultimoRun.accion} · {formatearFecha(ultimoRun.inicio)} ·{" "}
            {ultimoRun.estado}
          </summary>
          <pre className="log">{logQuery.data?.tail_log || "(sin salida todavía)"}</pre>
        </details>
      )}

      {seleccion && (
        <PasoModal
          sessionId={s.session_id}
          chunk={seleccion.chunk}
          paso={seleccion.paso}
          onClose={() => setSeleccion(null)}
        />
      )}
    </section>
  );
}
