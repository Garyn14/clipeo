# Línea base de calidad — piloto `v1_full` (zapatillas_peru)

> Fecha: 2026-11-17 · Sprint S2 (CLIP-25) · Proveedor de IA: Claude Code (`claude_cli`), sin API de pago.
> Es el **punto de comparación** de los sprints de calidad (Q2–Q5): cada cambio se mide contra estos números.

## 1. Resumen ejecutivo

| Etapa | Métrica | Valor (3 corridas) | Lectura |
|---|---|---|---|
| **Detector** (A1 → A2) | Cobertura de los momentos que aprobaste | **83%** (75–87,5%) | Encuentra la mayoría: **no es el cuello de botella** |
| **Juez** | Precisión | **0,94** (0,88–0,94) | Cuando dice "publicar", casi siempre acierta |
| **Juez** | Recall | **0,25** (0,23–0,25) | **Descarta 3 de cada 4 clips buenos** |
| **Juez** | Acierto global | 0,40 (0,38–0,40) | Lo arrastra el recall |

**Conclusión:** el sistema no pierde clips buenos por no encontrarlos, sino porque **el juez es demasiado
estricto**. Muchos rechazos se explican por cómo está **cortado** el momento ("arranca con relleno", "no se
entiende solo") y por la **calidad de la transcripción** (frases mal captadas, hablantes sin identificar), no por
falta de historia. Parte de los "errores" también vienen de **etiquetas dudosas** en los casos de evaluación (§4).

## 2. Qué se midió

| Conjunto | Casos | Buenos / malos | Origen |
|---|---|---|---|
| Juez · correcciones del editor | 19 | 16 / 3 | Tus aprobaciones y descartes en la revisión |
| Juez · muestra medida | 58 | 44 / 14 | Clips de TikTok: `top` y `propia_top` = buenos, `fondo` = malos |
| Cobertura | 7 chunks | 16 aprobados, 3 descartados | Sesiones con correcciones, chunk completo |

Cada evaluación se corrió **3 veces**. Sin filtración: en los casos de correcciones, la propia corrección se quitó
del prompt del juez. Herramientas: `python -m evaluacion.evaluar | cobertura | analizar` (ver `evaluacion/README.md`).
Resultados crudos: `evaluacion/resultados/20261117_132758_zapatillas_peru.json` (juez) y
`evaluacion/resultados/20261117_132029_zapatillas_peru_cobertura.json` (cobertura).

## 3. Resultados

### 3.1 Juez (decisión por mayoría de 3 corridas)

| Subconjunto | VP | FP | VN | FN | Precisión | Recall |
|---|---|---|---|---|---|---|
| Correcciones del editor | 5 | 1 | 2 | 11 | 0,83 | 0,31 |
| Muestra medida | 10 | 0 | 14 | 34 | 1,00 | 0,23 |
| **Total** | **15** | **1** | **16** | **45** | **0,94** | **0,25** |

Por grupo de la muestra:

| Grupo | Casos | El juez publicó |
|---|---|---|
| `fondo` (rindieron poco) | 14 | **0**: los descarta todos ✅ |
| `propia_top` (tus mejores clips en @nandoclips93) | 8 | 4 |
| `top` (mejores clips de otras cuentas) | 36 | 6 |

- **Estabilidad:** las corridas casi no cambian (acierto 0,38–0,40). Solo 4 de 77 casos cambian de decisión entre
  corridas, y los 4 son correcciones. El juez es **consistente, pero consistentemente estricto**.
- **Tipo de momento:** de los clips buenos, el juez asignó `ninguno` a 45. El acierto de tipo es 0,44 (solo en
  casos con tipo esperado).
- **Único falso positivo:** "El tío Fritz premia a Raffo" (lo descartaste; el juez lo publica en las 3 corridas).

### 3.2 Detector (cobertura)

| Corrida | Cobertura | Candidatos por chunk |
|---|---|---|
| 1 | 87,5% (14/16) | 8,9 |
| 2 | 75,0% (12/16) | 10,1 |
| 3 | 87,5% (14/16) | 9,4 |

- Momentos que **se escapan** (en la misma sesión, `za-cob-002`): "El tío Fritz regala billetera" y "El tío Fritz
  pilla a Rafael".
- **Variación:** 4 de 7 chunks dan resultados distintos entre corridas. Conviene medir con 3 corridas siempre.
- Vuelve a proponer los 3 momentos que descartaste. Es esperable: busca amplio y el juez filtra.

## 4. Análisis de errores: ¿falla el juez o la etiqueta?

Los 45 falsos negativos se agruparon por el motivo que da el juez y por lo que muestra el texto. Es una lectura del
texto, **sin ver los videos**; los casos dudosos se validan contigo en la demo (§6).

| Grupo | Casos aprox. | Ejemplos | ¿De quién es el error? |
|---|---|---|---|
| **A. Fuera del nicho** (política, otros streamers, denuncias) | 7 | `za-mues-001` discurso político (408K), `za-mues-018` contenido político (2M), `za-mues-004` chisme de streamers | **Etiqueta dudosa:** la muestra mezcla universos (Yolu, Noto) con temas que no son de este nicho |
| **B. El texto no alcanza** (el clip vive de la imagen o el audio) | 5 | `za-mues-038` solo "¡Abajo!" en 22 s (782K), `za-mues-024` dos frases sueltas | **Falta información:** el juez solo lee texto |
| **C. Anuncios o pitch que sí rindieron** | 5 | `za-mues-054` anuncio de puestos (tu cuenta, outlier 45), `za-mues-028` anuncio (862K) | **Contradice la memoria del nicho**, que dice que los anuncios no funcionan. Hay que revisar esa regla |
| **D. Transcripción mala o hablantes sin identificar** | ~6 | `za-corr-008` "transcripción caótica", `za-corr-011` "'Oye, oye' repetido" | **Falla de etapas previas** (transcripción y Agente 0) que el juez paga |
| **E. Arranque con relleno o momento que no se entiende solo** | ~6 | `za-corr-009` "30 segundos de relleno ('a ver')", `za-corr-010` "solo el preámbulo, la sorpresa no se ve" | **Falla de corte o edición:** el momento es bueno pero está mal cortado |
| **F. Criterio distinto al tuyo** | ~16 | `za-corr-003` "come con su gente", `za-corr-005` "presiona a su técnico", `za-corr-012` "reclama al encargado" | **Diferencia de criterio:** apruebas momentos cotidianos de jefe y trabajadores que la memoria considera "sin conflicto" |

**Recall ajustado:** sin los grupos A y B (etiquetas dudosas o información insuficiente), el recall sube a
**≈0,31**. Sigue bajo: el juez es estricto aun descontando el ruido de las etiquetas.

## 5. Patrones de error

1. **El juez es estricto por diseño y por memoria.** El prompt exige tipo de momento + algo en juego + que se
   entienda solo, y la memoria refuerza "historia, no formato". El resultado: precisión alta, recall bajo.
2. **Juzga el corte, no el momento.** Muchos rechazos son por cómo empieza o termina el rango ("arranca con
   presentación", "termina cortado", "la sorpresa no se ve"). Un mejor corte (gancho primero, sin relleno)
   rescataría parte de esos clips.
3. **La transcripción y los hablantes le restan.** "Transcripción caótica", "hablantes sin identificar" y, en una
   sesión de Fritz, frases atribuidas al "Tío Yolu" (error del Agente 0). El juez castiga lo que no entiende.
4. **El juez cambió de opinión sobre sus propias aprobaciones.** Los 16 clips que aprobaste fueron propuestos por
   el mismo juez en producción; hoy aprueba solo 5. Causas probables: tus descartes posteriores (p. ej. "premio a
   Raffo") ahora pesan en su prompt, y la evaluación no le pasa las pistas del detector (tipo sugerido, qué está en
   juego) ni el mapa de hablantes que sí recibe en producción. **Hay que cerrar esa brecha de fidelidad** para
   comparar bien en los próximos sprints.
5. **La memoria del nicho tiene reglas que los datos contradicen** (anuncios que rinden en tu propia cuenta) y no
   refleja tu gusto por momentos cotidianos de jefe y trabajadores.

## 6. Recomendaciones para los próximos sprints

| Prioridad | Qué | Por qué | Épica |
|---|---|---|---|
| 1 | **Dirección editorial** (gancho primero, recortar relleno, corte que se entienda solo) **y que el juez evalúe el clip ya dirigido** | Ataca el patrón 2, el más accionable | Q2 (S3) |
| 2 | **Calibrar el juez con tu criterio**: decidir cuál manda en los casos F, revisar las reglas de la memoria (anuncios), y medir de nuevo | Recall 0,25 deja muchos clips buenos fuera | Q5 / nuevo ticket |
| 3 | **Fidelidad de la evaluación**: pasar al juez las pistas del detector y el mapa de hablantes, como en producción; etiquetar la muestra por universo y excluir lo fuera del nicho | Patrón 4 y grupo A: hoy la medición es más dura que la producción | Q1 |
| 4 | **Transcripción y hablantes** (Agente 0) | Patrón 3 | Q3 / nuevo ticket |
| 5 | **Detección con más señales** | Cobertura ya es 83%; menos urgente de lo previsto | Q3 (puede bajar de prioridad) |

## 7. Preguntas para el operador (demo)

1. En los casos **F** (momentos cotidianos de jefe y trabajadores), ¿quieres que el juez los publique? Define si
   manda tu criterio o la memoria.
2. Los **anuncios** que rindieron (grupo C), ¿son buenos clips o fueron excepciones?
3. ¿Confirmas que los clips **fuera del nicho** (grupo A) no deberían contar para zapatillas_peru?
