from pathlib import Path
import json

import geopandas as gpd
import networkx as nx
import pandas as pd
import streamlit as st
import folium

from shapely.geometry import Point
from streamlit_folium import st_folium


st.set_page_config(
    page_title="관악구 15분 공원 생활권",
    page_icon="🌳",
    layout="wide"
)

DATA_DIR = Path(__file__).parent / "data"

BUILDING_PATH = DATA_DIR / "gwanak_residential_buildings.geojson"
PARK_PATH = DATA_DIR / "gwanak_parks.geojson"
PARK_NODE_PATH = DATA_DIR / "gwanak_park_network_nodes.csv"
GRAPH_PATH = DATA_DIR / "gwanak_walk_network.graphml"
LINK_PATH = DATA_DIR / "gwanak_walk_links.geojson"
BOUNDARY_PATH = DATA_DIR / "gwanak_boundary.geojson"


def clean_id(value):
    text = str(value)
    if text.endswith(".0"):
        text = text[:-2]
    return text


@st.cache_data
def load_geodata():
    buildings = gpd.read_file(BUILDING_PATH).to_crs(4326)
    parks = gpd.read_file(PARK_PATH).to_crs(4326)
    links = gpd.read_file(LINK_PATH).to_crs(4326)
    boundary = gpd.read_file(BOUNDARY_PATH).to_crs(4326)

    buildings["building_id"] = buildings.index.astype(str)

    return buildings, parks, links, boundary


@st.cache_resource
def load_network():
    graph = nx.read_graphml(GRAPH_PATH)
    graph = nx.relabel_nodes(graph, lambda x: clean_id(x))

    for u, v, attrs in graph.edges(data=True):
        try:
            attrs["length"] = float(attrs.get("length", 1))
        except:
            attrs["length"] = 1.0

    node_rows = []

    for node_id, attrs in graph.nodes(data=True):
        try:
            node_rows.append({
                "node_id": clean_id(node_id),
                "x": float(attrs["x"]),
                "y": float(attrs["y"])
            })
        except:
            pass

    nodes = gpd.GeoDataFrame(
        node_rows,
        geometry=[
            Point(row["x"], row["y"])
            for row in node_rows
        ],
        crs=4326
    )

    return graph, nodes


