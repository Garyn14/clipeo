import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { PageHeader } from "../components/ui";
import type { RunLaunchBody } from "../api/types";

export function NuevaCorrida() {
  const navigate = useNavigate();
  const canalesQuery = useQuery({ queryKey: ["canales"], queryFn: api.getCanales });

  const [modo, setModo] = useState<RunLaunchBody["modo"]>("video");
  const [urlOPath, setUrlOPath] = useState("");
  const [canalId, setCanalId] = useState("");

  const launchMutation = useMutation({
    mutationFn: () =>
      api.launchRun({
        modo,
        url_o_path: urlOPath.trim(),
        canal_id: canalId || undefined,
      }),
    onSuccess: ({ session_id }) => navigate(`/sesiones/${session_id}`),
  });

  return (
    <section className="panel">
      <PageHeader
        seccion="Producción"
        titulo="Nueva corrida"
        descripcion="Procesa un video suelto (enlace o archivo local). La transcripción va siempre por Colab."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          launchMutation.mutate();
        }}
      >
        <label>
          Modo
          <select value={modo} onChange={(e) => setModo(e.target.value as RunLaunchBody["modo"])}>
            <option value="video">Video / URL</option>
            <option value="test">Sesión existente (--test)</option>
          </select>
        </label>

        <label>
          {modo === "video" ? "URL del video" : "Directorio de sesión (stream_data/...)"}
          <input
            type="text"
            value={urlOPath}
            onChange={(e) => setUrlOPath(e.target.value)}
            placeholder={modo === "video" ? "https://tiktok.com/@usuario/live" : "stream_data/20260929_120000"}
            required
          />
        </label>

        <label>
          Canal / nicho
          <select value={canalId} onChange={(e) => setCanalId(e.target.value)}>
            <option value="">default</option>
            {canalesQuery.data?.map((c) => (
              <option key={c.canal_id} value={c.canal_id}>
                {c.canal_id} — {c.descripcion || c.sistema}
              </option>
            ))}
          </select>
        </label>

        <button
          type="submit"
          className="btn btn-primary"
          disabled={launchMutation.isPending || !urlOPath.trim()}
        >
          {launchMutation.isPending ? "Lanzando..." : "Lanzar corrida"}
        </button>
      </form>

      {launchMutation.isError && (
        <p className="error">{(launchMutation.error as Error).message}</p>
      )}
    </section>
  );
}
