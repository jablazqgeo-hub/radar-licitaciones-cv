from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from radar import load_incremental_since, merge_incremental

DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "licitaciones.csv"
META_PATH = DATA_DIR / "metadata.json"
RETENTION_DAYS = int(os.environ.get("RADAR_RETENTION_DAYS", "90"))
OVERLAP_HOURS = int(os.environ.get("RADAR_OVERLAP_HOURS", "12"))
BOOTSTRAP_DAYS = int(os.environ.get("RADAR_BOOTSTRAP_DAYS", "3"))
MAX_PAGES = int(os.environ.get("RADAR_MAX_PAGES_PER_SOURCE", "40"))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_meta() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_existing() -> pd.DataFrame:
    if not CSV_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def determine_cutoff(meta: dict, now: datetime) -> tuple[datetime, str]:
    # Se prioriza la última sincronización completamente correcta.
    raw = meta.get("last_successful_sync_utc") or meta.get("updated_at_utc")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            # Solape para capturar correcciones/republicaciones y evitar huecos por retrasos de PLACSP.
            return dt - timedelta(hours=OVERLAP_HOURS), "incremental"
        except Exception:
            pass
    return now - timedelta(days=BOOTSTRAP_DAYS), "bootstrap"


def atomic_write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)


def atomic_write_json(obj: dict, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    started = utcnow()
    previous_meta = load_meta()
    existing = load_existing()
    cutoff, mode = determine_cutoff(previous_meta, started)

    print(f"Modo: {mode}", flush=True)
    print(f"Última base: {previous_meta.get('last_successful_sync_utc') or previous_meta.get('updated_at_utc') or 'sin historial'}", flush=True)
    print(f"Leyendo novedades desde: {cutoff.isoformat()}", flush=True)
    print(f"Registros existentes: {len(existing)}", flush=True)

    def progress(source, pages, diag, oldest):
        oldest_txt = oldest.isoformat() if oldest else "?"
        print(
            f"[{source}] ficheros={pages} expedientes={diag.expedientes_revisados} "
            f"cv_locales={diag.cv_locales} tematicos={diag.tematicos} oldest={oldest_txt}",
            flush=True,
        )

    fresh, errors, diag, by_source = load_incremental_since(
        cutoff,
        progress=progress,
        max_pages_per_source=MAX_PAGES,
    )

    # Seguridad: si una fuente falla o no se completa el intervalo, NO avanzamos el cursor ni sustituimos datos.
    if errors:
        print("La actualización no se considera completa; se conservan intactos los datos anteriores.", file=sys.stderr)
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 2

    finished = utcnow()
    merged = merge_incremental(existing, fresh, retention_days=RETENTION_DAYS, now=finished)

    metadata = {
        "updated_at_utc": finished.isoformat(),
        "last_successful_sync_utc": finished.isoformat(),
        "incremental_from_utc": cutoff.isoformat(),
        "mode": mode,
        "retention_days": RETENTION_DAYS,
        "opportunities": int(len(merged)),
        "new_or_updated_in_run": int(len(fresh)),
        "duration_seconds": int((finished - started).total_seconds()),
        "diagnostics": {
            "atom_pages": int(diag.paginas),
            "reviewed": int(diag.expedientes_revisados),
            "within_period": int(diag.dentro_periodo),
            "cv_local": int(diag.cv_locales),
            "thematic": int(diag.tematicos),
        },
        "by_source": by_source,
        "errors": [],
    }

    atomic_write_csv(merged, CSV_PATH)
    atomic_write_json(metadata, META_PATH)

    print(json.dumps(metadata, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
