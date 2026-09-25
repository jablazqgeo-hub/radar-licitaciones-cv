from __future__ import annotations
import re
import pandas as pd
import streamlit as st
from config import CATEGORIES
from radar import load_recent, Diagnostics

st.set_page_config(page_title="Radar de Licitaciones CV", page_icon="🛰️", layout="wide")
st.title("🛰️ Radar de Licitaciones · Comunitat Valenciana")
st.caption("Planificación urbana y territorial · movilidad · turismo · infraestructura verde · clima · paisaje · accesibilidad · Smart City · desarrollo local")

for key, default in {
    "df": pd.DataFrame(),
    "diag": None,
    "by_source": {},
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    st.header("1. Actualizar radar")
    days = st.selectbox("Buscar actualizaciones de los últimos", [7, 14, 30, 60, 90], index=2, format_func=lambda x: f"{x} días")
    if st.button("Actualizar ahora", type="primary", use_container_width=True):
        progress_bar = st.progress(0, text="Conectando con PLACSP…")
        progress_slot = st.empty()
        source_seen = {}

        def on_progress(source, pages, diag, oldest):
            source_seen[source] = pages
            total_pages = sum(source_seen.values())
            oldest_txt = oldest.strftime("%d/%m/%Y") if oldest else "fecha no disponible"
            progress_slot.caption(f"{source}: {pages} ficheros · {diag.expedientes_revisados:,} expedientes · fecha más antigua {oldest_txt}")
            # Progress is deliberately approximate because the number of files is not known in advance.
            progress_bar.progress(min(95, 5 + total_pages * 2), text=f"Revisando histórico oficial… {total_pages} ficheros ATOM")

        try:
            df, errors, diag, by_source = load_recent(days, progress=on_progress)
            st.session_state.df = df
            st.session_state.diag = diag
            st.session_state.by_source = by_source
            progress_bar.progress(100, text="Actualización completada")
            progress_slot.empty()
            st.success(f"Listo: {len(df)} oportunidades detectadas tras revisar {diag.paginas} ficheros ATOM.")
            if errors:
                st.warning("Alguna fuente oficial no respondió correctamente:\n\n" + "\n\n".join(errors))
        except Exception as exc:
            progress_bar.empty()
            st.error(f"No se pudo completar la actualización: {exc}")

    st.divider()
    st.header("2. Filtros")
    min_score = st.slider("Relevancia mínima", 0, 100, 25, 5)
    selected_provinces = st.multiselect("Provincia", ["Alicante", "Castellón", "Valencia", "Sin determinar"], default=["Alicante", "Castellón", "Valencia", "Sin determinar"])
    selected_categories = st.multiselect("Familias", list(CATEGORIES.keys()), default=list(CATEGORIES.keys()))
    search = st.text_input("Buscar texto", placeholder="Ej. PMUS, Agenda Urbana, DTI…")


df = st.session_state.df.copy()
diag = st.session_state.diag

if diag is None:
    st.info("Pulsa «Actualizar ahora». Esta versión sigue el enlace ATOM `next`, que PLACSP utiliza para encadenar las actualizaciones anteriores, hasta cubrir el periodo elegido.")
    st.stop()

st.subheader("Control de la búsqueda")
d1, d2, d3, d4, d5 = st.columns(5)
d1.metric("ATOM revisados", diag.paginas)
d2.metric("Expedientes revisados", f"{diag.expedientes_revisados:,}")
d3.metric("Dentro del periodo", f"{diag.dentro_periodo:,}")
d4.metric("Entidades CV/locales", f"{diag.cv_locales:,}")
d5.metric("Temáticamente válidos", f"{diag.tematicos:,}")

with st.expander("Detalle por fuente oficial"):
    rows = []
    for source, vals in st.session_state.by_source.items():
        rows.append({"Fuente": source, **vals})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

if df.empty:
    st.warning("La descarga y el recorrido histórico han terminado, pero ningún expediente superó los filtros geográfico + temático. Revisa los contadores superiores: permiten distinguir si el problema está en los datos, en el ámbito valenciano o en la clasificación temática.")
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
c1.metric("Oportunidades visibles", len(filtered))
c2.metric("Alta relevancia (≥70)", int((filtered["relevancia"] >= 70).sum()))
c3.metric("Organismos", filtered.loc[filtered["organo"] != "Sin identificar", "organo"].nunique())

st.subheader("Oportunidades detectadas")
cols = ["relevancia", "titulo", "organo", "provincia", "categorias", "fecha_actualizacion", "fecha_limite", "presupuesto", "cpv", "coincidencias", "enlace"]
view = filtered.sort_values(["relevancia", "fecha_actualizacion"], ascending=[False, False])[cols]
st.dataframe(view, use_container_width=True, hide_index=True, column_config={
    "relevancia": st.column_config.ProgressColumn("Relevancia", min_value=0, max_value=100, format="%d"),
    "titulo": st.column_config.TextColumn("Licitación", width="large"),
    "organo": st.column_config.TextColumn("Órgano", width="medium"),
    "categorias": st.column_config.TextColumn("Familia", width="medium"),
    "enlace": st.column_config.LinkColumn("Enlace oficial"),
})
st.download_button("⬇️ Exportar CSV", filtered.to_csv(index=False).encode("utf-8-sig"), "radar_licitaciones_cv.csv", "text/csv")
st.caption("Fuente: sindicación ATOM oficial de PLACSP. La puntuación indica afinidad temática; revisa siempre los pliegos oficiales.")
