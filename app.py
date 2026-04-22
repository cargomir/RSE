from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Radiografía Sistema Eléctrico - PSUF 2025",
    layout="wide",
    initial_sidebar_state="expanded",
)

WORKBOOK_NAME = "PSuficiencia_def25_v1.xlsx"
APP_DIR = Path(__file__).resolve().parent
WORKBOOK_PATH = APP_DIR / "data" / WORKBOOK_NAME
REQUIRED_SHEETS = ["Cambios Oferta", "Factores", "Resultados", "Psuf S1", "Psuf S2"]

DISPLAY_NAMES = {
    "Potencia id": "ID potencia",
    "Nombre empresa": "Empresa",
    "Nombre unidad generadora": "Central",
    "Tipo tecnologia": "Tecnología",
    "Subsistema": "Subsistema",
    "Combustible nombre": "Combustible",
    "Potencia [MW]": "Potencia [MW]",
    "Pmax [MW]": "Capacidad máxima [MW]",
    "Pini [MW]": "Potencia inicial [MW]",
    "Peq [MW]": "Potencia equivalente [MW]",
    "Fmm [pu]": "Factor de mantenimiento [pu]",
    "Ifor [pu]": "Indisponibilidad forzada [pu]",
    "CCPP [pu]": "Consumos propios [pu]",
    "psuf_pre": "Potencia preliminar [MW]",
    "psuf_def": "Potencia definitiva [MW]",
    "Merma MW": "Merma [MW]",
    "Merma %": "Merma [%]",
    "Ratio reconocimiento": "Ratio reconocimiento [%]",
    "ratio": "Ratio reconocimiento [%]",
    "Psuf promedio subperiodos": "Potencia promedio subperiodos [MW]",
    "Variabilidad subperiodos": "Variabilidad subperiodos [MW]",
    "Psuf min subperiodo": "Potencia mínima subperiodo [MW]",
    "Psuf max subperiodo": "Potencia máxima subperiodo [MW]",
    "N subperiodos": "Número de subperiodos",
    "Fecha cambio": "Fecha de cambio",
    "Causa": "Causa",
    "Subperiodo": "Subperiodo",
    "psuf_subperiodo": "Potencia por subperiodo [MW]",
    "Subsistema tabla": "Subsistema"
}

def rename_for_display(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={c: DISPLAY_NAMES.get(c, c) for c in df.columns})

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def fmt_mw(x: float) -> str:
    if pd.isna(x):
        return "-"
    return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")

def fmt_pct_series(s: pd.Series) -> pd.Series:
    return (s * 100).round(1).astype(str).str.replace(".", ",", regex=False) + "%"


@st.cache_data(show_spinner=False)
def read_workbook(workbook_path: Path):
    if not workbook_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo {workbook_path.name} en: {workbook_path.parent}"
        )

    excel = pd.ExcelFile(workbook_path)
    missing = [s for s in REQUIRED_SHEETS if s not in excel.sheet_names]
    if missing:
        raise ValueError(
            f"El archivo debe incluir estas hojas: {', '.join(REQUIRED_SHEETS)}. "
            f"Faltan: {', '.join(missing)}"
        )

    data = {}
    for sheet in REQUIRED_SHEETS:
        data[sheet] = normalize_columns(pd.read_excel(workbook_path, sheet_name=sheet))
    return data


def reshape_psuf(df: pd.DataFrame, subsistema_tabla: str) -> pd.DataFrame:
    df = df.copy()
    id_vars = [c for c in ["Potencia id", "Nombre unidad generadora", "Psuf_pre", "Psuf_def"] if c in df.columns]
    period_cols = [c for c in df.columns if str(c).strip().isdigit()]

    long_df = df.melt(
        id_vars=id_vars,
        value_vars=period_cols,
        var_name="Subperiodo",
        value_name="psuf_subperiodo",
    )
    long_df["Subperiodo"] = pd.to_numeric(long_df["Subperiodo"], errors="coerce")
    long_df["psuf_subperiodo"] = pd.to_numeric(long_df["psuf_subperiodo"], errors="coerce")
    long_df["Subsistema tabla"] = subsistema_tabla
    return long_df


