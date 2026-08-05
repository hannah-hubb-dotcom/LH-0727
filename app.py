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
STATION_DATA_PATH = Path(__file__).parent / "fire_station_locations.xlsx"
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


@st.cache_data
def load_station_data(path: str):
    """Read EPSG:5186 facility coordinates and convert them to lon/lat."""
    import pyproj

    stations = pd.read_excel(path, sheet_name=0)
    required_columns = {"서ㆍ센터명", "유형구분명", "X좌표", "Y좌표"}
    missing_columns = required_columns - set(stations.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"엑셀에 필요한 컬럼이 없습니다: {missing}")

    stations = stations.copy()
    stations["X좌표"] = pd.to_numeric(stations["X좌표"], errors="coerce")
    stations["Y좌표"] = pd.to_numeric(stations["Y좌표"], errors="coerce")
    stations = stations.dropna(subset=["X좌표", "Y좌표"])

    transformer = pyproj.Transformer.from_crs(
        "EPSG:5186", "EPSG:4326", always_xy=True
    )
    stations["경도"], stations["위도"] = transformer.transform(
        stations["X좌표"].to_numpy(), stations["Y좌표"].to_numpy()
    )
    stations["표시구분"] = stations["유형구분명"].where(
        stations["유형구분명"].eq("소방서"), "안전센터/구조대"
    )
    return stations


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


st.divider()
st.subheader("서울시 소방서·안전센터·구조대 위치")
st.caption("엑셀의 EPSG:5186 좌표를 경위도 좌표로 변환하여 표시했습니다.")

if not STATION_DATA_PATH.exists():
    st.error(
        f"시설 위치 데이터 파일을 찾을 수 없습니다: {STATION_DATA_PATH.name}"
    )
    st.stop()

try:
    stations = load_station_data(str(STATION_DATA_PATH))
except Exception as error:
    st.error("시설 위치 데이터를 불러오는 중 오류가 발생했습니다.")
    st.exception(error)
    st.stop()

station_fig = px.scatter_mapbox(
    stations,
    lat="위도",
    lon="경도",
    color="표시구분",
    color_discrete_map={
        "소방서": "#e53935",
        "안전센터/구조대": "#111111",
    },
    hover_name="서ㆍ센터명",
    hover_data={
        "표시구분": True,
        "유형구분명": True,
        "위도": ":.6f",
        "경도": ":.6f",
    },
    labels={
        "표시구분": "시설 구분",
        "유형구분명": "원본 구분",
        "위도": "위도",
        "경도": "경도",
    },
    size_max=13,
    zoom=10.8,
    center=SEOUL_CITY_HALL,
    mapbox_style="open-street-map",
)

station_fig.update_traces(marker={"size": 9, "opacity": 0.9})
station_fig.update_layout(
    height=650,
    margin={"r": 0, "t": 0, "l": 0, "b": 0},
    legend={"title": "시설 구분"},
    font={"family": "Arial, sans-serif"},
)

st.plotly_chart(
    station_fig,
    use_container_width=True,
    config={"scrollZoom": True},
)
