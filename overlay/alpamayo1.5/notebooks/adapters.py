"""Data adapter abstractions for the POC.

The Korea Automotive Research Institute (KATECH) testbed will eventually feed
real vehicle CAN/camera streams and roadside V2X / infrastructure-LiDAR
messages into Alpamayo. This file defines the minimal interface so the rest
of the codebase can be source-agnostic. Today the concrete implementations
wrap the existing nav_demo_samples.json + load_physical_aiavdataset path; in
the production system they will be replaced with live ROS / DDS / MQTT
subscribers without touching app.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from alpamayo1_5.load_physical_aiavdataset import load_physical_aiavdataset


@dataclass
class VehicleObservation:
    """One time-aligned observation from the ego vehicle."""

    clip_id: str
    t0_us: int
    payload: dict  # the dict returned by load_physical_aiavdataset


class VehicleDataAdapter:
    """Adapter for the test vehicle: cameras + ego pose history.

    POC: pulls from physical_aiavdataset parquet files.
    Production: subscribe to vehicle DDS topics (camera_*, ego_state).
    """

    name = "Vehicle CAN/Camera Adapter"

    def fetch(self, clip_id: str, t0_us: int) -> VehicleObservation:
        data = load_physical_aiavdataset(clip_id, t0_us=t0_us)
        return VehicleObservation(clip_id=clip_id, t0_us=t0_us, payload=data)


@dataclass
class V2XMessage:
    """A natural-language message produced by infrastructure / V2X stack."""

    text: str
    source: str  # e.g. "RSU-12", "TrafficSignal-A4", "RoadsideLiDAR-7"
    confidence: float = 1.0


class V2XAdapter:
    """Adapter for roadside infrastructure messages.

    POC: messages are typed by the operator in the UI (or swap_direction is
    used to fabricate a counterfactual).
    Production: parse SAE J2735 / ETSI ITS-G5 messages from RSUs, summarize
    into Alpamayo's nav_text format.
    """

    name = "Roadside V2X / Infra-LiDAR Adapter"

    def from_text(self, text: str, source: str = "operator") -> Optional[V2XMessage]:
        text = (text or "").strip()
        if not text:
            return None
        return V2XMessage(text=text, source=source)