@st.cache_data(show_spinner=False)
def build_master_tables(data: dict[str, pd.DataFrame]):
    cambios = data["Cambios Oferta"].copy()
    factores = data["Factores"].copy()
    resultados = data["Resultados"].copy()
    psuf_s1 = data["Psuf S1"].copy()
    psuf_s2 = data["Psuf S2"].copy()

    cambios = coerce_numeric(cambios, ["Potencia [MW]"])
    if "Fecha cambio" in cambios.columns:
        cambios["Fecha cambio"] = pd.to_datetime(cambios["Fecha cambio"], errors="coerce")

    factores = coerce_numeric(
        factores,
        ["Pmax [MW]", "Pini [MW]", "Peq [MW]", "Fmm [pu]", "Ifor [pu]", "CCPP [pu]"],
    )
    resultados = coerce_numeric(resultados, ["psuf_pre", "psuf_def"])

    cambios_dedup = cambios[[
        c for c in [
            "Potencia id",
            "Nombre empresa",
            "Nombre unidad generadora",
            "Combustible nombre",
            "Subsistema",
        ] if c in cambios.columns
    ]].drop_duplicates(subset=["Potencia id"], keep="last")

    keys = [
        c for c in [
            "Potencia id",
            "Nombre empresa",
            "Nombre unidad generadora",
            "Tipo tecnologia",
            "Subsistema",
        ] if c in factores.columns and c in resultados.columns
    ]

    master = (
        factores
        .merge(resultados, on=keys, how="outer")
        .merge(cambios_dedup, on="Potencia id", how="left", suffixes=("", "_cambio"))
    )

    for base_col in ["Nombre empresa", "Nombre unidad generadora", "Subsistema"]:
        extra_col = f"{base_col}_cambio"
        if base_col in master.columns and extra_col in master.columns:
            master[base_col] = master[base_col].fillna(master[extra_col])

    if "Pmax [MW]" in master.columns and "psuf_def" in master.columns:
        master["Merma MW"] = master["Pmax [MW]"] - master["psuf_def"]
        master["Ratio reconocimiento"] = np.where(
            master["Pmax [MW]"] > 0,
            master["psuf_def"] / master["Pmax [MW]"],
            np.nan,
        )
        master["Merma %"] = np.where(
            master["Pmax [MW]"] > 0,
            (master["Pmax [MW]"] - master["psuf_def"]) / master["Pmax [MW]"],
            np.nan,
        )

    psuf_long = pd.concat(
        [reshape_psuf(psuf_s1, "S1"), reshape_psuf(psuf_s2, "S2")],
        ignore_index=True,
    )

    variability = (
        psuf_long.groupby("Potencia id", dropna=False)["psuf_subperiodo"]
        .agg(["mean", "std", "min", "max", "count"])
        .reset_index()
        .rename(columns={
            "mean": "Psuf promedio subperiodos",
            "std": "Variabilidad subperiodos",
            "min": "Psuf min subperiodo",
            "max": "Psuf max subperiodo",
            "count": "N subperiodos",
        })
    )

    master = master.merge(variability, on="Potencia id", how="left")
    return master, cambios, psuf_long


st.title("⚡Radiografía Sistema Eléctrico")

st.sidebar.title("⚡Radiografía Sistema")
st.sidebar.markdown("**Período:** 2025")
st.sidebar.markdown("**Origen:** Base oficial PSUF")

st.sidebar.markdown("---")

try:
    data = read_workbook(WORKBOOK_PATH)
    master, cambios, psuf_long = build_master_tables(data)
except Exception as e:
    st.error(f"No fue posible procesar el archivo: {e}")
    st.stop()

with st.sidebar:
    st.markdown("### Filtros")

    tecnologias = sorted(master.get("Tipo tecnologia", pd.Series(dtype=str)).dropna().unique().tolist())
    empresas = sorted(master.get("Nombre empresa", pd.Series(dtype=str)).dropna().unique().tolist())
    subsistemas = sorted(master.get("Subsistema", pd.Series(dtype=str)).dropna().unique().tolist())

    tecnologias_opciones = ["Todas"] + tecnologias
    empresas_opciones = ["Todas"] + empresas
    subsistemas_opciones = ["Todos"] + subsistemas

    filtro_tecnologia = st.selectbox("Tecnología", tecnologias_opciones, index=0)
    filtro_empresa = st.selectbox("Empresa", empresas_opciones, index=0)
    filtro_subsistema = st.selectbox("Subsistema", subsistemas_opciones, index=0)

filtered = master.copy()

if filtro_tecnologia != "Todas":
    filtered = filtered[filtered["Tipo tecnologia"] == filtro_tecnologia]

if filtro_empresa != "Todas":
    filtered = filtered[filtered["Nombre empresa"] == filtro_empresa]

if filtro_subsistema != "Todos":
    filtered = filtered[filtered["Subsistema"] == filtro_subsistema]

