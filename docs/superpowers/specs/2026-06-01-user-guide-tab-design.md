# 📖 사용 가이드 탭 — 설계 문서

- **작성**: 2026-06-01
- **대상 시스템**: KATECH PoC 데모 (`kadap-poc-v2`)
- **트리거**: 평가위원이 처음 접속해 7개 탭의 평가 흐름을 즉시 이해하지 못하는
  문제 해결. 시연 자리에서 운영자 개입 없이 평가위원 단독으로 진행 가능한 수준의
  상세 가이드 제공.

## 1. 목표

새 탭 `📖 사용 가이드`를 nav 맨 앞에 추가, 첫 접속 시 자동 표출. 각 평가 탭(①~⑥)
의 목적·사용 절차·결과 해석·자주 묻는 질문을 캡처 스크린샷과 함께 한 페이지에
정리. 캡처는 Playwright Python으로 실제 UI를 자동 캡처해 100% 일치 보장.

## 2. 비목표

- 운영자용 매뉴얼 (모델 적재 절차, 캐시 갱신, 시뮬 재실행) — 별도 README 또는
  ⓘ 시스템 탭의 향후 확장으로 분리
- 동영상 튜토리얼 — PNG 캡처로 충분
- 다국어 — 한국어만 (KATECH 평가 대상)
- 인쇄용 PDF — 브라우저 인쇄로 충분

## 3. 위치 & 라벨

- nav 순서: `📖 사용 가이드 | ① 시나리오 평가 | ② 시연 자동 실행 | ③ 실시간
  인터랙티브 | ④ VQA | ⑤ 카메라 입력 개수 | ⑥ NRE Closed-Loop | ⓘ 시스템`
- `📖 사용 가이드`는 번호 없음 — 평가 흐름의 일부가 아닌 navigation aid
- `base.html`의 `hx-trigger="load"` 기본값을 `/tab/guide`로 변경 → 첫 접속 시
  자동 표출

## 4. 콘텐츠 구조

단일 페이지 + 좌측 sticky 목차 (8개 섹션). 모든 섹션은 동일 패턴.

```
┌──────────────────────────────────────────────┐
│ 좌측 sticky 목차       │ 본문 (앵커 스크롤)     │
│ ───────────────────  │ ───────────────────  │
│ 1. 시작하기          │ # 1. 시작하기          │
│ 2. 시나리오 평가     │   서비스 개요, 평가 흐름 │
│ 3. 시연 자동 실행    │ # 2. 시나리오 평가     │
│ 4. 실시간 인터랙티브 │   [캡처1] 초기 상태    │
│ 5. VQA              │   [캡처2] 모델 적재 후 │
│ 6. 카메라 개수       │   목적/단계/해석/FAQ  │
│ 7. Closed-Loop      │ ...                  │
│ 8. 트러블슈팅        │                      │
└──────────────────────────────────────────────┘
```

### 4.1 섹션 1: 시작하기
- 서비스 개요 (한국형 V2X 자율주행 평가 플랫폼, Alpamayo 1.5 + Cosmos-Reason2)
- 평가 흐름 권장 순서: ① 단건 평가 → ② 시연 자동 → ③ 실시간 인터랙티브 → ④ VQA →
  ⑤ 카메라 개수 → ⑥ Closed-Loop
- 사전 준비: ① 탭에서 모델 적재 (~1분)
- 캡처 1장: 첫 화면 (nav + landing)

### 4.2 섹션 2~7: 평가 탭 6개 (탭당 동일 구조)
각 섹션:
- **목적** — 평가위원이 이 탭에서 무엇을 평가하는지 1단락 (3~5줄)
- **캡처** — 2~3장 (초기 상태 / 입력 중 / 결과 표출)
- **사용 절차** — `<ol>` 단계 (3~6 step)
- **결과 해석** — 메트릭/수치 의미 (예: ADE < 1.0m 양호, 1.0~2.0m 보통, > 2.0m
  주의 필요)
- **자주 묻는 질문 (FAQ)** — 1~3개 (탭별 특이사항)

