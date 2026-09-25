from __future__ import annotations
import re
import pandas as pd
import streamlit as st
from config import CATEGORIES
from radar import load_recent

st.set_page_config(page_title="Radar de Licitaciones CV", page_icon="🛰️", layout="wide")
st.title("🛰️ Radar de Licitaciones · Comunitat Valenciana")
st.caption("Planificación urbana y territorial · movilidad · turismo · infraestructura verde · clima · paisaje · accesibilidad · Smart City · desarrollo local")

if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()

@st.cache_data(ttl=60*60, show_spinner=False)
def cached_recent(days: int):
    return load_recent(days)

with st.sidebar:
    st.header("1. Actualizar radar")
    days = st.selectbox("Buscar actualizaciones de los últimos", [7, 14, 30, 60, 90], index=2, format_func=lambda x: f"{x} días")
    if st.button("Actualizar ahora", type="primary", use_container_width=True):
        status = st.status("Consultando los feeds diarios oficiales de PLACSP…", expanded=True)
        try:
            df, errors = cached_recent(int(days))
            st.session_state.df = df
            status.update(label=f"Listo: {len(df)} oportunidades detectadas", state="complete", expanded=False)
            if errors:
                st.warning("Alguna fuente oficial no respondió correctamente:\n\n" + "\n\n".join(errors))
        except Exception as exc:
            status.update(label="No se pudo completar la actualización", state="error", expanded=True)
            st.error(str(exc))

    st.divider()
    st.header("2. Filtros")
    min_score = st.slider("Relevancia mínima", 0, 100, 35, 5)
    selected_provinces = st.multiselect("Provincia", ["Alicante", "Castellón", "Valencia", "Sin determinar"], default=["Alicante", "Castellón", "Valencia", "Sin determinar"])
    selected_categories = st.multiselect("Familias", list(CATEGORIES.keys()), default=list(CATEGORIES.keys()))
    search = st.text_input("Buscar texto", placeholder="Ej. PMUS, Agenda Urbana, DTI…")

df = st.session_state.df.copy()
if df.empty:
    st.info("Pulsa «Actualizar ahora». Esta versión consulta los feeds ATOM diarios oficiales, en lugar de descargar los ZIP mensuales nacionales.")
    st.stop()

filtered = df[df["relevancia"] >= min_score].copy()
if selected_provinces: filtered = filtered[filtered["provincia"].isin(selected_provinces)]
if selected_categories:
    pattern = "|".join(re.escape(x) for x in selected_categories)
    filtered = filtered[filtered["categorias"].str.contains(pattern, case=False, regex=True, na=False)]
if search.strip():
    q = search.strip()
    mask = pd.Series(False, index=filtered.index)
    for col in ["titulo", "organo", "categorias", "coincidencias", "texto"]:
        mask |= filtered[col].str.contains(q, case=False, regex=False, na=False)
    filtered = filtered[mask]

c1,c2,c3 = st.columns(3)
c1.metric("Oportunidades", len(filtered))
c2.metric("Alta relevancia (≥70)", int((filtered["relevancia"] >= 70).sum()))
c3.metric("Organismos", filtered["organo"].nunique())

st.subheader("Oportunidades detectadas")
cols = ["relevancia","titulo","organo","provincia","categorias","fecha_actualizacion","fecha_limite","presupuesto","cpv","coincidencias","enlace"]
view = filtered.sort_values(["relevancia","fecha_actualizacion"], ascending=[False,False])[cols]
st.dataframe(view, use_container_width=True, hide_index=True, column_config={
    "relevancia": st.column_config.ProgressColumn("Relevancia", min_value=0, max_value=100, format="%d"),
    "enlace": st.column_config.LinkColumn("Enlace oficial"),
})
st.download_button("⬇️ Exportar CSV", filtered.to_csv(index=False).encode("utf-8-sig"), "radar_licitaciones_cv.csv", "text/csv")
st.caption("Fuente: feeds ATOM oficiales de PLACSP. La puntuación indica afinidad temática; revisa siempre los pliegos oficiales.")
