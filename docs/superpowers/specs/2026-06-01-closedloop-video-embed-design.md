# Closed-Loop NRE 합성 영상 Tab ⑥ 임베드 — 설계 문서

- **작성**: 2026-06-01
- **대상 시스템**: KATECH PoC 데모 (`kadap-poc-v2`)
- **트리거**: 평가위원에게 closed-loop 결과를 "trace + 메트릭 + PDF"로만 제공하던 것을 보완,
  NRE 합성 카메라 영상을 직접 시각적으로 시연하기 위함.

## 1. 목표

Tab ⑥ Closed-Loop 화면에서 rollout을 선택하면 **NRE가 매 step 합성한 front_wide 120fov
카메라 영상**이 V2X 배너 · AI reasoning 자막 · ADE/FDE 메트릭 오버레이와 함께 즉시
재생되도록 한다. 시연 자리에서 라이브 렌더링 시간을 제로화하기 위해 사전 일괄
영상화로 처리한다.

## 2. 비목표

- closed-loop 시뮬레이션 라이브 실행 시간 단축 (NRE 60~80분/scene은 NVIDIA 표준 비용)
- 6대 전체 카메라 그리드 표출 (단일 front_wide만, 평가위원 시선 집중)
- ego 위치 plotly와의 분할 화면 (Tab ⑥의 기존 plotly 섹션이 별도로 담당)
- 영상에서의 인터랙티브 클릭 / step jump (기존 step slider가 담당)

## 3. 아키텍처

```
existing_rollouts() ──► extract_frames() ──► parse ASL meta ──► matplotlib + ffmpeg
   (8개 rollout)        (~ASL→JPEG)         (V2X/메트릭/CoT)    (front_wide + overlay)
                                                                            │
                                                                            ▼
                                                  kadap-poc-v2/closedloop_videos/<uuid>.mp4
                                                                            │
                          Tab ⑥ rollout 선택 ◄─── StaticFiles ──────────────┘
                          video controls 재생
```

사전 일괄 처리 / 시연 시 정적 파일 재생만. 4단계 모두 batch 1회 실행.

## 4. 컴포넌트

| # | 파일 | 신규/수정 | 역할 |
|---|---|---|---|
| 1 | `scripts/render_closedloop_videos.py` | 신규 | 8 rollout 순회: frames 보장 → ASL meta 추출 → matplotlib 오버레이 합성 → ffmpeg mp4 인코딩 |
| 2 | `kadap-poc-v2/closedloop_videos/<uuid>.mp4` | 신규 (생성물) | 캐시 디렉터리. 1개당 ~수백 KB 예상 |
| 3 | `kadap-poc-v2/main.py` `tab_closedloop` + `closedloop_load` | 수정 | rollout view dict에 `composite_url` 필드 추가 |
| 4 | `kadap-poc-v2/main.py` StaticFiles mount | 수정 | `/closedloop_videos` 경로로 정적 mp4 서빙 |
| 5 | `kadap-poc-v2/templates/_closedloop_loaded.html` | 수정 | rollout 선택 패널 최상단에 video 임베드 (`controls`, `max-width: 640px`, 영상 없으면 안내 div) |

## 5. 영상 사양

- **포맷**: H.264 mp4, 2 fps × 15 frames = 7.5초 (Tab ② composite와 동일 패턴)
- **해상도**: front_wide 120fov 원본 비율 유지 (~1304×800 예상, 인코딩 시 짝수 맞춤)
- **오버레이** (matplotlib + PIL, Tab ② `make_video_nav.py`의 폰트/색감 재사용):
  - 상단 좌측: `[V2X] Turn left in 11m` (배너, 노란색 배경) — ASL rollout 메타에서 추출
  - 우측 상단: `step k/N · t=2.4s` (t는 frame 타임스탬프를 step 0 기준 상대 초로 환산)
  - 하단 자막 영역: AI reasoning — `step.chain_of_thought` 1순위, 없으면 `step.msg` 첫 줄, 둘 다 없으면 빈 자막 (영상 자체는 생성)
  - 하단 우측: `ADE x.xxm | FDE y.yym` — rollout 전체 메트릭 (step별로 변하지 않고 모든 프레임에 동일 표기)
