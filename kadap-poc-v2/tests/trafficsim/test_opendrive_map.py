from pathlib import Path

from trafficsim.world import WorldMap, load_opendrive_map

E6 = Path(__file__).resolve().parents[2] / "trafficsim" / "maps" / "e6mini.xodr"


def test_load_opendrive_returns_worldmap():
    wm = load_opendrive_map(E6)
    assert isinstance(wm, WorldMap)


def test_load_opendrive_has_lanes():
    wm = load_opendrive_map(E6)
    assert len(wm.lanes) >= 1
    lane = wm.lanes[0]
    assert lane.id.startswith("road_")
    assert len(lane.polyline) >= 2


def test_load_opendrive_origin_shifted_to_nonnegative():
    wm = load_opendrive_map(E6)
    all_x = [pt[0] for lane in wm.lanes for pt in lane.polyline]
    all_y = [pt[1] for lane in wm.lanes for pt in lane.polyline]
    assert min(all_x) >= -1e-6
    assert min(all_y) >= -1e-6


def test_load_opendrive_speed_limit_positive():
    wm = load_opendrive_map(E6)
    assert all(lane.speed_limit > 0 for lane in wm.lanes)
