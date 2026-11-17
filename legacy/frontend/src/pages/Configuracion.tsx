import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { EnvField } from "../api/types";

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

  return (
    <section className="panel">
      <h1>Configuración</h1>
      <p className="hint">
        Se guarda directo en <code>.env</code> — aplica desde la próxima corrida que lances
        (no hace falta reiniciar el backend).
      </p>

      <form onSubmit={handleSubmit} className="form-config">
        {campos.map((field) => (
          <CampoEnv
            key={field.key}
            field={field}
            valor={valores[field.key] ?? ""}
            onChange={(v) => setValores((prev) => ({ ...prev, [field.key]: v }))}
          />
        ))}

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
