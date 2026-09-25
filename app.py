from __future__ import annotations

from datetime import date
import re
import pandas as pd
import streamlit as st

from config import CATEGORIES
from radar import load_month, parse_zip_bytes, to_dataframe

st.set_page_config(page_title="Radar de Licitaciones CV", page_icon="🛰️", layout="wide")
st.title("🛰️ Radar de Licitaciones · Comunitat Valenciana")
st.caption("Planificación urbana y territorial · movilidad · turismo · infraestructura verde · clima · paisaje · accesibilidad · Smart City · desarrollo local")

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def cached_month(year: int, month: int):
    # Caches the already-filtered result, not the huge national ZIP files.
    return load_month(year, month)


with st.sidebar:
    st.header("1. Cargar datos")
    mode = st.radio("Fuente", ["Descarga oficial mensual", "Subir ZIP oficial"], index=0)

    if mode == "Descarga oficial mensual":
        today = date.today()
        year = st.number_input("Año", min_value=2016, max_value=today.year, value=today.year, step=1)
        month = st.number_input("Mes", min_value=1, max_value=12, value=today.month, step=1)
        if st.button("Descargar y analizar", type="primary", use_container_width=True):
            status = st.status("Preparando datos oficiales…", expanded=True)
            try:
                # The first run can still take a few minutes because PLACSP publishes national files.
                # Subsequent runs of the same month are much faster thanks to Streamlit cache.
                df, errors = cached_month(int(year), int(month))
                st.session_state.df = df
                status.update(label=f"Listo: {len(df)} oportunidades detectadas", state="complete", expanded=False)
                if errors:
                    st.warning("Alguna fuente no pudo descargarse:\n\n" + "\n\n".join(errors))
            except Exception as exc:
                status.update(label="No se pudo completar la carga", state="error", expanded=True)
                st.error(f"Error: {exc}")
    else:
        files = st.file_uploader("ZIP(s) descargados de PLACSP", type=["zip"], accept_multiple_files=True)
        if st.button("Analizar ZIP", type="primary", use_container_width=True, disabled=not files):
            all_tenders = []
            with st.spinner("Analizando y filtrando…"):
                for f in files or []:
                    all_tenders.extend(parse_zip_bytes(f.getvalue(), f.name))
            st.session_state.df = to_dataframe(all_tenders)

    st.divider()
    st.header("2. Filtros")
    min_score = st.slider("Relevancia mínima", 0, 100, 35, 5)
    selected_provinces = st.multiselect(
        "Provincia",
        ["Alicante", "Castellón", "Valencia", "Sin determinar"],
        default=["Alicante", "Castellón", "Valencia", "Sin determinar"],
    )
    selected_categories = st.multiselect("Familias", list(CATEGORIES.keys()), default=list(CATEGORIES.keys()))
    search = st.text_input("Buscar texto", placeholder="Ej. PMUS, agenda urbana, DTI…")


df = st.session_state.df.copy()

if df.empty:
    st.info("Pulsa ‘Descargar y analizar’. La primera carga del mes puede tardar porque PLACSP distribuye ficheros nacionales; después el resultado queda en caché y las siguientes consultas son mucho más rápidas.")
    st.stop()

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

c1, c2, c3 = st.columns(3)
c1.metric("Licitaciones detectadas", len(filtered))
c2.metric("Alta relevancia (≥70)", int((filtered["relevancia"] >= 70).sum()))
c3.metric("Organismos", filtered["organo"].nunique())

st.subheader("Oportunidades")
view_cols = ["relevancia", "titulo", "organo", "provincia", "categorias", "fecha_limite", "presupuesto", "cpv", "coincidencias", "enlace"]
view = filtered.sort_values(["relevancia", "fecha_actualizacion"], ascending=[False, False])[view_cols]
st.dataframe(
    view,
    use_container_width=True,
    hide_index=True,
    column_config={
        "relevancia": st.column_config.ProgressColumn("Relevancia", min_value=0, max_value=100, format="%d"),
        "enlace": st.column_config.LinkColumn("Enlace"),
    },
)

st.download_button(
    "⬇️ Exportar resultados a CSV",
    filtered.to_csv(index=False).encode("utf-8-sig"),
    file_name="radar_licitaciones_cv.csv",
    mime="text/csv",
)

st.divider()
st.caption("La puntuación es un filtro de relevancia temática. Revisa siempre la ficha y los pliegos oficiales antes de decidir si una licitación encaja.")
