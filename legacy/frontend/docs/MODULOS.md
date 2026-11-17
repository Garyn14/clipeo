# Módulos del frontend

## `src/api/`

- **`types.ts`** — interfaces TypeScript espejo de los esquemas que devuelve el backend (`backend/docs/API.md`). Ningún tipo se infiere de forma implícita desde el fetch — si el backend cambia una forma de respuesta, este archivo es el primer lugar a actualizar.
- **`client.ts`** — un único objeto `api` con un método por endpoint. `request<T>()` centraliza el fetch + manejo de error (lee `detail` del JSON de FastAPI en errores 4xx/5xx y lo lanza como `Error`, que React Query expone en `mutation.error`/`query.error`).

## `src/pages/`

- **`NuevaCorrida.tsx`** — único formulario de la app. `useQuery` para poblar el `<select>` de canales, `useMutation` para `POST /runs`; al resolver, navega a `/runs/:runId` vía `useNavigate`.
- **`EstadoCorrida.tsx`** — de solo lectura. El `refetchInterval` de la query es una función que mira `query.state.data?.estado`: sigue polleando mientras sea `"corriendo"`, se detiene solo al llegar a `"completado"`/`"fallido"` — evita pollear para siempre una corrida ya terminada.
- **`Sesiones.tsx`** — tabla simple, una fila por sesión de `stream_data/`. `progreso` viene ya clasificado por el backend (`sin_chunks`/`en_curso`/`con_errores`/`completado`) — el frontend no reimplementa esa lógica de conteo, solo la muestra.
- **`RevisionClips.tsx`** — la pantalla con más estado local. Estructura:
  - El componente de página (`RevisionClips`) solo trae la lista de clips + el `config` de la sesión (para saber qué `canal_id` pasarle al backend en los eventos de corrección/descarte).
  - `ClipCard` (subcomponente en el mismo archivo — no se separó a su propio módulo porque solo lo usa esta página) maneja el estado de edición local (`editando`, campos del form) y las tres mutaciones (`approveMutation`, `editMutation`, `discardMutation`). Cada mutación exitosa llama `onChanged`, que invalida la query `["clips", sessionId]` en el componente padre — así la grilla entera se refresca con el estado real del backend en vez de mutar estado local a mano.
  - Un clip con `descartado: true` (ver `backend/docs/ARQUITECTURA.md` — numeración estable de clips) se renderiza como una tarjeta apagada sin acciones, en vez de desaparecer de la grilla.

## Qué falta a propósito (no es un olvido)

- Sin manejo de "sesión expirada"/auth — no hay auth en v1 (ver `backend/docs/DECISIONES.md`).
- Sin componente de layout/diseño compartido más allá de `App.css` — un solo archivo de estilos alcanza para 4 pantallas; se separará si el árbol de componentes crece.
- Sin tests automatizados de UI todavía — la verificación de este v1 fue manual (Playwright ad hoc contra sesiones reales de `stream_data/`, no un suite versionado).
