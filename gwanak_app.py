from pathlib import Path
import json

import geopandas as gpd
import networkx as nx
import pandas as pd
import streamlit as st
import folium

from shapely.geometry import Point, LineString
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
BOUNDARY_PATH = DATA_DIR / "gwanak_boundary.geojson"


# 아파트 대표 좌표
FEATURED_APARTMENTS = {
    "관악푸르지오": (37.4885, 126.9470),
    "서울대입구삼성아파트": (37.4785, 126.9525),
    "신림주공1단지": (37.4670, 126.9215),
    "봉천두산아파트": (37.4835, 126.9435),
    "관악드림타운": (37.4840, 126.9400),
}


def clean_id(value):
    value = str(value)

    if value.endswith(".0"):
        value = value[:-2]

    return value


@st.cache_data
def load_geodata():
    buildings = gpd.read_file(BUILDING_PATH).to_crs(4326)
    parks = gpd.read_file(PARK_PATH).to_crs(4326)
    boundary = gpd.read_file(BOUNDARY_PATH).to_crs(4326)

    buildings = buildings.reset_index(drop=True)
    buildings["building_id"] = buildings.index.astype(str)

    return buildings, parks, boundary


@st.cache_resource
def load_network():
    graph = nx.read_graphml(GRAPH_PATH)
    graph = nx.relabel_nodes(
        graph,
        lambda node_id: clean_id(node_id)
    )

    for _, _, attrs in graph.edges(data=True):
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

    network_nodes = gpd.GeoDataFrame(
        node_rows,
        geometry=[
            Point(row["x"], row["y"])
            for row in node_rows
        ],
        crs=4326
    )

    return graph, network_nodes


@st.cache_data
def load_park_nodes():
    park_nodes = pd.read_csv(PARK_NODE_PATH)

    park_nodes["node_id"] = (
        park_nodes["node_id"]
        .map(clean_id)
    )

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


def add_layer(
    map_object,
    data,
    layer_name,
    color,
    fill_color=None,
    fill_opacity=0.3,
    weight=2
):
    if data is None or len(data) == 0:
        return

    folium.GeoJson(
        json.loads(data.to_json()),
        name=layer_name,
        style_function=lambda feature: {
            "color": color,
            "weight": weight,
            "fillColor": fill_color or color,
            "fillOpacity": fill_opacity
        }
    ).add_to(map_object)


def find_nearest_building(
    buildings,
    latitude,
    longitude
):
    buildings_metric = buildings.to_crs(5186)

    clicked_point = gpd.GeoDataFrame(
        geometry=[
            Point(longitude, latitude)
        ],
        crs=4326
    ).to_crs(5186)

    joined = gpd.sjoin_nearest(
        clicked_point,
        buildings_metric[["building_id", "geometry"]],
        how="left",
        distance_col="distance_m"
    )

    building_id = joined.iloc[0]["building_id"]

    return buildings[
        buildings["building_id"] == building_id
    ].iloc[0]


def make_network_lines(
    graph,
    network_nodes,
    reachable_node_ids
):
    node_geometry = (
        network_nodes
        .set_index("node_id")["geometry"]
        .to_dict()
    )

    line_rows = []

    for start, end in graph.edges():
        start = clean_id(start)
        end = clean_id(end)

        if start not in reachable_node_ids:
            continue

        if end not in reachable_node_ids:
            continue

        if start not in node_geometry:
            continue

        if end not in node_geometry:
            continue

        line_rows.append({
            "geometry": LineString([
                node_geometry[start],
                node_geometry[end]
            ])
        })

    if len(line_rows) == 0:
        return gpd.GeoDataFrame(
            {"geometry": []},
            geometry="geometry",
            crs=4326
        )

    return gpd.GeoDataFrame(
        line_rows,
        geometry="geometry",
        crs=4326
    )


def make_route(
    graph,
    network_nodes,
    source_node,
    target_node
):
    try:
        route_nodes = nx.shortest_path(
            graph,
            source=source_node,
            target=target_node,
            weight="length"
        )
    except:
        return gpd.GeoDataFrame(
            {"geometry": []},
            geometry="geometry",
            crs=4326
        )

    node_geometry = (
        network_nodes
        .set_index("node_id")["geometry"]
        .to_dict()
    )

    route_lines = []

    for start, end in zip(
        route_nodes[:-1],
        route_nodes[1:]
    ):
        if start in node_geometry and end in node_geometry:
            route_lines.append(
                LineString([
                    node_geometry[start],
                    node_geometry[end]
                ])
            )

    return gpd.GeoDataFrame(
        {"geometry": route_lines},
        geometry="geometry",
        crs=4326
    )