- **폰트**: Noto Sans CJK JP (한글 가능, vlm_qa.py와 동일)

## 6. 데이터 흐름

1. 평가위원이 Tab ⑥ 진입 → 기존 rollout 드롭다운 표출
2. UUID 선택 → htmx `GET /closedloop/load?uuid=<uuid>`
3. `closedloop_load` 응답 HTML에 video 임베드 포함:
   - `composite_url = f"/closedloop_videos/{uuid}.mp4"` 가 캐시에 존재하면 표출
   - 없으면 안내 div + 기존 trace/Plotly만 표출 (퇴화 동작)
4. 브라우저가 mp4 fetch, native `<video controls>` 재생

## 7. 영상 사전 생성 절차

`scripts/render_closedloop_videos.py` 단일 진입점:

```
for rollout in existing_rollouts():
    if cached_mp4(rollout) exists and not --force: continue
    ensure_frames_extracted(rollout)         # ASL → JPEG, 이미 있으면 skip
    meta = parse_asl_meta(rollout)           # V2X text, ADE/FDE, step CoT 리스트
    frames = sorted(jpg paths in camera_front_wide_120fov/)
    for frame_path, step_meta in zip(frames, meta.steps):
        render_overlay(frame_path, step_meta) → /tmp/...png
    ffmpeg /tmp pngs → closedloop_videos/<uuid>.mp4 (2fps, libx264, yuv420p)
```

- 운영자는 신규 rollout 추가 후 1회 실행
- 예상 시간: rollout당 ~35s (frames 추출 20s + parse 5s + 렌더+ffmpeg 10s) × 8 = ~5분

## 8. 에러 처리

| 상황 | 동작 |
|---|---|
| 영상 파일 부재 | UI에 "영상 미생성. `scripts/render_closedloop_videos.py` 실행" 안내. 기존 trace/Plotly는 그대로 표출 |
| ffmpeg 미설치 / 실패 | 해당 rollout만 skip, 로그 출력, 다음 rollout 진행 |
| frame 추출 실패 | rollout skip, 로그에 사유 |
| ASL parse 실패 | V2X text/메트릭/CoT을 "(unknown)"으로 표기하고 영상은 생성 |

UI는 절대 빈 화면을 보이지 않음 — 기존 trace/Plotly 섹션은 항상 fallback.

## 9. 테스트

1. **Dry-run**: 단일 rollout (`2233cbf6`, 이미 frames_jpeg 추출됨)으로 render 스크립트 검증
   - `closedloop_videos/2233cbf6-...mp4` 생성 확인
   - 7.5초, 1304×800, H.264, 오버레이 한글 정상 표출
   - Tab ⑥에서 rollout 선택 시 video 재생 확인
2. **Batch**: 8개 전체 일괄 렌더 → 5분 이내 완료, 모두 mp4 산출
3. **Fallback**: closedloop_videos 디렉터리 비우고 Tab ⑥ 동작 확인 → 안내 div만 표출, trace/Plotly 정상

## 10. 범위

### 포함
- 신규 스크립트 1개, main.py 수정 (StaticFiles mount + view dict 1필드), 템플릿 1개 수정
- 8개 rollout 사전 영상화 1회 실행
- 시연 검증 (1 rollout end-to-end + 1 비-원본 spot check)

### 제외
- 멀티 카메라 그리드 표출
- step별 인터랙티브 jump (기존 slider 유지)
- 영상 다운로드 버튼 (브라우저 video controls의 우클릭으로 충분)
- 실시간 rollout 자동 영상화 daemon (운영 복잡도 증가, POC 범위 밖)
- nav_demo_samples 카테고리 등 시나리오 메타와의 연동 (rollout은 별도 scenario_id 체계)

## 11. 소요 추정

| 항목 | 시간 |
|---|---|
| 스크립트 작성 + dry-run | ~25분 |
| main.py / 템플릿 수정 + 검증 | ~15분 |
| 8개 batch 렌더 | ~5분 |
| commit + push | ~3분 |
| **합계** | **~50분** |

폐루프 시뮬 신규 rollout (~40분 남음) 완료 전에 코드/스크립트 작업 끝내고, 시뮬 완료
즉시 8개 batch 실행 → 즉시 시연 검증 가능.
