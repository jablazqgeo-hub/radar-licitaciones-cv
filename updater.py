from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from radar import load_recent

DAYS = int(os.environ.get("RADAR_DAYS", "30"))
DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "licitaciones.csv"
META_PATH = DATA_DIR / "metadata.json"


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    def progress(source, pages, diag, oldest):
        oldest_txt = oldest.isoformat() if oldest else "?"
        print(
            f"[{source}] ficheros={pages} expedientes={diag.expedientes_revisados} "
            f"cv_locales={diag.cv_locales} tematicos={diag.tematicos} oldest={oldest_txt}",
            flush=True,
        )

    print(f"Actualizando radar para los últimos {DAYS} días...", flush=True)
    df, errors, diag, by_source = load_recent(DAYS, progress=progress)

    # Guardar siempre el resultado, aunque sea vacío, para que Streamlit refleje el estado real.
    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")

    metadata = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "days": DAYS,
        "opportunities": int(len(df)),
        "diagnostics": {
            "atom_pages": int(diag.paginas),
            "reviewed": int(diag.expedientes_revisados),
            "within_period": int(diag.dentro_periodo),
            "cv_local": int(diag.cv_locales),
            "thematic": int(diag.tematicos),
        },
        "by_source": by_source,
        "errors": errors,
    }
    META_PATH.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)

    # No fallar por una fuente parcial si la otra produjo datos; sí fallar si ambas fallaron y no se revisó nada.
    if diag.expedientes_revisados == 0 and errors:
        print("ERROR: no se pudo revisar ningún expediente.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
