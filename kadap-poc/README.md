# KADaP Alpamayo PoC (한자연 납품용 자율주행 테스트베드)

한국자동차연구원(KATECH, Korea Automotive Technology Institute) 납품용 인터랙티브 closed-loop 시뮬레이션 UI.
NVIDIA Alpamayo 1.5 + Alpasim + NRE를 KADaP A40 노드에서 띄우고, Gradio
프론트엔드에서 시나리오와 ablation 을 선택해 실행한다.

PoC의 핵심 메시지: **"변경된 정보 → 다른 판단"** — 같은 시나리오에 다른
ablation(카메라 마스크, 시작 offset 등)을 넣었을 때 Alpamayo 1.5 추론이
실제로 다른 trajectory를 내놓는다는 걸 KATECH 연구원이 자기 손으로
확인하게 만든다.

## 구조

- `app.py` — Gradio UI (7 탭)
- `runner.py` — one-shot 시뮬레이션 오케스트레이터 (compose down → wizard
  + ablation Hydra override → compose up → poll → finalize)
- `ablation.py` — `AblationSpec` + PRESETS (camera mask, start offset)
- `scenarios.py` — NuRec 카탈로그 + HF 다운로드
- `trace.py` — step-by-step closed-loop trace (NRE → driver → controller)
- `metrics.py` — controller_return 시계열 → 속도/횡가속/jerk
- `report.py` — PDF 1-pager (rollout 1개당)
- `client.py` — daemon-mode gRPC 클라이언트 (현재 upstream 버그로 미사용)

## 사전 조건

- `.env` 에 `HF_TOKEN` 설정
- Alpasim vendored fork 패치 적용됨:
  - `submit_recording_ground_truth` 가 pose 버퍼 pre-seed
  - `Alpamayo15Model` 이 `attn_implementation="sdpa"` 사용
- `scripts/run_closedloop.sh` 가 한 번 돌아 wizard 가 docker-compose.yaml 생성

## 실행

```bash
# 1) closed-loop 스택 기동 (10분, driver-0 모델 로드 + sensorsim warmup)
bash scripts/run_closedloop.sh

# 2) Gradio UI 띄움 (호스트 alpasim venv 재활용)
nohup bash scripts/run_kadap_poc.sh > /tmp/kadap-poc.log 2>&1 < /dev/null &
# 또는 직접: ./alpasim/.venv/bin/python kadap-poc/app.py
```

기본 포트 7870. KADaP 외부 노출 포트는 인스턴스 콘솔에서 매핑.

## Ablation 사용

`ablation.PRESETS` 에 정의된 항목을 Tab ② 에서 체크 → "ablation 순차
실행" 으로 같은 scene에 변형된 입력을 차례로 적용.

| Preset | 효과 |
|---|---|
| `base` | 모든 카메라, time_start_offset_us=300ms (디폴트) |
| `no_left` | `camera_cross_left_120fov` 만 제거 |
| `no_tele` | `camera_front_tele_30fov` 만 제거 |
| `front_only` | 전방 wide 카메라 1개만 사용 |
| `start_500ms` | scene 진입 0.5초 지연 |
| `start_2s` | scene 진입 2.0초 지연 |
| `start_5s` | scene 진입 5.0초 지연 |

새 ablation 추가: `kadap-poc/ablation.py` 의 PRESETS dict 에 한 줄 추가하면
즉시 UI dropdown 에 반영됨. Hydra 오버라이드만으로 표현 가능한 변경은
지금 구조로 끝, traffic 추가/제거나 sensor noise injection 같은 건 별도
post-wizard patcher 필요 (v0 범위 밖).

CLI 사용 예:

```bash
# 단일 ablation rollout
./alpasim/.venv/bin/python kadap-poc/runner.py --ablation no_left

# 기존 rollout 메타 stamping (driver=alpamayo1_5 로 backfill)
./alpasim/.venv/bin/python kadap-poc/runner.py --backfill-driver alpamayo1_5
```

## 시나리오 카탈로그

`alpasim/data/scenes/sim_scenes_2602.csv` 의 916개 NuRec 클립이 base. Tab
⑦에서 검색 + HF 다운로드 가능. `scripts/probe_scene_lengths.py` 를 돌리면
로컬에 캐시된 USDZ 의 GT trajectory 길이를 `long_scenes.json` 으로 정렬해
저장 (현재 모든 OSS 클립이 20초로 동일).

## v0 한계 / upstream 의존성

- **모든 OSS scene이 20초 GT** — 다양한 길이의 scene이 필요하면 NRE 데이터
  파이프라인에서 별도 추출 필요
- **Driver는 단일 GPU에 1개만 적재 가능** (Alpamayo 1.5 10B + Cosmos-Reason2 8B
  → A40 22 GB). Ablation 순차 실행은 정의상 N × 10분
- **Daemon 모드는 upstream 버그로 미사용** — `docs/UPSTREAM_BUG_DAEMON_DRIVER.md`
  참고. PoC v0 는 one-shot compose 모드
- **SDPA fallback** — `flash_attn` 미설치 환경의 cu_seqlens_q 버그 우회.
  inference 정확도는 bf16 잡음 수준에서 동일하지만 native flash-attn 설치 시
  `KADAP_ATTN_IMPL=flash_attention_2` 로 원복 가능