psuf_filtered = psuf_long[psuf_long["Potencia id"].isin(filtered["Potencia id"].dropna().unique())].copy()
cambios_filtered = cambios[cambios["Potencia id"].isin(filtered["Potencia id"].dropna().unique())].copy()

total_unidades = filtered["Potencia id"].nunique()
total_empresas = filtered["Nombre empresa"].nunique() if "Nombre empresa" in filtered.columns else 0
pmax_total = filtered["Pmax [MW]"].sum(skipna=True)
pini_total = filtered["Pini [MW]"].sum(skipna=True)
psuf_pre_total = filtered["psuf_pre"].sum(skipna=True)
psuf_def_total = filtered["psuf_def"].sum(skipna=True)
ratio_total = psuf_def_total / pmax_total if pmax_total > 0 else np.nan

st.markdown(
    """
    <style>
    .kpi-card {
        background-color: #f8fafc;
        border: 1px solid #dbe3ea;
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 8px;
        min-height: 95px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        text-align: center;
    }
    .kpi-title {
        font-size: 0.95rem;
        color: #4b5c6b;
        margin-bottom: 6px;
        font-weight: 500;
    }
    .kpi-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0f172a;
        line-height: 1.1;
    }
    </style>
    """,
    unsafe_allow_html=True
)

def kpi_card(title, value):
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-title">{title}</div>
            <div class="kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

fila1 = st.columns(3, gap="small")
fila2 = st.columns(4, gap="small")

with fila1[0]:
    kpi_card("Centrales", f"{total_unidades:,}".replace(",", "."))
with fila1[1]:
    kpi_card("Empresas", f"{total_empresas:,}".replace(",", "."))
with fila1[2]:
    kpi_card("Ratio reconocimiento sistema", f"{ratio_total:.1%}" if pd.notna(ratio_total) else "-")

with fila2[0]:
    kpi_card("Capacidad máxima [MW]", fmt_mw(pmax_total))
with fila2[1]:
    kpi_card("Potencia inicial [MW]", fmt_mw(pini_total))
with fila2[2]:
    kpi_card("Potencia preliminar [MW]", fmt_mw(psuf_pre_total))
with fila2[3]:
    kpi_card("Potencia definitiva [MW]", fmt_mw(psuf_def_total))

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Resumen sistema",
    "Tecnologías",
    "Empresas",
    "Centrales",
    "Subperiodos y cambios",
])

