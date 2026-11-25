import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { PageHeader } from "../components/ui";
import type { EnvField, PerfilClaude } from "../api/types";

// CLIP-83: la página se ordena por secciones; lo que casi no se toca va plegado en "Avanzado".
const SECCIONES: { id: string; titulo: string; descripcion: string }[] = [
  { id: "transcripcion", titulo: "Transcripción (Colab)", descripcion: "Servidor de GPU que transcribe los videos." },
  { id: "ia", titulo: "IA (Claude)", descripcion: "Quién responde en los pasos de IA del pipeline." },
  { id: "tiktok", titulo: "Publicación · TikTok", descripcion: "App de TikTok for Developers para enviar borradores." },
  { id: "youtube", titulo: "Publicación · YouTube Shorts", descripcion: "Cliente OAuth de Google Cloud para subir Shorts." },
  { id: "pruebas", titulo: "Pruebas", descripcion: "Solo para probar el panel con cuentas simuladas." },
];

export function Configuracion() {
  const queryClient = useQueryClient();
  const envQuery = useQuery({ queryKey: ["env"], queryFn: api.getEnvStatus });

  const [valores, setValores] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  // Precarga los campos no-secretos con su valor actual; los secretos
  // arrancan vacíos (nunca se leen en texto plano desde el backend).
  useEffect(() => {
    if (!envQuery.data) return;
    const iniciales: Record<string, string> = {};
    for (const field of envQuery.data) {
      if (!field.secret) iniciales[field.key] = field.value;
    }
    setValores((prev) => ({ ...iniciales, ...prev }));
  }, [envQuery.data]);

  const updateMutation = useMutation({
    mutationFn: (values: Record<string, string>) => api.updateEnv(values),
    onSuccess: () => {
      setSaved(true);
      queryClient.invalidateQueries({ queryKey: ["env"] });
      setTimeout(() => setSaved(false), 3000);
    },
  });

  if (envQuery.isLoading) return <p>Cargando configuración...</p>;
  if (envQuery.isError) return <p className="error">{(envQuery.error as Error).message}</p>;

  const campos = envQuery.data ?? [];

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cambios: Record<string, string> = {};
    for (const field of campos) {
      const actual = valores[field.key] ?? "";
      if (field.secret) {
        if (actual.trim()) cambios[field.key] = actual;
      } else if (actual !== field.value) {
        cambios[field.key] = actual;
      }
    }
    if (Object.keys(cambios).length === 0) return;
    updateMutation.mutate(cambios);
  };

  const renderCampo = (field: EnvField) => (
    <CampoEnv
      key={field.key}
      field={field}
      valor={valores[field.key] ?? ""}
      onChange={(v) => setValores((prev) => ({ ...prev, [field.key]: v }))}
    />
  );

  return (
    <section className="panel">
      <PageHeader
        seccion="Ajustes"
        titulo="Configuración"
        descripcion={<>Se guarda directo en <code>.env</code> y aplica desde la próxima corrida que lances, sin reiniciar el backend.</>}
      />

      <form onSubmit={handleSubmit} className="form-config">
        {SECCIONES.map((seccion) => {
          const propios = campos.filter((f) => (f.seccion || "pruebas") === seccion.id);
          const normales = propios.filter((f) => !f.avanzado);
          const avanzados = propios.filter((f) => f.avanzado);
          if (propios.length === 0 && seccion.id !== "ia") return null;
          return (
            <fieldset key={seccion.id} className="config-seccion">
              <legend>{seccion.titulo}</legend>
              <p className="config-seccion-desc">{seccion.descripcion}</p>
              {seccion.id === "ia" && <CuentaClaudeSeccion />}
              {normales.map(renderCampo)}
              {avanzados.length > 0 && (
                <details className="config-avanzado">
                  <summary>Avanzado ({avanzados.length})</summary>
                  {avanzados.map(renderCampo)}
                </details>
              )}
            </fieldset>
          );
        })}

        <div className="acciones">
          <button type="submit" className="btn btn-primary" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "Guardando..." : "Guardar cambios"}
          </button>
          {saved && <span className="pill pill-ok">guardado</span>}
        </div>

        {updateMutation.isError && (
          <p className="error">{(updateMutation.error as Error).message}</p>
        )}
      </form>
    </section>
  );
}

function CampoEnv({
  field,
  valor,
  onChange,
}: {
  field: EnvField;
  valor: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="campo-env">
      <span className="campo-env-titulo">
        {field.label}
        {field.is_set ? (
          <span className="pill pill-ok">configurado</span>
        ) : (
          <span className="pill pill-warn">sin configurar</span>
        )}
      </span>
      <input
        type={field.secret ? "password" : "text"}
        value={valor}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.secret ? (field.masked_value || "sin configurar") : ""}
        autoComplete="off"
      />
      <span className="campo-env-help">{field.help}</span>
    </label>
  );
}

