"""Autoware sim 통합 — C-실용 변형.

구성:
  - Autoware planning_simulator (Docker 컨테이너, headless)
  - rosbridge_server (컨테이너 내 WS :9090)
  - Alpamayo bridge (호스트 venv, rosbridge WS 클라이언트로 image 구독, trajectory 발행)
  - 합성 카메라 (호스트, 기존 closedloop rollout mp4 frame을 ROS 이미지로 발행)
  - FastAPI 새 탭 (browser → HTMX polling → 호스트가 보관한 최신 state)

호스트(alpasim venv, Python 3.12) ↔ 컨테이너(ROS humble, Python 3.10) 분리 이유:
  Alpamayo 1.5 의존성과 ROS 2 humble의 Python 3.10이 충돌. rosbridge로 우회.
"""
