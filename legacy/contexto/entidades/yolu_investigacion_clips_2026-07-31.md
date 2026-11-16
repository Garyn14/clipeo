# Análisis de Viralidad — Sistema de Clipeo (TikTok)
## Universo "Yolu" (La Casa de las Zapatillas — Huánuco, Perú)

Scraping manual del usuario, 2026-07-31. Insumo para enriquecer `contexto/entidades/yolu.yaml` de cara a la primera prueba real del pipeline con contenido del canal propio de Yolu. Complementa `yolu_investigacion_clips_2026-07-29.md` (barrido previo, mismo estilo de análisis) y `yolu_investigacion_web_2026-07-31.md` (investigación de noticias/hechos reales, mismo día).

**Fecha de análisis:** 31/07/2026 · **Plataforma:** TikTok únicamente · **Búsquedas:** "Yolu clips", "La tía yolu", "Matiwasi" · **Método:** lectura del overlay + análisis de comentarios top.

---

## 0. Hallazgo transversal

Las tres búsquedas pertenecen al mismo ecosistema — la tienda "Yolu / La Casa de las Zapatillas" en Huánuco — que funciona como una **"telenovela/reality" episódica** con personajes recurrentes: Tío Yolu (protagonista cómico), Tía Yolu (@tiayolu, jefa/administradora + cuenta propia de baile/lifestyle), Matiwasi (@elmatiwasi1, "hijo", precocidad/inocencia), **Dana/Danna** (vendedora, eje de coqueteo), Jorgito Muñoz (camarógrafo, meme recurrente). El contenido lo reclipean decenas de cuentas (yoluclips19, almanegraclips, satorugojo.clips, babynathsclips1, clips_yoluu, gatitoclips1.0, etc.), multiplicando el alcance del mismo universo narrativo.

**Motores de viralidad detectados**: (1) humor de doble sentido/picardía peruana — mayor generador de comentarios; (2) "chisme" y drama tipo novela; (3) ganchos en el overlay con formato titular/revelación; (4) participación del espectador (retos, debates); (5) personajes-meme recurrentes (fideliza, efecto serie); (6) ternura + precocidad de Matiwasi; (7) audios de tendencia + contenido IA declarado en algunos casos.

## 1. Búsqueda "Yolu clips" — el "reality" de tienda

El clip más viral detectado en toda la investigación: **"Matiwasi hace sus cálculos... ¿De 8am a 8pm son 16 horas?"** (yoluclips19, 104.3K likes) — un reto matemático erróneo que generó debate masivo ("ME HIZO DUDAR ESE CSM", 18.8K likes en el comentario top). Segundo más viral: **"Yolu coquetea, y Matiwasi le avisa a su mamá"** (38.1K) — humor familiar + chisme. También destaca el arco **"Yolu se entera que Danna está con un coronel"** (6.2K, pero con comentarios muy virales por creatividad).

## 2. Búsqueda "La tía yolu" — doble motor

El personaje "Tía Yolu" tiene dos vetas: dentro del reality (autoridad + drama de celos, ej. Jorgito "el más celoso" con overlay "Luciana le dice que se va al chongo"), y su **cuenta propia (@tiayolu)** con contenido de baile/lifestyle que capitaliza la fama del universo — el video más viral de esta búsqueda (244.5K likes) es un baile, no un momento de tienda, y ya recibe **"colaboración pagada"** (branded content). Es el caso más claro de personaje → creadora monetizable dentro del ecosistema.

## 3. Búsqueda "Matiwasi" — precocidad + inocencia

Formatos ganadores confirmados: retos mentales/escolares (el cálculo de horas, 104.3K — el más viral del universo completo), humor de "rol invertido" (el niño vacila/supera a un adulto — "lo vacila al tío Yolu por no saber inglés", 67.8K), contenido de notas escolares ("tío yolu esperaba un 15 pero Matiwasi sacó 10", 34.3K), y ternura/glow-up (corte de pelo, 37.3K). Los comentarios frecuentemente añaden una capa de doble sentido adulto sobre contenido en sí inocente.

## 4. Fórmula del overlay (aplicada a `yolu.yaml`)

El overlay casi siempre es un titular con gancho: **revelación/chisme**, **acción + consecuencia**, **pregunta/reto**, o **etiqueta de personaje** — nunca descripción neutra. Emojis de intriga (👀😏🤣) con moderación. El humor de doble sentido es el motor #1 de comentarios, pero debe quedar apto para todo público. Los clips más comentados dejan una pregunta abierta que la audiencia "completa" en comentarios — el algoritmo premia ese hilo.

**Hashtags dominantes observados**: `#tioyolu`, `#tiayolu`, `#matiwasi`, `#yolu`, `#huanuco_perú`, `#clips`, `#humor`, `#fyp`, `#viral`.

## 5. Qué se integró en `contexto/entidades/yolu.yaml`

- Nuevo personaje: **Dana/Danna** (vendedora, eje de coqueteo/celos, arco "Danna y el coronel").
- Jorgito Muñoz enriquecido con el arco de celos confirmado (no solo especulación de comunidad).
- Vocabulario nuevo: "el coronel", "chongo", "la jaéna", "baje".
- Señales de detección: retos mentales de Matiwasi, humor de rol invertido, contenido escolar, arco Danna/coronel, Yolu coqueteando "delatado" por Matiwasi, contenido propio de @tiayolu.
- `contenido_adicional.tono`: fórmula de gancho (revelación/acción-consecuencia/pregunta/etiqueta de personaje), uso moderado de emojis de intriga, regla de "dejar pregunta abierta" — marcado explícitamente como **confirmado por scraping, no por corrección editorial todavía** (distinto nivel de confianza que las reglas de Franco Vidal, que sí vienen de corrección editorial real).

## Nota de límites

Análisis basado en la vista pública de búsqueda de TikTok (overlays visibles y comentarios destacados), no en analítica oficial de la plataforma. Las fechas relativas ("Hace X h/d") son las que muestra TikTok al momento del scraping. El contenido marcado por TikTok como generado por IA se indicó cuando estaba disponible.
