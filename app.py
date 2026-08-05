from pathlib import Path
import json

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="서울 행정동 출동건수 지도",
    page_icon="🚑",
    layout="wide",
)


DATA_PATH = Path(__file__).parent / "dong_emergency_count.geojson"
SEOUL_CITY_HALL = {"lat": 37.5663, "lon": 126.9779}


@st.cache_data
def load_geojson(path: str):
    with open(path, encoding="utf-8") as file:
        geojson = json.load(file)

    rows = [feature["properties"] for feature in geojson["features"]]
    data = pd.DataFrame(rows)
    data["ADM_CD"] = data["ADM_CD"].astype(str)
    data["emergency_count"] = pd.to_numeric(data["emergency_count"])
    return geojson, data


st.title("서울 행정동별 출동건수")
st.caption("행정동을 마우스로 가리키면 행정동 이름, 코드, 출동건수를 확인할 수 있습니다.")

if not DATA_PATH.exists():
    st.error(f"데이터 파일을 찾을 수 없습니다: {DATA_PATH.name}")
    st.stop()

geojson, all_data = load_geojson(str(DATA_PATH))

show_mokdong_only = st.toggle("목x동만 보기", value=False)

if show_mokdong_only:
    data = all_data[all_data["ADM_NM"].str.startswith("목")].copy()
else:
    data = all_data.copy()

if data.empty:
    st.warning("조건에 맞는 행정동이 없습니다.")
    st.stop()

st.write(
    f"표시 행정동: **{len(data):,}개**  |  "
    f"출동건수: **{data['emergency_count'].sum():,}건**"
)

fig = px.choropleth_mapbox(
    data_frame=data,
    geojson=geojson,
    locations="ADM_CD",
    featureidkey="properties.ADM_CD",
    color="emergency_count",
    color_continuous_scale=[
        [0.0, "#ffffff"],
        [0.25, "#fee2e2"],
        [0.5, "#fca5a5"],
        [0.75, "#ef4444"],
        [1.0, "#b91c1c"],
    ],
    range_color=(0, int(all_data["emergency_count"].max())),
    hover_name="ADM_NM",
    hover_data={
        "ADM_CD": True,
        "emergency_count": ":,d",
    },
    labels={
        "ADM_NM": "행정동",
        "ADM_CD": "행정동 코드",
        "emergency_count": "출동건수",
    },
    mapbox_style="open-street-map",
    center=SEOUL_CITY_HALL,
    zoom=10.8,
    opacity=0.78,
)

fig.update_layout(
    height=720,
    margin={"r": 0, "t": 0, "l": 0, "b": 0},
    coloraxis_colorbar={
        "title": "출동건수",
        "tickformat": ",d",
        "len": 0.65,
    },
    font={"family": "Arial, sans-serif"},
)

st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})

