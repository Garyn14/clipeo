import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ClipView } from "../api/types";
import { TIPO_MOMENTO_LABEL } from "../pasos";

export function RevisionClips() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const sessionQuery = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.getSession(sessionId!),
    enabled: !!sessionId,
  });

  const clipsQuery = useQuery({
    queryKey: ["clips", sessionId],
    queryFn: () => api.getClips(sessionId!),
    enabled: !!sessionId,
  });

  const finalizarMutation = useMutation({
    mutationFn: () => api.finalizarRevision(sessionId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["session", sessionId] });
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      navigate(`/sesiones/${sessionId}`);
    },
  });

  if (clipsQuery.isLoading) return <p className="hint">Cargando clips...</p>;
  if (clipsQuery.isError) return <p className="error">{(clipsQuery.error as Error).message}</p>;

  const canalId = sessionQuery.data?.config || undefined;
  const clips = clipsQuery.data ?? [];
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["clips", sessionId] });

  const aprobados = clips.filter((c) => c.listo_para_publicar && !c.descartado).length;
  const descartados = clips.filter((c) => c.descartado).length;
  const pendientes = clips.length - aprobados - descartados;
  const finalizada = sessionQuery.data?.pasos.fin.estado === "ok";

  return (
    <section className="panel">
      <p className="migas">
        <Link to={`/sesiones/${sessionId}`}>← Detalle de la sesión</Link>
      </p>
      <h1>Revisión de clips — {sessionId}</h1>

      <div className="barra-revision">
        <span className="pill pill-ok">{aprobados} aprobados</span>
        <span className="pill pill-muted">{descartados} descartados</span>
        <span className={`pill ${pendientes ? "pill-warn" : "pill-muted"}`}>{pendientes} sin decidir</span>
        {finalizada ? (
          <span className="pill pill-ok">Revisión finalizada</span>
        ) : (
          <button
            className="btn btn-primary"
            disabled={pendientes > 0 || finalizarMutation.isPending}
            title={pendientes ? "Aprueba o descarta cada clip antes de finalizar" : undefined}
            onClick={() => finalizarMutation.mutate()}
          >
            {finalizarMutation.isPending ? "Finalizando..." : "Finalizar revisión"}
          </button>
        )}
      </div>
      {finalizarMutation.isError && <p className="error">{(finalizarMutation.error as Error).message}</p>}

      {clips.length === 0 && (
        <p className="hint">Todavía no hay clips marcados para publicar en esta sesión.</p>
      )}

      <div className="grilla-clips">
        {clips.map((clip) => (
          <ClipCard
            key={clip.clip_id}
            clip={clip}
            sessionId={sessionId!}
            canalId={canalId}
            onChanged={invalidate}
          />
        ))}
      </div>
    </section>
  );
}