with tab1:
    st.subheader("Resumen del sistema")
    col1, col2 = st.columns(2)

    with col1:
        resumen_sub = (
            filtered.groupby("Subsistema", dropna=False)[["Pmax [MW]", "Pini [MW]", "psuf_pre", "psuf_def"]]
            .sum(numeric_only=True)
            .reset_index()
        )
        fig = px.bar(
            resumen_sub,
            x="Subsistema",
            y=["Pmax [MW]", "psuf_def"],
            barmode="group",
            title="Pmax vs Psuf definitiva por subsistema",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        resumen_tec = (
            filtered.groupby("Tipo tecnologia", dropna=False)["psuf_def"]
            .sum()
            .reset_index()
            .sort_values("psuf_def", ascending=False)
        )
        fig = px.pie(
            resumen_tec,
            names="Tipo tecnologia",
            values="psuf_def",
            title="Participación de Psuf definitiva por tecnología",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Resumen tabular")
    tabla_resumen = (
        filtered.groupby(["Subsistema", "Tipo tecnologia"], dropna=False)[["Pmax [MW]", "Pini [MW]", "psuf_pre", "psuf_def"]]
        .sum(numeric_only=True)
        .reset_index()
    )
    st.dataframe(rename_for_display(tabla_resumen), use_container_width=True)

with tab2:
    st.subheader("Radiografía por tecnología")
    tech = (
    filtered.groupby("Tipo tecnologia", dropna=False)
    .agg(
        unidades=("Potencia id", "nunique"),
        pmax=("Pmax [MW]", "sum"),
        pini=("Pini [MW]", "sum"),
        psuf_pre=("psuf_pre", "sum"),
        psuf_def=("psuf_def", "sum"),
        ifor_prom=("Ifor [pu]", "mean"),
        fmm_prom=("Fmm [pu]", "mean"),
        ratio=("Ratio reconocimiento", "mean"),
    )
    .reset_index()
    .sort_values("psuf_def", ascending=False)
)

    fig = px.bar(
        tech,
        x="Tipo tecnologia",
        y="psuf_def",
        title="Potencia definitiva por tecnología",
        text_auto=".2s"
    )
    st.plotly_chart(fig, use_container_width=True)

    fig = px.scatter(
        tech,
        x="ifor_prom",
        y="ratio",
        size="pmax",
        hover_name="Tipo tecnologia",
        title="Indisponibilidad forzada promedio vs ratio reconocimiento",
    )
    fig.update_yaxes(tickformat=".1%")
    st.plotly_chart(fig, use_container_width=True)

    tech_tabla = tech.copy()
    tech_tabla["ratio"] = fmt_pct_series(tech_tabla["ratio"])
    st.dataframe(rename_for_display(tech_tabla), use_container_width=True)

with tab3:
    st.subheader("Radiografía por empresa")
    emp = (
    filtered.groupby("Nombre empresa", dropna=False)
    .agg(
        unidades=("Potencia id", "nunique"),
        pmax=("Pmax [MW]", "sum"),
        psuf_def=("psuf_def", "sum"),
        merma=("Merma MW", "sum"),
        ratio=("Ratio reconocimiento", "mean"),
    )
    .reset_index()
    .sort_values("psuf_def", ascending=False)
)

    fig = px.bar(
        emp.head(15),
        x="Nombre empresa",
        y="psuf_def",
        title="Top 15 empresas por potencia definitiva",
    )
    st.plotly_chart(fig, use_container_width=True)

    emp_tabla = emp.copy()
    emp_tabla["ratio"] = fmt_pct_series(emp_tabla["ratio"])
    st.dataframe(rename_for_display(emp_tabla), use_container_width=True)

with tab4:
    st.subheader("Radiografía por central")
    vista = filtered[[
        c for c in [
            "Potencia id",
            "Nombre empresa",
            "Nombre unidad generadora",
            "Tipo tecnologia",
            "Subsistema",
            "Pmax [MW]",
            "Pini [MW]",
            "Peq [MW]",
            "Ifor [pu]",
            "Fmm [pu]",
            "CCPP [pu]",
            "psuf_pre",
            "psuf_def",
            "Merma MW",
            "Merma %",
            "Ratio reconocimiento",
            "Variabilidad subperiodos",
        ] if c in filtered.columns
    ]].copy()

    opciones_orden = [
        c for c in [
            "psuf_def",
            "Merma MW",
            "Ratio reconocimiento",
            "Ifor [pu]",
            "Variabilidad subperiodos"
        ] if c in vista.columns
    ]
    orden = st.selectbox("Ordenar por", opciones_orden, index=0)
    asc = st.toggle("Orden ascendente", value=False)
    vista = vista.sort_values(orden, ascending=asc)

    vista_tabla = vista.copy()
    if "Ratio reconocimiento" in vista_tabla.columns:
        vista_tabla["Ratio reconocimiento"] = fmt_pct_series(vista_tabla["Ratio reconocimiento"])
    if "Merma %" in vista_tabla.columns:
        vista_tabla["Merma %"] = fmt_pct_series(vista_tabla["Merma %"])

    st.dataframe(rename_for_display(vista_tabla), use_container_width=True)

with tab5:
    st.subheader("Subperiodos y cambios de oferta")
    col1, col2 = st.columns(2)

    with col1:
        if not psuf_filtered.empty:
            resumen_subp = (
                psuf_filtered.groupby(["Subsistema tabla", "Subperiodo"], dropna=False)["psuf_subperiodo"]
                .sum()
                .reset_index()
            )
            fig = px.line(
                resumen_subp,
                x="Subperiodo",
                y="psuf_subperiodo",
                color="Subsistema tabla",
                markers=True,
                title="Psuf total por subperiodo",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay datos de subperiodos con los filtros actuales.")

    with col2:
        if not cambios_filtered.empty and "Fecha cambio" in cambios_filtered.columns:
            cambios_mes = (
                cambios_filtered.assign(Mes=cambios_filtered["Fecha cambio"].dt.to_period("M").astype(str))
                .groupby("Mes", dropna=False)
                .size()
                .reset_index(name="N cambios")
                .sort_values("Mes")
            )
            fig = px.bar(cambios_mes, x="Mes", y="N cambios", title="Cambios de oferta por mes")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No hay fechas de cambios disponibles para los filtros actuales.")

    st.markdown("### Detalle de cambios de oferta")
    st.dataframe(rename_for_display(cambios_filtered), use_container_width=True)

st.markdown("---")
st.caption(
    "Prototipo diseñado por Carlos Andrés González Miranda"
)
