# Guía de operación (CLIP-58)

Cómo se opera Clipeo día a día en la laptop del operador, y cómo montarlo en otra máquina. Comandos desde la raíz del
repo (`D:\clipeo` en la laptop) salvo que se indique `legacy/`.

## 1. Levantar todo

```bash
python -m herramientas.levantar
```

Arranca la API con el motor de publicación y el panel de revisión (http://localhost:5173), y muestra si las cuentas de
TikTok y YouTube están conectadas y si el túnel de Colab vive. **Ctrl+C** lo apaga. Mientras esté apagado, la cola de
publicación espera.

## 2. Colab (transcripción, obligatoria)

La transcripción se hace **solo en Colab** (WhisperX local no se usa).

> Claude puede levantarlo solo en el navegador integrado con la cuenta por defecto: ver `docs/CUENTAS.md`.

1. Abrir `legacy/colab/transcripcion_colab.ipynb` en Colab (desde GitHub) con una cuenta que tenga los Secrets
   `HF_TOKEN` y `COLAB_AUTH_TOKEN` (o `AUTH_TOKEN`), con "Acceso del notebook".
2. GPU T4 → ejecutar **celdas 1 y 2** → **Entorno de ejecución → Reiniciar sesión** → ejecutar **celda 3** (si falla,
   reintentar; la primera vez Colab pide dar acceso a cada Secret).
3. Copiar la URL `https://….trycloudflare.com` a `COLAB_TRANSCRIBE_URL` en `.env`.
4. Si se acaba el cupo de GPU de una cuenta, cambiar de cuenta.

El pipeline comprueba el túnel antes de descargar y para con un mensaje si está caído (CLIP-56).

## 3. Producir clips

- **Fuentes fijas del cliente (recomendado):** panel → **Fuentes** → *Ejecutar* (lo nuevo de sus canales y de los
  noticieros desde la última revisión) → marcar candidatos → *Procesar*. Sin cron: se corre a mano cuando quieras.
  Por terminal, desde `legacy/`: `python -m investigacion.fuentes_estaticas ejecutar zapatillas_peru` y luego
  `procesar zapatillas_peru --todos`. Los canales se editan en `legacy/investigacion/zapatillas_peru/fuentes.yaml`.
- **Medios (TV/prensa):** desde `legacy/`
  ```bash
  python -m investigacion.fuentes_medios buscar zapatillas_peru --sobre fritz
  python -m investigacion.fuentes_medios listar zapatillas_peru
  python -m investigacion.fuentes_medios procesar zapatillas_peru 1 3
  ```
- **Un video suelto:** `python legacy/pipeline.py --video "<url>" --config zapatillas_peru --colab`
  (medios: agregar `--medios --sobre fritz`).

## 4. Revisar y publicar

1. Panel → sesión → círculo **Revisión** → Aprobar / Editar / Descartar → **Finalizar revisión**.
   Los avisos **⚠** son del control de calidad (CLIP-51/52): mirar el clip antes de aprobar.
2. Al aprobar, el clip entra a la cola: **YouTube** se publica solo (público) en los horarios 8/12/16/20;
   **TikTok** llega como borrador a la app (Actividad) y el operador lo publica desde el celular con el texto del panel.
3. "Enviar ahora" en Publicaciones lo manda sin esperar el horario.
4. Publicado en TikTok → pegar el link en "Link del video ya publicado" de la revisión.

**Regla:** la cuenta de TikTok tiene videos privados del operador. **Nunca** publicarlos ni tocarlos.

## 5. Medir y aprender (semanal)

Desde `legacy/`:

```bash
python -m investigacion.medir_publicados zapatillas_peru
python -m investigacion.aprendizaje zapatillas_peru
python -m evaluacion.experimento_titulo zapatillas_peru
```

## 6. Montar en otra máquina

1. Python 3.10+, Node.js, FFmpeg, `yt-dlp`; `pip install -r legacy/requirements.txt`; `npm install` en
   `legacy/frontend`.
2. Copiar el `.env` (secretos: **nunca** por chat ni al repo) y la carpeta `data/` (base de publicación con las cuentas).
   Si no se copia `data/`, hay que reconectar TikTok y YouTube en el panel.
3. `.env` con rutas relativas a la raíz: `CLIPEO_STREAM_DATA=stream_data`, `PUBLICACION_DB=data/publicacion.db`.
4. Modelo SFace (37 MB, fuera del repo): ver `legacy/edicion_video/assets/modelos/README.md`.
5. Caras de referencia de Fritz (dato biométrico, fuera del repo):
   `python -m edicion_video.referencia_cara fritz <videos de su canal>` desde `legacy/`.
6. `python -m herramientas.levantar`.
