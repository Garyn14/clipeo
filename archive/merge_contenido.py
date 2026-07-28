import json
from pathlib import Path

session = Path("stream_data/20260612_210425")
all_contenido = []

for chunk_num in ["chunk_001", "chunk_002", "chunk_003", "chunk_004"]:
    path = session / "chunks" / chunk_num / "contenido.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8")).get("contenido", [])
        n_pub = sum(1 for x in data if x.get("publicar"))
        all_contenido.extend(data)
        print(f"{chunk_num}: {len(data)} items — {n_pub} para publicar")

merged = {"contenido": all_contenido}
out = session / "contenido_completo.json"
out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
total_pub = sum(1 for x in all_contenido if x.get("publicar"))
print(f"TOTAL: {len(all_contenido)} items — {total_pub} para publicar")
print(f"Guardado en: {out}")
