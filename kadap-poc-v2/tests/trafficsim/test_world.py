from pathlib import Path

from trafficsim.world import WorldMap, load_default_map

MAP_PATH = Path(__file__).resolve().parents[2] / "trafficsim" / "map.geojson"


def test_default_map_loads():
    wm = load_default_map()
    assert isinstance(wm, WorldMap)


def test_map_has_lanes():
    wm = load_default_map()
    assert len(wm.lanes) >= 4


def test_map_has_intersections():
    wm = load_default_map()
    assert len(wm.intersections) >= 2


def test_map_has_crosswalks():
    wm = load_default_map()
    assert len(wm.crosswalks) >= 1


def test_lane_has_polyline():
    wm = load_default_map()
    lane = wm.lanes[0]
    assert len(lane.polyline) >= 2
    x, y = lane.polyline[0]
    assert isinstance(x, float)
    assert isinstance(y, float)


def test_geojson_file_exists():
    assert MAP_PATH.exists()
