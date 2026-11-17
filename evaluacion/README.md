# Evaluación de calidad

Mide con números si un cambio mejora la selección de clips (épica Q1, CLIP-20).

## 1. Exportar los casos (una vez, en la laptop del operador)

Las transcripciones están en la laptop (`legacy/stream_data/`, `legacy/investigacion/<nicho>/muestra/`), no en el repo.

```bash
python -m evaluacion.exportar_casos zapatillas_peru
```

Escribe dos archivos (solo texto, sin videos ni secretos); revisarlos y subirlos:
- `evaluacion/casos/zapatillas_peru.yaml`: casos del juez (ventanas de transcripción).
- `evaluacion/casos/zapatillas_peru.cobertura.yaml`: un caso por chunk con correcciones (transcripción completa + rangos aprobados y descartados).

- **Correcciones del editor** → aprobado/editado = publicar, descartado = no publicar.
- **Muestra medida** → `top` y `propia_top` = publicar, `fondo` = no publicar.

## 2. Evaluar

```bash
python -m evaluacion.evaluar zapatillas_peru                # casos reales
python -m evaluacion.evaluar zapatillas_peru --solo-sinteticos   # prueba rápida del evaluador
```

Por cada caso ejecuta el juez del piloto (`legacy/agentes/juez.py`) con la memoria del nicho y compara con lo
esperado. Resumen: acierto, precisión (de lo que publica, cuánto debía), recall (de lo que debía, cuánto publica),
matriz VP/FP/VN/FN y acierto de tipo. Guarda el detalle en `evaluacion/resultados/`.

IA: `AI_PROVIDER` (por defecto `claude_cli`, sin API de pago); `--proveedor` lo cambia para una corrida.

## 3. Cobertura del detector (A1 → A2)

```bash
python -m evaluacion.cobertura zapatillas_peru [--repeticiones 3] [--solape 0.5]
```

Ejecuta el detector del piloto sobre cada chunk completo y mide cuántos de los momentos aprobados por el editor
vuelve a proponer (un esperado cuenta si algún rango lo cubre en al menos 50% de su duración). Reporta cobertura,
candidatos por chunk, descartados que vuelve a proponer y la lista de momentos que se escaparon.

## 4. Variación de la IA

`evaluar` y `cobertura` aceptan `--repeticiones N`: corren todo N veces y reportan media/mín/máx y los casos
inestables (resultado distinto entre corridas). Para la línea base: N = 3.

## Cuidados

- **Sin filtración:** en un caso que sale de una corrección, esa corrección se quita del prompt del juez.
- La memoria del nicho (`referencias.yaml`) cita títulos de algunos clips de la muestra; el juez ve la
  transcripción, no el título, pero el riesgo de sesgo existe y se tiene en cuenta al leer los números.
- Los casos `sintetico` solo prueban el evaluador: no miden calidad.
