from pathlib import Path
import json

import geopandas as gpd
import networkx as nx
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
GRAPH_PATH = DATA_DIR / "gwanak_walk_network.graphml"
BOUNDARY_PATH = DATA_DIR / "gwanak_boundary.geojson"


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
    graph = nx.relabel_nodes(graph, clean_id)

    for _, _, attributes in graph.edges(data=True):
        try:
            attributes["length"] = float(
                attributes.get("length", 1)
            )
        except:
            attributes["length"] = 1.0

    node_rows = []

    for node_id, attributes in graph.nodes(data=True):
        try:
            node_rows.append({
                "node_id": clean_id(node_id),
                "x": float(attributes["x"]),
                "y": float(attributes["y"])
            })
        except:
            continue

    network_nodes = gpd.GeoDataFrame(
        node_rows,
        geometry=[
            Point(row["x"], row["y"])
            for row in node_rows
        ],
        crs=4326
    )

    return graph, network_nodes


def load_park_nodes(parks, network_nodes):
    parks_copy = parks.copy()

    parks_copy["park_name"] = (
        parks_copy["LABEL"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    parks_copy = parks_copy[
        parks_copy["park_name"] != ""
    ].copy()

    # 공원 폴리곤의 대표점 생성
    parks_copy["geometry"] = (
        parks_copy.geometry.representative_point()
    )

    parks_metric = parks_copy[
        ["park_name", "geometry"]
    ].to_crs(5186)

    nodes_metric = network_nodes[
        ["node_id", "geometry"]
    ].to_crs(5186)

    # 공원 대표점을 전체 보행 네트워크에 연결
    park_nodes = gpd.sjoin_nearest(
        parks_metric,
        nodes_metric,
        how="left",
        distance_col="park_snap_distance_m"
    )

    if "index_right" in park_nodes.columns:
        park_nodes = park_nodes.drop(
            columns=["index_right"]
        )

    park_nodes["node_id"] = (
        park_nodes["node_id"]
        .map(clean_id)
    )

    return park_nodes[
        [
            "park_name",
            "node_id",
            "park_snap_distance_m"
        ]
    ]


def add_geojson_layer(
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

    nearest = gpd.sjoin_nearest(
        clicked_point,
        buildings_metric[
            ["building_id", "geometry"]
        ],
        how="left",
        distance_col="distance_m"
    )

    building_id = nearest.iloc[0]["building_id"]

    return buildings[
        buildings["building_id"] == building_id
    ].iloc[0]


def create_network_lines(
    graph,
    network_nodes,
    reachable_node_ids
):
    node_geometry = dict(
        zip(
            network_nodes["node_id"],
            network_nodes.geometry
        )
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


def create_route(
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

    node_geometry = dict(
        zip(
            network_nodes["node_id"],
            network_nodes.geometry
        )
    )

    route_rows = []

    for start, end in zip(
        route_nodes[:-1],
        route_nodes[1:]
    ):
        start = clean_id(start)
        end = clean_id(end)

        if start in node_geometry and end in node_geometry:
            route_rows.append({
                "geometry": LineString([
                    node_geometry[start],
                    node_geometry[end]
                ])
            })

    return gpd.GeoDataFrame(
        route_rows,
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

    # 15분 = 1,125m
    distances = nx.single_source_dijkstra_path_length(
        graph,
        source=source_node,
        cutoff=1125,
        weight="length"
    )

    reachable_node_ids = set(distances.keys())

    reachable_lines = create_network_lines(
        graph,
        network_nodes,
        reachable_node_ids
    )

    # 실제 도달 가능한 보행로 주변 35m를 영역으로 표현
    if len(reachable_lines) > 0:
        lines_metric = reachable_lines.to_crs(5186)

        service_geometry = (
            lines_metric
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

    # 현재 그래프에 연결된 공원만 사용
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
        "reachable_lines": reachable_lines,
        "service_area": service_area,
        "reachable_parks": reachable_parks
    }


try:
    buildings, parks, boundary = load_geodata()
    graph, network_nodes = load_network()

    # 기존 CSV 대신 현재 전체 그래프에 공원 재연결
    park_nodes = load_park_nodes(
        parks,
        network_nodes
    )

except Exception as error:
    st.error("데이터를 불러오지 못했습니다.")
    st.exception(error)
    st.stop()


st.title("🌳 관악구 15분 공원 생활권 분석")

st.write(
    "아파트를 선택하거나 지도에서 주거용 건물을 클릭하면 "
    "15분 보행 가능 영역과 접근 가능한 공원을 확인할 수 있습니다."
)


if "selected_building_id" not in st.session_state:
    st.session_state.selected_building_id = None


st.sidebar.header("아파트 바로가기")

apartment_options = [
    "지도에서 직접 선택"
] + list(FEATURED_APARTMENTS.keys())

selected_apartment = st.sidebar.selectbox(
    "분석할 아파트를 선택하세요",
    apartment_options
)


if selected_apartment != "지도에서 직접 선택":
    latitude, longitude = (
        FEATURED_APARTMENTS[selected_apartment]
    )

    selected = find_nearest_building(
        buildings,
        latitude,
        longitude
    )

    st.session_state.selected_building_id = (
        selected["building_id"]
    )


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


map_object = folium.Map(
    location=[37.474, 126.951],
    zoom_start=13,
    tiles="CartoDB positron",
    control_scale=True
)


add_geojson_layer(
    map_object,
    boundary,
    "관악구 경계",
    color="#555555",
    fill_color="#eeeeee",
    fill_opacity=0.05,
    weight=2
)


add_geojson_layer(
    map_object,
    parks,
    "전체 공원",
    color="#238b45",
    fill_color="#74c476",
    fill_opacity=0.25,
    weight=2
)


if accessibility is not None:

    add_geojson_layer(
        map_object,
        accessibility["service_area"],
        "15분 보행 가능 영역",
        color="#08519c",
        fill_color="#4292c6",
        fill_opacity=0.25,
        weight=3
    )

    reachable_parks = accessibility[
        "reachable_parks"
    ]

    accessible_names = set(
        reachable_parks["park_name"]
    )

    if "LABEL" in parks.columns:

        parks_display = parks.copy()

        parks_display["_park_name"] = (
            parks_display["LABEL"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        accessible_park_polygons = parks_display[
            parks_display["_park_name"].isin(
                accessible_names
            )
        ].copy()

        accessible_park_polygons = (
            accessible_park_polygons
            .drop(columns=["_park_name"])
        )

        add_geojson_layer(
            map_object,
            accessible_park_polygons,
            "15분 안에 갈 수 있는 공원",
            color="#e6550d",
            fill_color="#fdae6b",
            fill_opacity=0.7,
            weight=3
        )

    add_geojson_layer(
        map_object,
        accessibility["reachable_lines"],
        "15분 보행 네트워크",
        color="#6a51a3",
        weight=3,
        fill_opacity=0
    )

    for _, park in reachable_parks.iterrows():

        park_geometry = park["park_geometry"]

        if park_geometry is None:
            continue

        distance = float(
            park["walking_distance_m"]
        )

        minutes = round(distance / 75, 1)

        folium.Marker(
            location=[
                park_geometry.y,
                park_geometry.x
            ],
            tooltip=str(park["park_name"]),
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

    if len(reachable_parks) > 0:

        nearest_park = reachable_parks.iloc[0]

        route = create_route(
            graph,
            network_nodes,
            accessibility["source_node"],
            clean_id(nearest_park["node_id"])
        )

        add_geojson_layer(
            map_object,
            route,
            "가장 가까운 공원까지의 보행 경로",
            color="#d94801",
            weight=6,
            fill_opacity=0
        )


building_display = buildings.head(8000)

for _, building in building_display.iterrows():

    point = building.geometry

    is_selected = (
        selected_building is not None
        and building["building_id"]
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


folium.LayerControl().add_to(map_object)


map_result = st_folium(
    map_object,
    width=None,
    height=700,
    returned_objects=["last_clicked"]
)


last_clicked = map_result.get("last_clicked")

if last_clicked is not None:

    clicked_building = find_nearest_building(
        buildings,
        last_clicked["lat"],
        last_clicked["lng"]
    )

    clicked_id = clicked_building["building_id"]

    if clicked_id != st.session_state.selected_building_id:
        st.session_state.selected_building_id = clicked_id
        st.rerun()


if selected_building is None:

    st.info(
        "왼쪽 메뉴에서 아파트를 선택하거나 "
        "지도에서 주거용 건물을 클릭해 주세요."
    )

else:

    reachable_parks = accessibility[
        "reachable_parks"
    ]

    st.subheader("선택한 위치의 15분 생활권")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "15분 이내 공원 수",
        f"{len(reachable_parks)}개"
    )

    if len(reachable_parks) > 0:

        nearest = reachable_parks.iloc[0]

        distance = float(
            nearest["walking_distance_m"]
        )

        minutes = round(distance / 75, 1)

        col2.metric(
            "가장 가까운 공원",
            nearest["park_name"]
        )

        col3.metric(
            "보행거리",
            f"{distance:.0f}m"
        )

        col4.metric(
            "예상 도보시간",
            f"{minutes}분"
        )

    else:

        col2.metric("가장 가까운 공원", "없음")
        col3.metric("보행거리", "-")
        col4.metric("예상 도보시간", "-")

    st.subheader("15분 안에 갈 수 있는 공원")

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
