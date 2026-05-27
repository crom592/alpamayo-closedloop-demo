# KADaP Alpamayo PoC (한자연 납품용 자율주행 테스트베드)

한국자동차연구원(KATRI) PoC용 인터랙티브 closed-loop 시뮬레이션 UI.
NVIDIA Alpamayo 1.5 + Alpasim + NRE를 KADaP A40 노드에서 daemon 모드로
띄우고, Gradio 프론트엔드에서 시나리오·정책을 선택해 실행한다.

## 구조

- `client.py` — `RuntimeService.simulate` gRPC 클라이언트 (호스트 :50051)
- `app.py` — Gradio UI (탭 ① 시나리오 평가 v0; ② ~ ④ 단계적 추가)

## 사전 조건

1. `scripts/run_closedloop.sh` 가 한 번 돌아 docker-compose.yaml 가 생성된 상태
2. `scripts/patch_compose_for_daemon.py` 적용 — `runtime-0` 에 `--serve` 플래그와
   호스트 포트 50051 노출, 모든 서비스에 HF 토큰 / xet·kernel 우회 환경 변수,
   `endpoints.startup_timeout_s = 1800` 주입
3. `docker compose up -d` 후 ~10분 (driver-0 가 Alpamayo 1.5 10B + Cosmos VLM
   적재 — GPU 약 22 GB)

## 실행

호스트 alpasim venv 를 그대로 재활용 (alpasim_grpc, gradio, reportlab 포함):

```bash
bash scripts/run_kadap_poc.sh         # daemon ready 검증 후 Gradio 띄움
# 또는 직접:
./alpasim/.venv/bin/python kadap-poc/app.py
```

기본 포트 7870. `KADAP_POC_PORT=7860 ./.venv/bin/python kadap-poc/app.py` 식으로
오버라이드 가능. KADaP 외부 노출 포트는 콘솔에서 매핑.

## v0 한계

- 시나리오 1종 (`clipgt-01d503d4-...`) — Task #15 에서 NRE artifact 추가 풀링
- 정책 전환은 `compose down/up` 필요 (단일 A40에 모델 22 GB × 1 만 적재 가능)
- 메트릭은 `aggregated_metrics` 만 표시 — timestep_metrics 시계열은 Task #12
- PDF 리포트 export 는 Task #14
