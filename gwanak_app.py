import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(
    page_title="관악구 생활권 녹지 접근성",
    page_icon="🌳",
    layout="wide",
)

DATA_DIR = Path(__file__).parent / "data"
ACCESSIBILITY_PATH = DATA_DIR / "gwanak_residential_grid_accessibility_v2.geojson"


@st.cache_data
def load_accessibility(path):
    with open(path, encoding="utf-8") as file:
        geojson = json.load(file)

    rows = []

    for feature in geojson["features"]:
        properties = feature["properties"]
        coordinates = feature["geometry"]["coordinates"]

        rows.append({
            **properties,
            "longitude": coordinates[0],
            "latitude": coordinates[1],
        })

    return pd.DataFrame(rows)


st.title("관악구 주민은 집에서 10분 안에 몇 개의 공원에 갈 수 있을까?")
st.caption("보행 네트워크 기반 생활권 녹지 접근성 분석")

if not ACCESSIBILITY_PATH.exists():
    st.error(
        "데이터 파일을 찾을 수 없습니다: "
        "data/gwanak_grid_accessibility.geojson"
    )
    st.stop()

accessibility = load_accessibility(ACCESSIBILITY_PATH)

threshold = st.selectbox(
    "도보시간 기준",
    options=[5, 10, 15],
    index=1,
)

count_column = f"parks_within_{threshold}min"

if count_column not in accessibility.columns:
    st.error(f"{count_column} 컬럼이 없습니다.")
    st.stop()

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("분석 지점 수", f"{len(accessibility):,}개")

with col2:
    st.metric(
        f"{threshold}분 이내 공원 평균",
        f"{accessibility[count_column].mean():.1f}개",
    )

with col3:
    st.metric(
        f"{threshold}분 이내 공원 최댓값",
        f"{accessibility[count_column].max():.0f}개",
    )

fig = px.scatter_mapbox(
    accessibility,
    lat="latitude",
    lon="longitude",
    color=count_column,
    color_continuous_scale=[
        [0.0, "#d73027"],
        [0.25, "#fc8d59"],
        [0.5, "#fee08b"],
        [0.75, "#91cf60"],
        [1.0, "#1a9850"],
    ],
    hover_data={
        "grid_id": True,
        count_column: True,
        "nearest_distance_m": ":.1f",
        "latitude": False,
        "longitude": False,
    },
    labels={
        "grid_id": "격자 ID",
        count_column: f"{threshold}분 이내 공원 수",
        "nearest_distance_m": "가장 가까운 공원 거리(m)",
    },
    center={
        "lat": 37.478,
        "lon": 126.951,
    },
    zoom=12.5,
    mapbox_style="open-street-map",
)

fig.update_traces(marker={"size": 10, "opacity": 0.85})

fig.update_layout(
    height=700,
    margin={"r": 0, "t": 0, "l": 0, "b": 0},
    coloraxis_colorbar={
        "title": f"{threshold}분 이내<br>공원 수",
    },
)

st.plotly_chart(
    fig,
    use_container_width=True,
    config={"scrollZoom": True},
)

st.subheader("접근성이 낮은 지역")

bottom = accessibility.sort_values(
    by=count_column,
    ascending=True,
).head(10)

st.dataframe(
    bottom[
        [
            "grid_id",
            count_column,
            "nearest_distance_m",
        ]
    ],
    use_container_width=True,
)
