# Mapa de cuentas y levantamiento de Colab

> Decisión del operador (2026-11-19). Este repositorio es **público**: aquí no van correos, contraseñas ni tokens.
> Los datos concretos de cada cuenta están en **`cuentas.local.yaml`** (raíz, ignorado por git; plantilla
> `cuentas.example.yaml`). Ahí van solo cuentas e identificadores: los secretos siguen en `.env`.

## Reglas

1. **Claude nunca inicia sesión.** No escribe contraseñas, códigos ni tokens en ningún formulario. Si una sesión
   venció, se lo pide al operador, que inicia sesión en el panel del navegador.
2. **Claude sí puede usar las sesiones ya iniciadas** en el navegador integrado de la app de Claude. Requisito: en el
   panel del navegador, ⋯ → **Conservar cookies → Compartidas** (con "Hasta salir" se borran al cerrar la app).
3. **TikTok:** nunca publicar, editar, borrar ni cambiar la visibilidad de los videos privados propios del operador.
   Solo se actúa sobre borradores de Clipeo que correspondan a clips aprobados.
4. Nunca cerrar sesión ni cambiar ajustes o credenciales de una cuenta.

## Cuentas

| Servicio | Cuenta | Dónde está el dato | Quién la usa |
|---|---|---|---|
| Google / **Colab** (transcripción) | Cuenta por defecto del operador | `cuentas.local.yaml` → `colab.defecto` | Claude levanta Colab solo, en el navegador integrado |
| Colab, cuenta de respaldo | Otra cuenta del operador, si se acaba el cupo de GPU | `cuentas.local.yaml` → `colab.respaldo` (la cambia el operador) | Operador |
| GitHub | `Garyn14` | `gh` CLI ya autenticado | Claude (PRs, comentarios) |
| Jira | `personal-clipeo.atlassian.net`, proyecto `CLIP` | Conector de Atlassian | Claude |
| TikTok (publicación) | Cuenta del nicho, conectada por OAuth en el panel → Publicaciones | `data/publicacion.db` (local) | Motor de publicación (borradores) |
| YouTube Shorts | Canal del nicho, conectado por OAuth en el panel | `data/publicacion.db` (local) | Motor de publicación (espejo) |

Los Secrets del notebook (`HF_TOKEN`, `COLAB_AUTH_TOKEN`/`AUTH_TOKEN`) los carga el operador en Colab: Claude no
los ve ni los escribe.

## Levantar Colab (lo hace Claude, sin el operador)

1. Leer `colab.defecto` de `cuentas.local.yaml`. Abrir en el navegador integrado
   `https://colab.research.google.com/github/Garyn14/clipeo/blob/main/legacy/colab/transcripcion_colab.ipynb`
   y comprobar que la cuenta activa (avatar arriba a la derecha) es esa. Si es otra o no hay sesión: **parar y avisar**
   al operador (no iniciar sesión ni cambiar de cuenta por su cuenta).
2. Entorno de ejecución → GPU T4.
3. Ejecutar **celdas 1 y 2** (encolar la 2 detrás de la 1) → **esperar en segundo plano ~7 min** → una sola
   revisión → **Reiniciar sesión** (paleta *Comandos* → "Reiniciar sesión"; el atajo Ctrl+M . no siempre responde)
   → ejecutar **celda 3** → **esperar en segundo plano ~2 min** → leer la URL. Si falla, reintentar. Si Colab pide
   dar acceso a un Secret, avisar al operador (es su decisión).
4. Copiar la URL `https://….trycloudflare.com` que imprime la celda 3 a `COLAB_TRANSCRIBE_URL` en el `.env`.
5. Comprobar el túnel (`colab_vivo` o la página Fuentes del panel, que muestra el estado).
6. Si se acabó el cupo de GPU, avisar al operador para pasar a la cuenta de respaldo.

**Ahorro de tokens:** no vigilar Colab con esperas, capturas o consultas repetidas. Las esperas se hacen con un
temporizador en segundo plano (p. ej. `sleep 420` lanzado en background: avisa al terminar y no consume nada mientras
corre) y después se revisa **una sola vez**. Objetivo: ~8–10 llamadas por levantamiento (antes ~30). CLIP-65 simplifica
el notebook a un solo "Ejecutar todas" sin reinicio.

Ver también `docs/OPERACION.md` §2.

## Otra máquina

Copiar `cuentas.local.yaml` a mano (igual que `.env`), o crearlo desde `cuentas.example.yaml`.