@st.cache_data
def load_park_nodes():
    park_nodes = pd.read_csv(PARK_NODE_PATH)

    park_nodes["node_id"] = park_nodes["node_id"].map(clean_id)

    park_nodes["park_name"] = (
        park_nodes["LABEL"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    park_nodes.loc[
        park_nodes["park_name"].isin(["", "nan", "None"]),
        "park_name"
    ] = park_nodes["park_id"].astype(str)

    return park_nodes


def make_geojson(data):
    return json.loads(data.to_json())


def add_geojson_layer(map_object, data, name, color, fill_color=None,
                      fill_opacity=0.35, weight=2):
    if data is None or len(data) == 0:
        return

    folium.GeoJson(
        make_geojson(data),
        name=name,
        style_function=lambda feature: {
            "color": color,
            "weight": weight,
            "fillColor": fill_color or color,
            "fillOpacity": fill_opacity
        },
        show=True
    ).add_to(map_object)


def nearest_building(buildings, clicked_lat, clicked_lon):
    buildings_metric = buildings.to_crs(5186)
    clicked = gpd.GeoDataFrame(
        geometry=[
            Point(clicked_lon, clicked_lat)
        ],
        crs=4326
    ).to_crs(5186)

    joined = gpd.sjoin_nearest(
        clicked,
        buildings_metric[["building_id", "geometry"]],
        how="left",
        distance_col="distance_m"
    )

    building_id = joined.iloc[0]["building_id"]

    return buildings[
        buildings["building_id"] == building_id
    ].iloc[0]


def calculate_accessibility(
    graph,
    network_nodes,
    links,
    park_nodes,
    selected_building
):
    building_point = selected_building.geometry

    building_metric = gpd.GeoDataFrame(
        geometry=[building_point],
        crs=4326
    ).to_crs(5186)

    nodes_metric = network_nodes.to_crs(5186)

    snapped = gpd.sjoin_nearest(
        building_metric,
        nodes_metric[["node_id", "geometry"]],
        how="left",
        distance_col="snap_distance_m"
    )

    source_node = clean_id(snapped.iloc[0]["node_id"])
    snap_distance = float(snapped.iloc[0]["snap_distance_m"])

    # 15분 = 1,125m
    distances = nx.single_source_dijkstra_path_length(
        graph,
        source=source_node,
        cutoff=1125,
        weight="length"
    )

    reachable_ids = set(distances.keys())

    # 도달 가능한 네트워크 노드
    reachable_nodes = network_nodes[
        network_nodes["node_id"].isin(reachable_ids)
    ].copy()

    # 15분 영역: 도달 가능 노드의 외곽선
    service_area = None

    if len(reachable_nodes) >= 3:
        service_area = reachable_nodes.geometry.unary_union.convex_hull

        service_area = gpd.GeoDataFrame(
            geometry=[service_area],
            crs=4326
        )

    # 링크의 시작·종료 노드 ID 정리
    links_copy = links.copy()

    if "BGNG_LNKG_ID" in links_copy.columns:
        links_copy["from_node"] = (
            links_copy["BGNG_LNKG_ID"].map(clean_id)
        )

    if "END_LNKG_ID" in links_copy.columns:
        links_copy["to_node"] = (
            links_copy["END_LNKG_ID"].map(clean_id)
        )

    reachable_links = links_copy[
        links_copy["from_node"].isin(reachable_ids)
        & links_copy["to_node"].isin(reachable_ids)
    ].copy()

    # 공원 목적지 정리
    park_nodes = park_nodes[
        park_nodes["node_id"].isin(set(graph.nodes))
    ].copy()

    park_nodes["walking_distance_m"] = (
        park_nodes["node_id"].map(distances)
    )

    reachable_parks = park_nodes.dropna(
        subset=["walking_distance_m"]
    ).copy()

    reachable_parks = reachable_parks[
        reachable_parks["walking_distance_m"] <= 1125
    ]

    # 같은 공원명의 여러 목적지 노드는 하나로 통합
    reachable_parks = (
        reachable_parks
        .sort_values("walking_distance_m")
        .drop_duplicates("park_name")
    )

    # 공원 목적지 좌표를 네트워크 노드 좌표로 연결
    park_locations = network_nodes[
        ["node_id", "geometry"]
    ].rename(columns={"geometry": "park_geometry"})

    reachable_parks = reachable_parks.merge(
        park_locations,
        on="node_id",
        how="left"
    )

    return {
        "source_node": source_node,
        "snap_distance": snap_distance,
        "reachable_nodes": reachable_nodes,
        "reachable_links": reachable_links,
        "service_area": service_area,
        "reachable_parks": reachable_parks
    }


# 데이터 불러오기
try:
    buildings, parks, links, boundary = load_geodata()
    graph, network_nodes = load_network()
    park_nodes = load_park_nodes()
except Exception as error:
    st.error("데이터를 불러오지 못했습니다.")
    st.exception(error)
    st.stop()


st.title("🌳 관악구 15분 공원 생활권 분석")

st.write(
    "지도에서 주거용 건물을 클릭하면 해당 건물에서 "
    "도보 15분 안에 갈 수 있는 공원과 보행 네트워크를 보여줍니다."
)

# 지도 중심
center_lat = 37.474
center_lon = 126.951

if "selected_building_id" not in st.session_state:
    st.session_state.selected_building_id = None

# 선택된 건물
selected_building = None

if st.session_state.selected_building_id is not None:
    selected_building = buildings[
        buildings["building_id"]
        == st.session_state.selected_building_id
    ].iloc[0]


# 지도 만들기
m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=13,
    tiles="CartoDB positron",
    control_scale=True
)

# 행정구역
add_geojson_layer(
    m,
    boundary,
    "관악구 경계",
    color="#555555",
    fill_color="#eeeeee",
    fill_opacity=0.05,
    weight=2
)

# 전체 공원
add_geojson_layer(
    m,
    parks,
    "전체 공원",
    color="#238b45",
    fill_color="#74c476",
    fill_opacity=0.35,
    weight=2
)

# 건물 표시
# 성능을 위해 최대 8,000개까지 표시
building_display = buildings.head(8000)

for _, row in building_display.iterrows():
    point = row.geometry

    is_selected = (
        selected_building is not None
        and row["building_id"]
        == selected_building["building_id"]
    )

    folium.CircleMarker(
        location=[point.y, point.x],
        radius=5 if is_selected else 2,
        color="#08306b" if is_selected else "#777777",
        fill=True,
        fill_color="#2171b5" if is_selected else "#aaaaaa",
        fill_opacity=0.8 if is_selected else 0.45,
        weight=2 if is_selected else 0.5,
        tooltip="주거용 건물 클릭"
    ).add_to(m)


accessibility = None

if selected_building is not None:
    accessibility = calculate_accessibility(
        graph,
        network_nodes,
        links,
        park_nodes,
        selected_building
    )

    # 15분 영역
    if accessibility["service_area"] is not None:
        add_geojson_layer(
            m,
            accessibility["service_area"],
            "15분 보행 가능 영역",
            color="#225ea8",
            fill_color="#4292c6",
            fill_opacity=0.25,
            weight=3
        )

    # 15분 안에 도달 가능한 보행 네트워크
    add_geojson_layer(
        m,
        accessibility["reachable_links"],
        "15분 보행 네트워크",
        color="#6a51a3",
        weight=3,
        fill_opacity=0
    )

    # 선택 건물
    point = selected_building.geometry

    folium.Marker(
        location=[point.y, point.x],
        tooltip="선택한 주거 건물",
        icon=folium.Icon(
            color="blue",
            icon="home",
            prefix="fa"
        )
    ).add_to(m)

    reachable_parks = accessibility["reachable_parks"]

    # 접근 가능한 공원 표시
    for _, park in reachable_parks.iterrows():
        geometry = park["park_geometry"]

        if geometry is None:
            continue

        distance = float(park["walking_distance_m"])
        minutes = round(distance / 75, 1)

        folium.Marker(
            location=[geometry.y, geometry.x],
            tooltip=park["park_name"],
            popup=(
                f"<b>{park['park_name']}</b><br>"
                f"보행거리: {distance:.0f}m<br>"
                f"예상시간: {minutes}분"
            ),
            icon=folium.Icon(
                color="orange",
                icon="tree",
                prefix="fa"
            )
        ).add_to(m)


# 지도 출력
map_result = st_folium(
    m,
    width=None,
    height=700,
    returned_objects=["last_clicked"]
)

# 지도 클릭 시 가장 가까운 건물 선택
last_clicked = map_result.get("last_clicked")

if last_clicked:
    clicked_lat = last_clicked["lat"]
    clicked_lon = last_clicked["lng"]

    clicked_building = nearest_building(
        buildings,
        clicked_lat,
        clicked_lon
    )

    clicked_id = clicked_building["building_id"]

    if clicked_id != st.session_state.selected_building_id:
        st.session_state.selected_building_id = clicked_id
        st.rerun()


# 하단 설명
if selected_building is None:
    st.info("지도에서 건물을 클릭해 주세요.")
else:
    reachable_parks = accessibility["reachable_parks"]

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "15분 이내 공원 수",
        f"{reachable_parks['park_name'].nunique()}개"
    )

    if len(reachable_parks) > 0:
        nearest = reachable_parks.iloc[0]
        nearest_distance = float(nearest["walking_distance_m"])
        nearest_minutes = round(nearest_distance / 75, 1)

        col2.metric(
            "가장 가까운 공원",
            nearest["park_name"]
        )

        col3.metric(
            "가장 가까운 거리",
            f"{nearest_distance:.0f}m"
        )

        col4.metric(
            "예상 도보시간",
            f"{nearest_minutes}분"
        )
    else:
        col2.metric("가장 가까운 공원", "없음")
        col3.metric("가장 가까운 거리", "-")
        col4.metric("예상 도보시간", "-")

    st.subheader("선택한 건물 정보")

    building_info = {}

    for column in ["A1", "A4", "A5", "A9"]:
        if column in selected_building.index:
            building_info[column] = selected_building[column]

    st.dataframe(
        pd.DataFrame([building_info]),
        use_container_width=True,
        hide_index=True
    )

    if len(reachable_parks) > 0:
        st.subheader("15분 안에 갈 수 있는 공원")

        park_table = reachable_parks[
            ["park_name", "walking_distance_m"]
        ].copy()

        park_table["expected_minutes"] = (
            park_table["walking_distance_m"] / 75
        ).round(1)

        park_table.columns = [
            "공원명",
            "보행거리(m)",
            "예상시간(분)"
        ]

        st.dataframe(
            park_table,
            use_container_width=True,
            hide_index=True
        )