### 4.3 섹션 8: 트러블슈팅 (평가위원 자가 해결 범위)
- "모델이 적재되지 않았습니다" → ① 탭 모델 적재 버튼 안내
- VQA 응답이 `[0.3, 0.5, ...]` 좌표만 → dual-mode 동작 설명
- ⑥ rollout 선택 시 "영상 미생성" → 사전 렌더 누락, 운영자 호출
- Tab ② 영상 로드 안 됨 → 페이지 새로고침
- ② 카메라 영상 첫 프레임만 길게 멈춤 → 시뮬레이션 데이터 짧을 때 정상

운영자용 트러블슈팅(컨테이너 재시작, 캐시 갱신, 시뮬 재실행)은 범위 밖.

## 5. 캡처 자동화 — Playwright Python

### 5.1 환경
- 신규 venv: `scripts/manual_capture/.venv` (alpasim venv 오염 방지)
- 의존성: `playwright` (Python 패키지 + chromium 바이너리)
- `playwright install chromium` 1회 실행 필요

### 5.2 캡처 스크립트
`scripts/manual_capture/capture.py`:
- 대상 URL 인자: 기본 `http://localhost:7861`
- 출력 디렉터리: `kadap-poc-v2/static/manual/screenshots/`
- 해상도: 1440×900 viewport
- 각 탭의 sub-state별 캡처 정의 (코드 상수 리스트)
- `--force` 플래그로 전체 재캡처, 미지정 시 누락된 것만 추가
- 모델 적재가 필요한 캡처는 startup에서 `/scenario_eval/load_model` POST 후
  적재 완료 (state-ready 폴링) → 캡처 수행

### 5.3 캡처 목록 (~20장 예상)
| 탭 | 상태 | 파일명 |
|---|---|---|
| landing | 첫 화면 | `landing.png` |
| ① 시나리오 평가 | 모델 적재 전 | `01_scenario_eval_initial.png` |
| ① 시나리오 평가 | 시나리오 선택 + V2X preset | `01_scenario_eval_input.png` |
| ① 시나리오 평가 | 결과 (BEV + 메트릭) | `01_scenario_eval_result.png` |
| ② 시연 자동 실행 | 갤러리 | `02_demo_run_gallery.png` |
| ② 시연 자동 실행 | 영상 재생 중 | `02_demo_run_playing.png` |
| ③ 실시간 인터랙티브 | 초기 | `03_interactive_initial.png` |
| ③ 실시간 인터랙티브 | V2X preset 전환 | `03_interactive_preset.png` |
| ④ VQA | 시나리오 선택 | `04_vqa_initial.png` |
| ④ VQA | 라이브 질문 입력 | `04_vqa_question.png` |
| ④ VQA | 응답 표출 | `04_vqa_answer.png` |
| ⑤ 카메라 개수 | 초기 | `05_cam_count_initial.png` |
| ⑤ 카메라 개수 | 결과 | `05_cam_count_result.png` |
| ⑥ Closed-Loop | rollout 선택 | `06_closedloop_initial.png` |
| ⑥ Closed-Loop | 영상 + 메트릭 | `06_closedloop_loaded.png` |
| ⓘ 시스템 | 전체 | `info_system.png` |

총 16장. PNG, 1440×900, 압축 후 ~100-300KB/장 = 합계 ~3-5MB.

### 5.4 파일 저장
- `kadap-poc-v2/static/manual/screenshots/*.png` — 정적 파일, git 추적 (PNG 캡처는
  콘텐츠의 일부)
- 갱신 시 git diff에서 변경된 PNG만 commit

## 6. 가이드 페이지 UI

### 6.1 레이아웃
- 좌측: sticky 목차 (`position: sticky; top: 0`), 너비 200px
- 우측: 본문, max-width 900px, 좌측 마진 230px
- 모바일/좁은 화면: 목차가 상단으로 fallback (CSS media query)

### 6.2 섹션 마크업
```html
<section id="guide-2" class="guide-section">
  <h2>② 시나리오 단건 평가</h2>
  <p class="guide-purpose">목적: ...</p>
  <figure>
    <img src="/static/manual/screenshots/01_scenario_eval_initial.png" alt="...">
    <figcaption>초기 상태</figcaption>
  </figure>
  <h3>사용 절차</h3>
  <ol>
    <li>시나리오 드롭다운에서 평가 대상 선택</li>
    ...
  </ol>
  <h3>결과 해석</h3>
  <ul>
    <li>ADE (Average Displacement Error): 예측 궤적과 실제 GT 궤적의 평균 거리.
        1.0m 미만이면 양호.</li>
    ...
  </ul>
  <h3>자주 묻는 질문</h3>
  <dl>
    <dt>Q. ...</dt><dd>A. ...</dd>
  </dl>
</section>
```