// ── CLIP-83: cuenta de Claude que usa el pipeline ──

function CuentaClaudeSeccion() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["cuenta-claude"], queryFn: api.getCuentaClaude });
  const [nuevo, setNuevo] = useState("");
  const [copiado, setCopiado] = useState("");

  const refrescar = () => queryClient.invalidateQueries({ queryKey: ["cuenta-claude"] });
  const activar = useMutation({
    mutationFn: (nombre: string) => api.activarPerfilClaude(nombre),
    onSuccess: (data) => queryClient.setQueryData(["cuenta-claude"], data),
  });
  const crear = useMutation({
    mutationFn: (nombre: string) => api.crearPerfilClaude(nombre),
    onSuccess: () => {
      setNuevo("");
      refrescar();
    },
  });

  const copiar = async (perfil: PerfilClaude) => {
    try {
      await navigator.clipboard.writeText(perfil.comando_login);
      setCopiado(perfil.nombre);
      setTimeout(() => setCopiado(""), 2500);
    } catch {
      /* sin permiso de portapapeles: el comando queda visible para copiarlo a mano */
    }
  };

  return (
    <div className="campo-env cuenta-claude">
      <span className="campo-env-titulo">
        Cuenta de Claude (pipeline)
        <button type="button" className="btn btn-secondary" onClick={refrescar} disabled={query.isFetching}>
          {query.isFetching ? "Revisando..." : "Revisar sesiones"}
        </button>
      </span>
      <span className="campo-env-help">
        Cada perfil es una sesión propia de Claude Code. Elige cuál gasta el pipeline: el cambio lo toma la siguiente
        llamada, sin cortar lo que esté corriendo. Esta app nunca ve tus tokens.
      </span>

      {query.isLoading && <p className="hint">Revisando sesiones...</p>}
      {query.isError && <p className="error">{(query.error as Error).message}</p>}
      {query.data && !query.data.activo_existe && (
        <p className="error">
          El perfil activo «{query.data.activo}» ya no existe: el pipeline fallará hasta que elijas otro.
        </p>
      )}

      {query.data && (
        <ul className="perfiles-claude">
          {query.data.perfiles.map((p) => {
            const esActivo = p.nombre === query.data!.activo;
            return (
              <li key={p.nombre || "_defecto"} className={esActivo ? "activo" : ""}>
                <div className="perfil-cabecera">
                  <strong>{p.nombre || "Por defecto (sesión de esta máquina)"}</strong>
                  {esActivo && <span className="pill pill-ok">activo</span>}
                  {p.sesion ? (
                    <span className="perfil-cuenta">
                      {p.cuenta || "sesión iniciada"}
                      {p.plan && ` · plan ${p.plan}`}
                    </span>
                  ) : (
                    <span className="pill pill-warn">{p.error ? "no se pudo revisar" : "sin sesión"}</span>
                  )}
                  {!esActivo && (
                    <button
                      type="button"
                      className="btn btn-secondary"
                      disabled={activar.isPending || !p.sesion}
                      title={p.sesion ? "" : "Primero inicia sesión en este perfil"}
                      onClick={() => activar.mutate(p.nombre)}
                    >
                      Usar este
                    </button>
                  )}
                </div>
                {!p.sesion && p.nombre && (
                  <div className="perfil-login">
                    <span>
                      Inicia sesión una vez en PowerShell (se abre el navegador) y luego pulsa «Revisar sesiones»:
                    </span>
                    <code>{p.comando_login}</code>
                    <button type="button" className="btn btn-secondary" onClick={() => copiar(p)}>
                      {copiado === p.nombre ? "copiado" : "Copiar"}
                    </button>
                  </div>
                )}
                {p.error && <span className="campo-env-help">{p.error}</span>}
              </li>
            );
          })}
        </ul>
      )}

      <div className="perfil-nuevo">
        <input
          type="text"
          value={nuevo}
          placeholder="nuevo perfil, p. ej. cuenta2"
          onChange={(e) => setNuevo(e.target.value)}
          autoComplete="off"
        />
        <button
          type="button"
          className="btn btn-secondary"
          disabled={!nuevo.trim() || crear.isPending}
          onClick={() => crear.mutate(nuevo)}
        >
          Crear perfil
        </button>
      </div>
      {crear.isError && <p className="error">{(crear.error as Error).message}</p>}
      {activar.isError && <p className="error">{(activar.error as Error).message}</p>}
    </div>
  );
}
