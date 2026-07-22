# iptv-listado-libre

Este repositorio procesa entradas de streams desde la fuente externa no confiable:

- https://raw.githubusercontent.com/Duartegame/TV-TDT/refs/heads/main/m3.txt

## Aviso importante

- La fuente externa se trata como **no confiable**.
- Solo se aceptan streams públicos y razonablemente autorizados según metadatos disponibles.
- Las URLs con credenciales o parámetros sensibles se rechazan automáticamente.
- Importar una entrada **no prueba** que sea legalmente redistribuible.
- El responsable del repositorio debe verificar derechos de emisión y redistribución antes de publicar.

## Flujo recomendado

```bash
python scripts/import_source.py
python scripts/generate_m3u.py
python scripts/validate_m3u.py
pytest
```

- `channels.csv` es la fuente de verdad.
- `canales.m3u` se regenera desde `channels.csv`.

## Ejecución manual del importador

```bash
python scripts/import_source.py
```

Esto descarga la fuente externa, filtra entradas inseguras y actualiza:

- `channels.csv`
- `reports/import-summary.json`
- `reports/rejected-domains.txt`

## Revisión de entradas pendientes

Cuando una URL pública no tiene nombre explícito:

- se crea un nombre temporal neutral `Unidentified public stream NNN`
- `group` se asigna a `Unclassified`
- `needs_review` se marca como `true`

Revise esas filas en `channels.csv` antes de su uso final.

## Regenerar y validar M3U

```bash
python scripts/generate_m3u.py
python scripts/validate_m3u.py
```

## Revisar reportes sanitizados

- `reports/import-summary.json` incluye solo conteos y razones de rechazo.
- `reports/rejected-domains.txt` incluye únicamente hostnames únicos rechazados.

No se almacenan URLs rechazadas completas ni valores de credenciales.
