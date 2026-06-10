"""Tick 엔진 + Sim 상태 컨테이너.

매 tick: (1) agent 업데이트, (2) Observation 구성 (V2X 라우팅 + perception),
(3) AVLogic.decide → Action, (4) 자차 kinematic 적용.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from trafficsim.agents import Pedestrian, TrafficLight, Vehicle
from trafficsim.avlogic.interface import (
    Action,
    AVLogic,
    EgoState,
    Observation,
    PerceivedObject,
    PerceptionView,
    V2XMsg,
)
from trafficsim.v2x import (
    bsm_from_vehicle,
    psm_from_pedestrian,
    route_messages,
    spat_from_traffic_light,
)
from trafficsim.world import WorldMap

SPEED_TAU = 1.0
MAX_ACCEL = 3.0
MAX_DECEL = 4.0
YAW_RATE_GAIN = 1.0
PERCEPTION_RANGE = 100.0
PERCEPTION_HALF_FOV = math.pi / 2


@dataclass
class SimConfig:
    dt: float = 0.1
    rng_seed: int = 0


@dataclass
class Sim:
    cfg: SimConfig
    logic: AVLogic
    world: WorldMap | None = None
    t: float = 0.0
    tick_count: int = 0
    ego: EgoState = field(
        default_factory=lambda: EgoState(x=0.0, y=0.0, yaw=0.0, speed=0.0, accel=0.0)
    )
    traffic_lights: list[TrafficLight] = field(default_factory=list)
    pedestrians: list[Pedestrian] = field(default_factory=list)
    vehicles: list[Vehicle] = field(default_factory=list)
    injected_msgs: list[V2XMsg] = field(default_factory=list)
    last_action: Action | None = None
    last_reason: str = ""

    def add_traffic_light(self, tl: TrafficLight) -> None:
        self.traffic_lights.append(tl)

    def add_pedestrian(self, p: Pedestrian) -> None:
        self.pedestrians.append(p)

    def add_vehicle(self, v: Vehicle) -> None:
        self.vehicles.append(v)

    def inject_message(self, msg: V2XMsg) -> None:
        self.injected_msgs.append(msg)

    def _update_agents(self) -> None:
        for tl in self.traffic_lights:
            tl.update(self.t)
        for p in self.pedestrians:
            p.update(self.t, self.cfg.dt)
        for v in self.vehicles:
            v.update(self.t, self.cfg.dt, lead_distance=None, lead_speed=None)

    def _collect_v2x(self) -> list[V2XMsg]:
        msgs: list[V2XMsg] = []
        for tl in self.traffic_lights:
            msgs.append(spat_from_traffic_light(tl, rx_time=self.t))
        for p in self.pedestrians:
            msgs.append(psm_from_pedestrian(p, rx_time=self.t))
        for v in self.vehicles:
            msgs.append(bsm_from_vehicle(v, rx_time=self.t))
        msgs.extend(m for m in self.injected_msgs if m.rx_time <= self.t)
        return route_messages(msgs, self.ego)

    def _build_perception(self) -> PerceptionView:
        objs: list[PerceivedObject] = []
        for v in self.vehicles:
            if self._in_fov(v.x, v.y):
                objs.append(
                    PerceivedObject(obj_type="vehicle", x=v.x, y=v.y, speed=v.speed)
                )
        for p in self.pedestrians:
            if self._in_fov(p.x, p.y):
                speed = math.hypot(p.vx, p.vy)
                objs.append(
                    PerceivedObject(obj_type="pedestrian", x=p.x, y=p.y, speed=speed)
                )
        return PerceptionView(objects=objs)

    def _in_fov(self, x: float, y: float) -> bool:
        dx = x - self.ego.x
        dy = y - self.ego.y
        d = math.hypot(dx, dy)
        if d > PERCEPTION_RANGE:
            return False
        if d < 1e-6:
            return True
        bearing = math.atan2(dy, dx) - self.ego.yaw
        bearing = (bearing + math.pi) % (2 * math.pi) - math.pi
        return abs(bearing) <= PERCEPTION_HALF_FOV

    def _apply_action(self, action: Action) -> None:
        dt = self.cfg.dt
        delta = (action.target_speed - self.ego.speed) / SPEED_TAU
        delta = max(-MAX_DECEL, min(MAX_ACCEL, delta))
        new_speed = max(0.0, self.ego.speed + delta * dt)
        self.ego.accel = (new_speed - self.ego.speed) / dt if dt > 0 else 0.0
        self.ego.speed = new_speed
        steering = max(-math.pi / 4, min(math.pi / 4, action.steering))
        yaw_rate = YAW_RATE_GAIN * steering
        self.ego.yaw += yaw_rate * dt
        self.ego.x += self.ego.speed * math.cos(self.ego.yaw) * dt
        self.ego.y += self.ego.speed * math.sin(self.ego.yaw) * dt

    def tick(self) -> None:
        self._update_agents()
        v2x = self._collect_v2x()
        perception = self._build_perception()
        obs = Observation(ego=self.ego, v2x_messages=v2x, perception=perception, t=self.t)
        action = self.logic.decide(obs)
        self._apply_action(action)
        self.last_action = action
        self.last_reason = action.reason
        self.t += self.cfg.dt
        self.tick_count += 1