### 6.3 스타일 (app.css 추가)
- `.guide-toc` — sticky 목차
- `.guide-section` — 섹션 카드 (여백 / 구분선)
- `.guide-screenshot` — 캡처 이미지 (max-width 100% / border / box-shadow)
- `.guide-purpose` — 목적 단락 강조 (배경색)

## 7. 데이터 흐름

1. 평가위원 첫 접속 → `base.html` 로드 → `hx-trigger="load"`가 `/tab/guide` 호출
2. `/tab/guide` → `tab_guide.html` 렌더 → 정적 PNG들 `<img>` 로드
3. 좌측 목차의 앵커 링크 클릭 → 우측 본문 해당 섹션으로 스크롤

## 8. 에러 처리

- 캡처 PNG 부재 → `<img>` 깨진 아이콘 표출 → 본문 텍스트는 정상 노출 (퇴화 동작)
- Playwright 캡처 실패 → 스크립트가 어느 캡처 실패인지 stderr 출력, 나머지는 진행
- 시연 자리에서 캡처가 깨져 있으면 운영자가 `scripts/manual_capture/capture.py
  --force` 재실행

## 9. 파일 변경 / 신규

| 파일 | 변경 |
|---|---|
| `kadap-poc-v2/main.py` | `/tab/guide` 엔드포인트 추가 |
| `kadap-poc-v2/templates/base.html` | nav 맨 앞에 `📖 사용 가이드` 추가, `hx-trigger="load"` 기본값 `/tab/guide`로 변경 |
| `kadap-poc-v2/templates/tab_guide.html` | 신규 — 단일 페이지 + sticky toc + 8 섹션 |
| `kadap-poc-v2/static/app.css` | `.guide-toc` / `.guide-section` / `.guide-screenshot` / `.guide-purpose` 스타일 추가 |
| `kadap-poc-v2/static/manual/screenshots/*.png` | 신규 — Playwright 캡처물 (~16장) |
| `scripts/manual_capture/capture.py` | 신규 — Playwright Python 자동화 |
| `scripts/manual_capture/requirements.txt` | 신규 — `playwright` |

## 10. 테스트

1. **Playwright dry-run**: 단일 탭(landing) 캡처만 먼저 검증 → 1440×900 PNG 정상
2. **전체 캡처**: ~16장 자동 일괄, 모두 정상 생성
3. **가이드 페이지 렌더**: uvicorn 재시작 후 `/` 접속 → 가이드 탭 자동 표출 + 모든
   캡처 200 OK
4. **앵커 스크롤**: 좌측 목차 클릭 시 우측 본문 해당 섹션으로 이동
5. **퇴화 동작**: 캡처 파일 1장 삭제 후 페이지 로드 → 깨진 이미지만 표출, 나머지
   콘텐츠 정상

## 11. 범위

### 포함
- `📖 사용 가이드` 탭 1개 신규 (8 섹션, ~16-20 캡처)
- Playwright Python venv + 자동 캡처 스크립트
- 첫 접속 시 가이드 자동 표출
- 시연 검증 (모든 캡처 + 앵커 + 퇴화 동작)

### 제외
- 운영자용 매뉴얼 (모델 적재, 캐시 갱신, 시뮬 재실행) — README/별도 작업
- 동영상 튜토리얼
- 다국어
- 인쇄용 PDF
- 가이드 탭 내 검색 기능
- 가이드 콘텐츠 다국어/번역
- A/B 변형 (예: 평가위원 ID별 가이드 분기)

## 12. 소요 추정

| 작업 | 시간 |
|---|---|
| Playwright venv + 캡처 스크립트 작성 + 1탭 dry-run | ~25분 |
| 모델 적재 후 전체 ~16장 일괄 캡처 | ~10분 (모델 적재 ~1분 + 캡처 ~1분 × 탭 + I/O) |
| `tab_guide.html` 콘텐츠 작성 (8 섹션) | ~45분 |
| `app.css` 스타일 + nav 변경 + 엔드포인트 | ~15분 |
| 시각 검증 + commit + push | ~10분 |
| **합계** | **~105분 (~1시간 45분)** |