function ClipCard({
  clip,
  sessionId,
  canalId,
  onChanged,
}: {
  clip: ClipView;
  sessionId: string;
  canalId: string | undefined;
  onChanged: () => void;
}) {
  const [editando, setEditando] = useState(false);
  const [l1, setL1] = useState(clip.texto_linea1);
  const [l2, setL2] = useState(clip.texto_linea2);
  const [inicio, setInicio] = useState(clip.rango_original.inicio ?? "");
  const [fin, setFin] = useState(clip.rango_original.fin ?? "");
  const [razon, setRazon] = useState("");
  const [link, setLink] = useState(clip.publicado?.tiktok?.url ?? "");

  const approveMutation = useMutation({
    mutationFn: () => api.approveClip(sessionId, clip.clip_id),
    onSuccess: onChanged,
  });

  const editMutation = useMutation({
    mutationFn: () =>
      api.editClip(sessionId, clip.clip_id, {
        canal_id: canalId,
        texto_linea1: l1,
        texto_linea2: l2,
        inicio,
        fin,
      }),
    onSuccess: () => {
      setEditando(false);
      onChanged();
    },
  });

  // CLIP-33: el link del video publicado enlaza el clip con su resultado real (etiqueta por audiencia)
  const publicadoMutation = useMutation({
    mutationFn: () => api.registrarPublicado(sessionId, clip.clip_id, link),
    onSuccess: onChanged,
  });

  const discardMutation = useMutation({
    mutationFn: () => api.discardClip(sessionId, clip.clip_id, { canal_id: canalId, razon: razon || undefined }),
    onSuccess: onChanged,
  });

  if (clip.descartado) {
    return (
      <article className="clip-card clip-descartado">
        <h3>
          {clip.clip_id} <span className="pill pill-muted">descartado</span>
        </h3>
        <p>{clip.texto_linea1} / {clip.texto_linea2}</p>
      </article>
    );
  }

  const scoreClase = clip.score >= 8 ? "score-alto" : clip.score >= 5 ? "score-medio" : "score-bajo";

  return (
    <article className="clip-card">
      <h3>
        <span>{clip.clip_id}</span>
        <span className={`score-badge ${scoreClase}`}>{clip.score}/10</span>
        {clip.listo_para_publicar && <span className="pill pill-ok">aprobado</span>}
        {(clip.juez?.fuerza ?? 0) >= 7 && (
          <span className="pill pill-ok" title="Fuerza 7 o más: revisar primero">⭐ prioridad</span>
        )}
        {clip.fuente?.tipo === "medios" && (
          <span className="pill" title={`Contenido de terceros (R-01) · sobre ${clip.fuente.sobre ?? "?"}`}>
            📺 medios · {clip.fuente.canal_origen ?? "canal desconocido"}
          </span>
        )}
      </h3>

      {(clip.control_calidad?.length ?? 0) > 0 && (
        <div className="hint" style={{ color: "#b45309" }} title="Control de calidad automático: revisar antes de aprobar">
          {clip.control_calidad!.map((h) => (
            <div key={h.codigo}>⚠ {h.detalle}</div>
          ))}
        </div>
      )}

      {clip.tiene_video && (
        <video controls preload="metadata" src={api.clipVideoUrl(sessionId, clip.clip_id)} />
      )}

      {!editando ? (
        <>
          <p className="texto-clip">
            {clip.texto_linea1}
            <br />
            {clip.texto_linea2}
          </p>
          <p className="rango">
            {clip.rango_original.inicio} → {clip.rango_original.fin} (
            {clip.rango_original.duracion_segundos}s)
          </p>
          <p className="hashtags">{clip.hashtags.map((h) => `#${h.replace(/^#/, "")}`).join(" ")}</p>

          {clip.juez && (
            <details className="por-que-juez" open>
              <summary>Por qué lo eligió el juez</summary>
              <p>
                <span className="pill">{TIPO_MOMENTO_LABEL[clip.juez.tipo ?? ""] ?? clip.juez.tipo}</span>
                {clip.juez.fuerza !== null && <span className="hint"> · fuerza {clip.juez.fuerza}/10</span>}
              </p>
              {clip.juez.en_juego && (
                <p>
                  <strong>En juego:</strong> {clip.juez.en_juego}
                </p>
              )}
              {clip.juez.parecidos && clip.juez.parecidos.length > 0 && (
                <p className="hint">Se parece a: «{clip.juez.parecidos[0]}»</p>
              )}
              {clip.juez.por_que && <p className="hint">{clip.juez.por_que}</p>}
            </details>
          )}

          {clip.listo_para_publicar && (
            <div className="link-publicado">
              <input
                type="url"
                placeholder="Link del video ya publicado en TikTok"
                value={link}
                onChange={(e) => setLink(e.target.value)}
              />
              <button
                className="btn btn-secondary"
                onClick={() => publicadoMutation.mutate()}
                disabled={!link.trim() || publicadoMutation.isPending}
              >
                {clip.publicado?.tiktok ? "Actualizar link" : "Guardar link"}
              </button>
              {clip.publicado?.tiktok && <span className="hint"> ✓ enlazado</span>}
              {publicadoMutation.isError && (
                <p className="hint">{(publicadoMutation.error as Error).message}</p>
              )}
            </div>
          )}

          <div className="acciones">
            <button
              className="btn btn-primary"
              onClick={() => approveMutation.mutate()}
              disabled={approveMutation.isPending}
            >
              Aprobar
            </button>
            <button className="btn btn-secondary" onClick={() => setEditando(true)}>
              Editar
            </button>
            <details>
              <summary>Descartar</summary>
              <input
                type="text"
                placeholder="Razón (opcional)"
                value={razon}
                onChange={(e) => setRazon(e.target.value)}
              />
              <button
                className="btn btn-danger"
                onClick={() => discardMutation.mutate()}
                disabled={discardMutation.isPending}
              >
                Confirmar descarte
              </button>
            </details>
          </div>
        </>
      ) : (
        <form
          className="form-edicion"
          onSubmit={(e) => {
            e.preventDefault();
            editMutation.mutate();
          }}
        >
          <label>
            Línea 1
            <input value={l1} onChange={(e) => setL1(e.target.value)} />
          </label>
          <label>
            Línea 2
            <input value={l2} onChange={(e) => setL2(e.target.value)} />
          </label>
          <label>
            Inicio (HH:MM:SS)
            <input value={inicio} onChange={(e) => setInicio(e.target.value)} />
          </label>
          <label>
            Fin (HH:MM:SS)
            <input value={fin} onChange={(e) => setFin(e.target.value)} />
          </label>
          <div className="acciones">
            <button type="submit" className="btn btn-primary" disabled={editMutation.isPending}>
              {editMutation.isPending ? "Re-cortando..." : "Guardar y re-cortar"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setEditando(false)}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      {(approveMutation.isError || editMutation.isError || discardMutation.isError) && (
        <p className="error">
          {(
            (approveMutation.error ?? editMutation.error ?? discardMutation.error) as Error
          )?.message}
        </p>
      )}
    </article>
  );
}
