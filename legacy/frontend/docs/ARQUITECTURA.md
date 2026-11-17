# Arquitectura del frontend

## Stack

Vite + React 19 + TypeScript, `react-router-dom` para ruteo, `@tanstack/react-query` para todo el estado de servidor (fetch, cache, polling). Sin Redux ni store global — no hace falta para un v1 con 4 pantallas que en su mayoría solo leen y refrescan datos del backend.

## Cómo correrlo

```
cd frontend
npm install
npm run dev       # http://localhost:5173
```

Apunta por defecto a `http://localhost:8000` (el backend en `backend/`, ver `backend/docs/ARQUITECTURA.md`). Override vía `VITE_API_BASE_URL` si el backend corre en otro puerto/host.

## Páginas y ruteo (`src/App.tsx`)

| Ruta | Página | Qué hace |
|---|---|---|
| `/` | `NuevaCorrida` | Form: modo (`video`/`test`), URL o path, canal/nicho (de `GET /config/canales`). Al enviar, `POST /runs` y redirige a `/runs/:runId`. |
| `/runs/:runId` | `EstadoCorrida` | Pollea `GET /runs/:runId` cada 3s mientras `estado === "corriendo"`; muestra el tail del log y, apenas se descubre, el link a la sesión. |
| `/sesiones` | `Sesiones` | Tabla de `GET /sessions`, refresca cada 5s. |
| `/sesiones/:sessionId` | `RevisionClips` | La pantalla principal: grilla de clips con reproductor de video y acciones Aprobar/Editar/Descartar. |

## Estrategia de datos: polling, no websockets

Todo el estado "en vivo" (progreso de una corrida, lista de sesiones) se resuelve con `refetchInterval` de React Query en vez de una conexión persistente. Para un v1 de un solo usuario operando una corrida a la vez, el costo de un websocket (canal propio en el backend, reconexión, etc.) no se justifica frente a un poll simple cada 3-5s. Si en el futuro se necesita progreso más fino (ej. porcentaje dentro de un chunk, no solo completado/pendiente), ahí sí conviene reconsiderar.

## Por qué no se expone `--revisar` ni el toggle de Colab

Ambos son decisiones ya tomadas para todo el frontend, no parámetros de UI:
- La transcripción siempre va por Colab (WhisperX local descartado por completo) — el backend agrega `--colab` sin que el usuario lo pida.
- La revisión de clips reemplaza por completo el flujo de terminal `--revisar` — el backend siempre lanza el pipeline sin ese flag y la revisión ocurre después, en `/sesiones/:sessionId`.

Ver `backend/docs/DECISIONES.md` para el razonamiento completo.