def calculate_accessibility(
    graph,
    network_nodes,
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

    source_node = clean_id(
        snapped.iloc[0]["node_id"]
    )

    snap_distance = float(
        snapped.iloc[0]["snap_distance_m"]
    )

    # 도보 15분 = 1,125m
    distances = nx.single_source_dijkstra_path_length(
        graph,
        source=source_node,
        cutoff=1125,
        weight="length"
    )

    reachable_node_ids = set(distances.keys())

    reachable_nodes = network_nodes[
        network_nodes["node_id"].isin(
            reachable_node_ids
        )
    ].copy()

    reachable_links = make_network_lines(
        graph,
        network_nodes,
        reachable_node_ids
    )

    # 볼록다각형 대신 보행로 주변 buffer로 영역 생성
    if len(reachable_links) > 0:
        links_metric = reachable_links.to_crs(5186)

        service_geometry = (
            links_metric
            .buffer(35)
            .unary_union
        )

        service_area = gpd.GeoDataFrame(
            {"geometry": [service_geometry]},
            geometry="geometry",
            crs=5186
        ).to_crs(4326)
    else:
        service_area = None

    park_nodes = park_nodes[
        park_nodes["node_id"].isin(
            set(graph.nodes)
        )
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

    # 같은 공원명은 하나로 계산
    reachable_parks = (
        reachable_parks
        .sort_values("walking_distance_m")
        .drop_duplicates("park_name")
    )

    park_locations = network_nodes[
        ["node_id", "geometry"]
    ].rename(
        columns={
            "geometry": "park_geometry"
        }
    )

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


try:
    buildings, parks, boundary = load_geodata()
    graph, network_nodes = load_network()
    park_nodes = load_park_nodes()

except Exception as error:
    st.error("데이터를 불러오지 못했습니다.")
    st.exception(error)
    st.stop()


st.title("🌳 관악구 15분 공원 생활권 분석")

st.write(
    "아파트를 선택하거나 지도에서 건물을 클릭하면 "
    "15분 보행 가능 영역과 접근 가능한 공원을 확인할 수 있습니다."
)


# 아파트 바로가기
st.sidebar.header("아파트 바로가기")

apartment_options = [
    "지도에서 직접 선택"
] + list(FEATURED_APARTMENTS.keys())

selected_apartment = st.sidebar.selectbox(
    "분석할 아파트를 선택하세요",
    apartment_options
)

if selected_apartment != "지도에서 직접 선택":
    apartment_lat, apartment_lon = (
        FEATURED_APARTMENTS[selected_apartment]
    )

    apartment_building = find_nearest_building(
        buildings,
        apartment_lat,
        apartment_lon
    )

    st.session_state.selected_building_id = (
        apartment_building["building_id"]
    )


if "selected_building_id" not in st.session_state:
    st.session_state.selected_building_id = None


selected_building = None

if st.session_state.selected_building_id is not None:
    selected_building = buildings[
        buildings["building_id"]
        == st.session_state.selected_building_id
    ].iloc[0]


accessibility = None

if selected_building is not None:
    accessibility = calculate_accessibility(
        graph,
        network_nodes,
        park_nodes,
        selected_building
    )


# 지도 생성
map_object = folium.Map(
    location=[37.474, 126.951],
    zoom_start=13,
    tiles="CartoDB positron",
    control_scale=True
)


# 관악구 경계
add_layer(
    map_object,
    boundary,
    "관악구 경계",
    color="#555555",
    fill_color="#eeeeee",
    fill_opacity=0.05,
    weight=2
)


# 전체 공원
add_layer(
    map_object,
    parks,
    "전체 공원",
    color="#238b45",
    fill_color="#74c476",
    fill_opacity=0.25,
    weight=2
)


if accessibility is not None:

    # 15분 보행 가능 영역
    add_layer(
        map_object,
        accessibility["service_area"],
        "15분 보행 가능 영역",
        color="#08519c",
        fill_color="#4292c6",
        fill_opacity=0.25,
        weight=3
    )

    # 15분 안에 접근 가능한 공원
    accessible_names = set(
        accessibility[
            "reachable_parks"
        ]["park_name"]
    )

    parks_for_display = parks.copy()

    if "LABEL" in parks_for_display.columns:
        parks_for_display["_park_name"] = (
            parks_for_display["LABEL"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        accessible_park_polygons = parks_for_display[
            parks_for_display["_park_name"].isin(
                accessible_names
            )
        ].copy()

        accessible_park_polygons = (
            accessible_park_polygons
            .drop(columns=["_park_name"])
        )

        add_layer(
            map_object,
            accessible_park_polygons,
            "15분 안에 접근 가능한 공원",
            color="#e6550d",
            fill_color="#fdae6b",
            fill_opacity=0.7,
            weight=3
        )

    # 15분 보행 네트워크
    add_layer(
        map_object,
        accessibility["reachable_links"],
        "15분 보행 네트워크",
        color="#6a51a3",
        weight=3,
        fill_opacity=0
    )

    # 공원 마커
    for _, park in accessibility[
        "reachable_parks"
    ].iterrows():

        park_geometry = park["park_geometry"]

        if park_geometry is None:
            continue

        distance = float(
            park["walking_distance_m"]
        )

        minutes = round(distance / 75, 1)

        folium.Marker(
           
