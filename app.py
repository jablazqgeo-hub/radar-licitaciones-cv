from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from config import CATEGORIES

DATA_DIR = Path("data")
CSV_PATH = DATA_DIR / "licitaciones.csv"
META_PATH = DATA_DIR / "metadata.json"

st.set_page_config(page_title="Radar de Licitaciones CV", page_icon="🛰️", layout="wide")
st.title("🛰️ Radar de Licitaciones · Comunitat Valenciana")
st.caption("Planificación urbana y territorial · movilidad · turismo · infraestructura verde · clima · paisaje · accesibilidad · Smart City · desarrollo local")


def load_meta():
    if not META_PATH.exists():
        return None
    try:
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_data():
    if not CSV_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(CSV_PATH, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


meta = load_meta()
df = load_data()

with st.sidebar:
    st.header("Estado del radar")
    if meta:
        raw = meta.get("updated_at_utc", "")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            updated_label = dt.strftime("%d/%m/%Y %H:%M UTC")
        except Exception:
            updated_label = raw or "No disponible"
        st.success(f"Datos actualizados: {updated_label}")
        st.caption(f"Ventana analizada: últimos {meta.get('days', 30)} días")
        if meta.get("errors"):
            st.warning("La última actualización tuvo avisos en alguna fuente oficial.")
    else:
        st.warning("Aún no hay una actualización automática guardada.")
        st.caption("Ejecuta una vez el workflow «Actualizar Radar de Licitaciones» en GitHub Actions.")

    st.divider()
    st.header("Filtros")
    min_score = st.slider("Relevancia mínima", 0, 100, 25, 5)
    selected_provinces = st.multiselect(
        "Provincia",
        ["Alicante", "Castellón", "Valencia", "Sin determinar"],
        default=["Alicante", "Castellón", "Valencia", "Sin determinar"],
    )
    selected_categories = st.multiselect(
        "Familias", list(CATEGORIES.keys()), default=list(CATEGORIES.keys())
    )
    search = st.text_input("Buscar texto", placeholder="Ej. PMUS, Agenda Urbana, DTI…")

if meta:
    diag = meta.get("diagnostics", {})
    st.subheader("Última actualización automática")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("ATOM revisados", f"{diag.get('atom_pages', 0):,}")
    c2.metric("Expedientes", f"{diag.get('reviewed', 0):,}")
    c3.metric("En periodo", f"{diag.get('within_period', 0):,}")
    c4.metric("CV / entidades locales", f"{diag.get('cv_local', 0):,}")
    c5.metric("Temáticamente válidos", f"{diag.get('thematic', 0):,}")

if df.empty:
    if meta and meta.get("opportunities", 0) == 0:
        st.info("La última actualización terminó correctamente, pero no encontró oportunidades que superasen los filtros geográfico y temático.")
    else:
        st.info("Todavía no hay datos precalculados. Ejecuta la actualización desde GitHub Actions y espera a que termine.")
    st.stop()

# Asegurar tipos esperados.
for col in ["titulo", "organo", "provincia", "categorias", "coincidencias", "texto", "enlace", "fecha_actualizacion", "fecha_limite", "presupuesto", "cpv"]:
    if col not in df.columns:
        df[col] = ""
    df[col] = df[col].fillna("").astype(str)
if "relevancia" not in df.columns:
    df["relevancia"] = 0
df["relevancia"] = pd.to_numeric(df["relevancia"], errors="coerce").fillna(0).astype(int)

filtered = df[df["relevancia"] >= min_score].copy()
if selected_provinces:
    filtered = filtered[filtered["provincia"].isin(selected_provinces)]
if selected_categories:
    pattern = "|".join(re.escape(x) for x in selected_categories)
    filtered = filtered[filtered["categorias"].str.contains(pattern, case=False, regex=True, na=False)]
if search.strip():
    q = search.strip()
    mask = pd.Series(False, index=filtered.index)
    for col in ["titulo", "organo", "categorias", "coincidencias", "texto"]:
        mask |= filtered[col].str.contains(q, case=False, regex=False, na=False)
    filtered = filtered[mask]

st.subheader("Oportunidades detectadas")
m1, m2, m3 = st.columns(3)
m1.metric("Oportunidades visibles", len(filtered))
m2.metric("Alta relevancia (≥70)", int((filtered["relevancia"] >= 70).sum()))
m3.metric("Organismos", filtered.loc[filtered["organo"] != "Sin identificar", "organo"].nunique())

if filtered.empty:
    st.warning("Hay datos en el radar, pero ninguna oportunidad coincide con los filtros actuales. Prueba a bajar la relevancia mínima o ampliar familias/provincias.")
else:
    cols = ["relevancia", "titulo", "organo", "provincia", "categorias", "fecha_actualizacion", "fecha_limite", "presupuesto", "cpv", "coincidencias", "enlace"]
    view = filtered.sort_values(["relevancia", "fecha_actualizacion"], ascending=[False, False])[cols]
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "relevancia": st.column_config.ProgressColumn("Relevancia", min_value=0, max_value=100, format="%d"),
            "titulo": st.column_config.TextColumn("Licitación", width="large"),
            "organo": st.column_config.TextColumn("Órgano", width="medium"),
            "categorias": st.column_config.TextColumn("Familia", width="medium"),
            "enlace": st.column_config.LinkColumn("Enlace oficial"),
        },
    )
    st.download_button(
        "⬇️ Exportar CSV",
        filtered.to_csv(index=False).encode("utf-8-sig"),
        "radar_licitaciones_cv.csv",
        "text/csv",
    )

st.caption("Fuente: sindicación ATOM oficial de PLACSP. La actualización pesada se ejecuta en GitHub Actions; Streamlit solo muestra los resultados precalculados.")
