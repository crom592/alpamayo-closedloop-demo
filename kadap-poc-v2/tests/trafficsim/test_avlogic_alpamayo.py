from trafficsim.avlogic.alpamayo_proxy import AlpamayoLogic
from trafficsim.avlogic.interface import (
    EgoState,
    Observation,
    PerceptionView,
)


def _obs():
    return Observation(
        ego=EgoState(x=0.0, y=0.0, yaw=0.0, speed=8.0, accel=0.0),
        v2x_messages=[],
        perception=PerceptionView(objects=[]),
        t=0.0,
    )


def test_alpamayo_logic_returns_action(monkeypatch):
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_MODE", "mock")
    a = AlpamayoLogic().decide(_obs())
    assert a is not None
    assert "Alpamayo" in a.reason


def test_alpamayo_logic_mock_uses_rule_based_baseline(monkeypatch):
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_MODE", "mock")
    a = AlpamayoLogic().decide(_obs())
    assert a.target_speed == 8.0  # cruise


def test_alpamayo_logic_live_mode_raises_when_unavailable(monkeypatch):
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_MODE", "live")
    monkeypatch.setenv("TRAFFICSIM_ALPAMAYO_ENDPOINT", "")
    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        AlpamayoLogic().decide(_obs())
