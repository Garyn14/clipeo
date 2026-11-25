# CLIP-83 · Configuración ordenada y cambio de cuenta de Claude

> Ticket suelto, aprobado por el operador el 2026-11-24 ("Dale el OK, crea el ticket con 1 + A").

## Por qué

El operador tiene más de una cuenta de Claude y quiere elegir desde la app cuál gasta el pipeline. Hasta ahora era
la sesión de Claude Code de la máquina, compartida con la sesión interactiva del agente, y cambiarla requería
`/login` y reiniciar `levantar`. Además, Configuración mostraba 12 campos en una sola lista.

## Diseño técnico ([Líder técnico])

- **Perfiles = carpetas de configuración de Claude Code** (`CLAUDE_CONFIG_DIR`). Cada carpeta guarda su propia
  sesión: verificado con `claude auth status`, que en una carpeta nueva responde "sin sesión" y en la por defecto
  devuelve cuenta y plan. Las carpetas viven **fuera del repo** (`~/.clipeo/claude_perfiles/<nombre>`, configurable
  con `AI_CLI_PERFILES_DIR`) porque contendrán credenciales.
- **Perfil activo = `AI_CLI_PERFIL` en `.env`** (vacío = sesión por defecto, como antes). `cli_provider` lo **relee en
  cada llamada** (`perfiles.config_dir_activo`) y pasa `CLAUDE_CONFIG_DIR` solo al subproceso `claude -p`: un cambio lo
  toma la siguiente llamada de un pipeline en curso, sin cortarlo, y la sesión interactiva no se toca. Si el perfil
  activo ya no existe, el error es fatal (claro) en vez de gastar otra cuenta.
- **Inicio de sesión:** lo hace el operador una vez por perfil en PowerShell
  (`$env:CLAUDE_CONFIG_DIR="<carpeta>"; claude auth login`); la app muestra y copia el comando. La app nunca ve ni guarda
  tokens: el estado sale de `claude auth status --json` (solo cuenta, plan y método).
- **Backend** (`routers/config.py`): `GET /config/claude`, `POST /config/claude/perfiles`, `PUT /config/claude/activo`.
  `env_manager.ENV_FIELDS` suma `seccion` y `avanzado` a cada campo.
- **Frontend** (`pages/Configuracion.tsx`): secciones Transcripción, IA (con la tarjeta "Cuenta de Claude"), Publicación
  TikTok, Publicación YouTube y Pruebas; los campos poco usados (API key de Anthropic, HF token, Redirect URI, simular
  falla) van plegados en "Avanzado".

## Cómo probar

1. Configuración → IA (Claude) → "Cuenta de Claude (pipeline)": aparece "Por defecto" con la cuenta y el plan, activo.
2. Crear un perfil (p. ej. `cuenta2`): queda "sin sesión", con el comando de PowerShell para iniciar sesión.
3. Correr ese comando en una terminal (abre el navegador para elegir la cuenta) y pulsar "Revisar sesiones": aparece
   la cuenta nueva y se activa con "Usar este".
4. Procesar un video: las llamadas a Claude salen de esa cuenta. Volver a "Por defecto" en cualquier momento.

Tests: `tests/test_perfiles_claude.py` (perfiles, proveedor y endpoints).
