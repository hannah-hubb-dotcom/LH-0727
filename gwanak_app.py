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


def geojson_data(data):
    return json.loads(data.to_json())


def add_geojson_layer(
    map_object,
    data,
    name,
    color,
    fill_color=None,
    fill_opacity=0.35,
    weight=2
):
    if data is None or len(data) == 0:
        return

    folium.GeoJson(
        geojson_data(data),
        name=name,
        style_function=lambda feature: {
            "color": color,
            "weight": weight,
            "fillColor": fill_color or color,
            "fillOpacity": fill_opacity
        },
        show=True
    ).add_to(map_object)


def find_nearest_building(
    buildings,
    clicked_lat,
    clicked_lon
):
    buildings_metric = buildings.to_crs(5186)

    clicked_point = gpd.GeoDataFrame(
        geometry=[
            Point(clicked_lon, clicked_lat)
        ],
        crs=4326
    ).to_crs(5186)

    joined = gpd.sjoin_nearest(
        clicked_point,
        buildings_metric[
            ["building_id", "geometry"]
        ],
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
    reachable_ids
):
    node_geometry = (
        network_nodes
        .set_index("node_id")["geometry"]
        .to_dict()
    )

    edge_rows = []

    for u, v in graph.edges():
        u = clean_id(u)
        v = clean_id(v)

        if u not in reachable_ids:
            continue

        if v not in reachable_ids:
            continue

        if u not in node_geometry:
            continue

        if v not in node_geometry:
            continue

        edge_rows.append({
            "from_node": u,
            "to_node": v,
            "geometry": LineString([
                node_geometry[u],
                node_geometry[v]
            ])
        })

    if len(edge_rows) == 0:
        return gpd.GeoDataFrame(
            {"geometry": []},
            geometry="geometry",
            crs=4326
        )

    return gpd.GeoDataFrame(
        edge_rows,
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
        nodes_metric[
            ["node_id", "geometry"]
        ],
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

    reachable_ids = set(distances.keys())

    reachable_nodes = network_nodes[
        network_nodes["node_id"].isin(reachable_ids)
    ].copy()

    reachable_links = make_network_lines(
        graph,
        network_nodes,
        reachable_ids
    )

    service_area = None

    if len(reachable_nodes) >= 3:
        service_area = reachable_nodes.geometry.unary_union.convex_hull

        service_area = gpd.GeoDataFrame(
            {"geometry": [service_area]},
            geometry="geometry",
            crs=4326
        )

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


# 데이터 불러오기
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
    "지도에서 주거용 건물을 클릭하면 "
    "해당 건물의 15분 보행 가능 영역과 "
    "접근 가능한 공원을 확인할 수 있습니다."
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


# 행정구역
add_geojson_layer(
    map_object,
    boundary,
    "관악구 경계",
    color="#555555",
    fill_color="#eeeeee",
    fill_opacity=0.05,
    weight=2
)


# 전체 공원
add_geojson_layer(
    map_object,
    parks,
    "전체 공원",
    color="#238b45",
    fill_color="#74c476",
    fill_opacity=0.3,
    weight=2
)


if accessibility is not None:

    # 15분 영역
    add_geojson_layer(
        map_object,
        accessibility["service_area"],
        "15분 보행 가능 영역",
        color="#08519c",
        fill_color="#4292c6",
        fill_opacity=0.22,
        weight=3
    )

    # 15분 영역과 겹치는 공원
    accessible_park_polygons = gpd.sjoin(
        parks,
        accessibility["service_area"][["geometry"]],
        how="inner",
        predicate="intersects"
    )

    if "index_right" in accessible_park_polygons.columns:
        accessible_park_polygons = (
            accessible_park_polygons
            .drop(columns=["index_right"])
        )

    add_geojson_layer(
        map_object,
        accessible_park_polygons,
        "15분 안에 접근 가능한 공원",
        color="#e6550d",
        fill_color="#fdae6b",
        fill_opacity=0.65,
        weight=3
    )

    # 접근 가능한 보행 네트워크
    add_geojson_layer(
        map_object,
        accessibility["reachable_links"],
        "15분 보행 네트워크",
        color="#6a51a3",
        weight=3,
        fill_opacity=0
    )

    # 접근 가능한 공원 마커
    for _, park in accessibility[
        "reachable_parks"
    ].iterrows():

        geometry = park["park_geometry"]

        if geometry is None:
            continue

        distance = float(
            park["walking_distance_m"]
        )

        minutes = round(distance / 75, 1)

        folium.Marker(
            location=[
                geometry.y,
                geometry.x
            ],
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
        ).add_to(map_object)

    # 가장 가까운 공원까지의 대표 경로
    reachable_parks = accessibility[
        "reachable_parks"
    ]

    if len(reachable_parks) > 0:
        nearest_park = reachable_parks.iloc[0]

        route = make_route(
            graph,
            network_nodes,
            accessibility["source_node"],
            clean_id(nearest_park["node_id"])
        )

        add_geojson_layer(
            map_object,
            route,
            "가장 가까운 공원까지의 대표 경로",
            color="#d94801",
            weight=6,
            fill_opacity=0
        )


# 건물 표시
# 너무 많은 마커로 인한 속도 저하를 막기 위해 최대 8,000개 표시
building_display = buildings.head(8000)

for _, row in building_display.iterrows():

    point = row.geometry

    is_selected = (
        selected_building is not None
        and row["building_id"]
        == selected_building["building_id"]
    )

    folium.CircleMarker(
        location=[
            point.y,
            point.x
        ],
        radius=6 if is_selected else 2,
        color="#08306b" if is_selected else "#777777",
        fill=True,
        fill_color="#2171b5" if is_selected else "#aaaaaa",
        fill_opacity=0.9 if is_selected else 0.45,
        weight=2 if is_selected else 0.5,
        tooltip="주거용 건물"
    ).add_to(map_object)


# 선택한 건물
if selected_building is not None:

    selected_point = selected_building.geometry

    folium.Marker(
        location=[
            selected_point.y,
            selected_point.x
        ],
        tooltip="선택한 건물",
        icon=folium.Icon(
            color="blue",
            icon="home",
            prefix="fa"
        )
    ).add_to(map_object)


# 레이어 컨트롤
folium.LayerControl().add_to(map_object)


# 지도 출력
map_result = st_folium(
    map_object,
    width=None,
    height=700,
    returned_objects=["last_clicked"]
)


# 클릭한 위치에서 가장 가까운 건물 선택
last_clicked = map_result.get("last_clicked")

if last_clicked:

    clicked_lat = last_clicked["lat"]
    clicked_lon = last_clicked["lng"]

    clicked_building = find_nearest_building(
        buildings,
        clicked_lat,
        clicked_lon
    )

    clicked_id = clicked_building["building_id"]

    if clicked_id != st.session_state.selected_building_id:
        st.session_state.selected_building_id = clicked_id
        st.rerun()


# 하단 정보
if selected_building is None:

    st.info("지도에서 주거용 건물을 클릭해 주세요.")

else:

    reachable_parks = accessibility[
        "reachable_parks"
    ]

    st.subheader("선택한 건물의 15분 생활권")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "15분 이내 공원 수",
        f"{len(reachable_parks)}개"
    )

    if len(reachable_parks) > 0:

        nearest = reachable_parks.iloc[0]

        nearest_distance = float(
            nearest["walking_distance_m"]
        )

        nearest_minutes = round(
            nearest_distance / 75,
            1
        )

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

        col2.metric(
            "가장 가까운 공원",
            "없음"
        )

        col3.metric(
            "가장 가까운 거리",
            "-"
        )

        col4.metric(
            "예상 도보시간",
            "-"
        )

    st.subheader("접근 가능한 공원 목록")

    if len(reachable_parks) > 0:

        park_table = reachable_parks[
            [
                "park_name",
                "walking_distance_m"
            ]
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

    st.caption(
        f"보행 네트워크 연결거리: "
        f"{accessibility['snap_distance']:.1f}m"
    )
