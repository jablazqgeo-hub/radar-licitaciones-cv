from __future__ import annotations

from datetime import date
import pandas as pd
import streamlit as st

from config import CATEGORIES
from radar import download_zip, month_urls, parse_zip_bytes, to_dataframe

st.set_page_config(page_title="Radar de Licitaciones CV", page_icon="🛰️", layout="wide")
st.title("🛰️ Radar de Licitaciones · Comunitat Valenciana")
st.caption("Planificación urbana y territorial · movilidad · turismo · infraestructura verde · clima · paisaje · accesibilidad · Smart City · desarrollo local")

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()

with st.sidebar:
    st.header("1. Cargar datos")
    mode = st.radio("Fuente", ["Descarga oficial mensual", "Subir ZIP oficial"], index=0)

    if mode == "Descarga oficial mensual":
        today = date.today()
        year = st.number_input("Año", min_value=2016, max_value=today.year, value=today.year, step=1)
        month = st.number_input("Mes", min_value=1, max_value=12, value=today.month, step=1)
        if st.button("Descargar y analizar", type="primary", use_container_width=True):
            all_tenders = []
            errors = []
            with st.spinner("Descargando y clasificando licitaciones…"):
                for source, url in month_urls(int(year), int(month)).items():
                    try:
                        data = download_zip(url)
                        all_tenders.extend(parse_zip_bytes(data, source))
                    except Exception as e:
                        errors.append(f"{source}: {e}")
            st.session_state.df = to_dataframe(all_tenders)
            if errors:
                st.warning("Alguna fuente no pudo descargarse:\n\n" + "\n\n".join(errors))
    else:
        files = st.file_uploader("ZIP(s) descargados de PLACSP", type=["zip"], accept_multiple_files=True)
        if st.button("Analizar ZIP", type="primary", use_container_width=True, disabled=not files):
            all_tenders = []
            with st.spinner("Analizando…"):
                for f in files or []:
                    all_tenders.extend(parse_zip_bytes(f.getvalue(), f.name))
            st.session_state.df = to_dataframe(all_tenders)

    st.divider()
    st.header("2. Filtros")
    min_score = st.slider("Relevancia mínima", 0, 100, 35, 5)
    selected_provinces = st.multiselect("Provincia", ["Alicante", "Castellón", "Valencia", "Sin determinar"], default=["Alicante", "Castellón", "Valencia", "Sin determinar"])
    selected_categories = st.multiselect("Familias", list(CATEGORIES.keys()), default=list(CATEGORIES.keys()))
    search = st.text_input("Buscar texto", placeholder="Ej. PMUS, agenda urbana, DTI…")


df = st.session_state.df.copy()

if df.empty:
    st.info("Carga un mes de datos oficiales de PLACSP desde la barra lateral. También puedes subir ZIP oficiales manualmente.")
    st.markdown("**Consejo:** empieza por el mes actual. La plataforma oficial indica que el fichero del mes en curso contiene las actualizaciones hasta el día anterior.")
    st.stop()

filtered = df[df["relevancia"] >= min_score].copy()
if selected_provinces:
    filtered = filtered[filtered["provincia"].isin(selected_provinces)]
if selected_categories:
    pattern = "|".join(selected_categories)
    filtered = filtered[filtered["categorias"].str.contains(pattern, case=False, regex=True, na=False)]
if search.strip():
    q = search.strip()
    filtered = filtered[
        filtered["titulo"].str.contains(q, case=False, regex=False, na=False)
        | filtered["organo"].str.contains(q, case=False, regex=False, na=False)
        | filtered["categorias"].str.contains(q, case=False, regex=False, na=False)
        | filtered["coincidencias"].str.contains(q, case=False, regex=False, na=False)
        | filtered["texto"].str.contains(q, case=False, regex=False, na=False)
    ]

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
st.caption("La puntuación es un filtro de relevancia temática, no una valoración jurídica ni una garantía de elegibilidad. Conviene revisar siempre los pliegos y la ficha oficial antes de decidir si presentar oferta.")
