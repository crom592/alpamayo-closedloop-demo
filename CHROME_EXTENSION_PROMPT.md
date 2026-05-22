# Chrome Claude 확장프로그램용 자동화 지시서

이 파일의 두 블록(`PROMPT A`, `PROMPT B`)을 Chrome 의 Claude 확장프로그램에 그대로 붙여넣으면, 확장이 브라우저 탭을 조종해서 GitHub 리포 생성 + KADaP 서버 구축 + 데모 기동까지 진행합니다.

## 사용자 선행 조건 (확장이 못 함)

1. **GitHub Personal Access Token** — github.com → Settings → Developer settings → Fine-grained PAT 발급 (scope: `repo` on `crom592/*`). 손에 들고 있을 것.
2. **AhnLab TrustGuard SSL VPN** — 데스크탑 앱 설치 + vpn.bigdata-car.kr:3443 접속. KADaP 작업 시작 전 필수.
3. **HuggingFace 토큰** — `nvidia/Alpamayo-1.5-10B`에 read 권한 있는 fine-grained 토큰. 손에 들고 있을 것.
4. **KADaP 포털 계정** — `cloud.bigdata-car.kr` 로그인 가능 + 프로젝트 책임자 권한 (프로젝트 생성 시 필요).

---

## PROMPT A — GitHub 리포 생성 (VPN 불필요)

> 너는 내 Chrome 탭을 조종해서 `crom592` GitHub 계정 아래에 closed-loop 데모용 리포를 만든다. 각 클릭/입력 후 스크린샷 찍고, UI가 내가 설명한 것과 다르면 멈추고 물어봐.
>
> 1. `https://github.com/login` 에 접속. 로그인 안 되어 있으면 멈추고 내가 로그인할 때까지 기다린 후 진행.
> 2. `https://github.com/NVlabs/alpamayo1.5` 접속 → 우상단 **Fork** 클릭 → Owner를 `crom592` 선택 → **Create fork**. fork 완료 페이지 URL을 기록.
> 3. `https://github.com/NVlabs/alpasim` 접속 → 동일하게 **Fork** → Owner `crom592` → **Create fork**. fork URL 기록.
> 4. `https://github.com/new` 접속:
>    - Owner: `crom592`
>    - Repository name: `alpamayo-closedloop-demo`
>    - Description: `Alpamayo 1.5 + Alpasim NRE closed-loop demo for KADaP cloud`
>    - Public 선택, 다른 옵션(README/.gitignore/LICENSE) **모두 체크 해제** (로컬에서 푸시할 것이므로)
>    - **Create repository** 클릭
> 5. 생성된 리포 페이지의 HTTPS 클론 URL을 기록해서 알려줘 (예: `https://github.com/crom592/alpamayo-closedloop-demo.git`).
> 6. 사용자가 손에 들고 있는 PAT을 받으면, 페이지에 표시된 "push existing repo" 명령들 중 `git remote add origin ...`와 `git push -u origin main` 두 줄을 정확히 인용해서 보고. (나는 그 명령들을 로컬 머신에서 실행할 거야 — 너는 실행하지 않아.)
>
> 작업 후 보고: fork 두 개의 URL, 메타-리포 URL, push 명령 두 줄.

---

## PROMPT B — KADaP 서버 구축 + 데모 기동 (VPN 연결 후)

> 너는 내 Chrome 탭을 조종해서 KADaP 자동차산업클라우드(`cloud.bigdata-car.kr`)에 GPU 서버를 만들고 Alpamayo closed-loop 데모를 띄운다. AhnLab TrustGuard VPN은 내가 미리 연결해놓는다. 각 단계 후 스크린샷 찍고, 폼 필드 이름이 내가 설명한 것과 다르면 멈추고 물어봐. 절대 임의로 폼을 채워서 제출하지 마.
>
> ### 1. 로그인 + 프로젝트 진입
> 1. `https://cloud.bigdata-car.kr` 접속. 로그인 페이지가 나오면 멈추고 내가 ID/비밀번호 칠 때까지 대기.
> 2. 좌측 메뉴 **프로젝트** 클릭 → 프로젝트 목록에서 `alpamayo-demo` 있으면 클릭. 없으면 **프로젝트 생성** → 프로젝트명 `alpamayo-demo` 입력 → **프로젝트 생성** → 목록에서 클릭해 진입.
>
> ### 2. 자원 쿼터 확인 (GO/NO-GO 게이트)
> 3. 좌측 메뉴 **프로젝트 자원** 탭 클릭. 화면에 표시된 가용 자원을 보고해:
>    - vCPU 잔여, 메모리 잔여, 저장공간 잔여
>    - **GPU**: 개수, 메모리, 모델명 (L40S / A100 / H100 / RTX / 기타)
> 4. 만약 가용 **GPU 메모리 < 24 GB** 이거나 **저장공간 잔여 < 350 GB** 이면 **여기서 멈춰**. 사용자한테 "쿼터 부족 — admin@bigdata-car.kr 로 증설 요청 필요. 진행할까?" 라고 물어봐. 사용자가 OK 하기 전까지 다음 단계 진행하지 마.
>
> ### 3. GPU 서버 생성
> 5. 좌측 메뉴 **서버 가상화 → 서버 관리** 클릭 → **서버 만들기** 클릭. 폼에 정확히 다음 값으로 채워:
>    - **서버 이름**: `alpamayo-closedloop`
>    - **OS 선택**: Linux 카테고리 → **Ubuntu 22.04** 이미지 중에서 **DevTools** 표시(망치 아이콘)와 **GPU** 표시(GPU 아이콘) 둘 다 있는 옵션. Docker/NVIDIA Container Toolkit이 미리 설치된 이미지여야 함. 후보가 여러 개면 가장 최신 빌드 선택.
>    - **사양 선택**: GPU 개수 = **1**, GPU 메모리 = 가용 옵션 중 **≥ 24 GB 인 가장 작은 옵션** (L40S 48GB 또는 A100 40GB 우선, H100 80GB 가능하면 좋음). CPU/메모리는 기본값.
>    - **OS 디스크**: **100 GB**
>    - **디스크 추가**: 추가 디스크 한 개, 크기 **200 GB** (마운트는 자동 또는 KADaP UI가 시키는 대로)
> 6. 서버 생성 정보 요약 패널에서 값들이 맞는지 다시 한번 보고. 내가 OK 하면 **서버 생성** 클릭.
> 7. 서버 목록으로 돌아가서 30초마다 새로고침. 카드의 상태가 **활성**으로 바뀔 때까지 대기 (예상 5~15분).
>
> ### 4. 포트포워딩 설정
> 8. 서버 카드의 `⋮` 메뉴 → **포트포워딩** 클릭. 포트 추가:
>    - **포트번호**: `7860`
>    - **웹서비스**: **YES**
>    - **프로토콜**: TCP+SSL (웹서비스 YES 선택 시 자동)
>    - **설명**: `dashboard`
> 9. **추가** → 확인. 표시되는 외부 접속 URL을 기록 (`https://<...>:7860` 같은 형식).
>
> ### 5. 웹 터미널로 데모 부트스트랩
> 10. 서버 카드의 **웹 터미널** 클릭 (또는 카드 메뉴 → 웹 콘솔(VPN) 접속). 터미널이 열리면 다음을 정확히 붙여넣고 엔터:
>     ```
>     cd /data && curl -fsSL https://raw.githubusercontent.com/crom592/alpamayo-closedloop-demo/main/scripts/kadap_bootstrap.sh | bash
>     ```
>     `.env` 파일이 만들어졌다는 메시지가 나오면 여기서 멈춰.
> 11. 사용자한테 "`HF_TOKEN` 값을 알려달라" 하고, 받으면 터미널에 다음을 정확히 입력:
>     ```
>     cd /data/alpamayo-closedloop-demo && sed -i 's|^HF_TOKEN=.*|HF_TOKEN=<여기에 토큰 붙여넣기>|' .env && grep HF_TOKEN .env
>     ```
>     출력에 `HF_TOKEN=hf_xxx...` 가 보이는지 확인 (전체 토큰은 화면에 노출 안 되게 마지막 4글자만 보고).
>
> ### 6. setup 실행 (장시간)
> 12. 터미널에 붙여넣기:
>     ```
>     bash scripts/setup.sh 2>&1 | tee setup.log
>     ```
> 13. 이후 **5분마다** `tail -50 setup.log` 를 새 터미널 탭 또는 같은 탭에서 별도 명령으로 실행해서 진행 상황 보고. 다음 메시지들이 차례로 나오는지 확인:
>     - `==> Verifying GPU` + nvidia-smi 출력
>     - `==> Installing uv`
>     - `==> Initializing git submodules`
>     - `==> Applying overlay`
>     - `==> Bootstrapping Alpasim environment` + proto 컴파일
>     - `==> Pre-pulling HuggingFace models` (가장 오래 걸림, 20~40분)
>     - `==> Setup complete.`
> 14. `Setup complete.` 가 보이지 않거나 에러가 나오면 멈추고 마지막 100줄을 보고.
>
> ### 7. closed-loop 기동
> 15. setup 완료되면 터미널에:
>     ```
>     bash scripts/run_closedloop.sh
>     ```
> 16. `docker compose ps` 출력에서 5개 서비스 — `controller-0`, `driver-0`, `physics-0`, `trafficsim-0`, `nre-0` — 가 모두 **Up (healthy)** 또는 **running** 상태가 되는지 확인. 2분간 대기 후:
>     ```
>     docker ps --format 'table {{.Names}}\t{{.Status}}'
>     ```
>     로 다시 점검. 5개 모두 running 이 안 되면 멈추고:
>     ```
>     docker compose -f /data/alpamayo-closedloop-demo/alpasim/run_dir/docker-compose.yaml logs --tail=200
>     ```
>     출력을 그대로 보고.
>
> ### 8. dashboard 기동
> 17. 5개 다 살아있으면:
>     ```
>     cd /data/alpamayo-closedloop-demo && bash scripts/run_dashboard.sh
>     ```
> 18. `docker logs --tail=50 alpamayo-dashboard` 로 Streamlit이 `:8501`에서 떴는지 확인.
> 19. 9단계에서 기록한 외부 URL을 새 탭에서 열고 스크린샷. 페이지 상단에 "🚗 Alpamayo 1.5 × Alpasim NRE — Closed-Loop Demo" 가 보이고 service health 5개 모두 🟢/🟡 표시되어야 함.
>
> ### 9. 최종 보고
> 20. 다음을 정리해서 보고:
>     - 외부 dashboard URL
>     - `docker compose ps` 마지막 출력
>     - `tail -50 setup.log` 마지막 출력
>     - dashboard 스크린샷
>     - controller-0 로그 마지막 30줄 (`docker logs --tail=30 <controller-container>`)
>     - 가장 최근 rollout MP4 파일 경로 (`ls -lat /data/alpamayo-closedloop-demo/alpasim/run_dir/rollouts | head`)

---

## 자주 발생하는 실패 + 복구

| 증상 | 원인 추정 | 복구 |
|---|---|---|
| `nvidia-smi: command not found` in setup.sh | DevTools 이미지가 아닌 일반 Ubuntu 선택됨 | 서버 삭제 후 재생성, OS 단계에서 **GPU 드라이버 포함** 이미지 선택 |
| `docker: permission denied` | 사용자가 `docker` 그룹에 없음 | `sudo usermod -aG docker $USER && newgrp docker` 후 재시도 |
| HF download 매우 느림 (>1MB/s 미만) | KADaP 외부 대역폭 제한 | `.env`에 `HF_ENDPOINT=https://<내부 미러>` 설정 (KADaP 관리자에게 미러 있는지 문의) |
| `wizard` 실행 시 USDZ 다운로드 거부 | NVIDIA 라이선스 클릭 필요 | wizard 출력의 EULA 링크 따라 수락 후 재시도 |
| `driver-0` 컨테이너 OOM | VRAM < 24 GB | `alpasim/src/wizard/configs/driver/alpamayo1_5.yaml`의 `use_classifier_free_guidance_nav: false` 확인. 그래도 OOM이면 closed-loop 포기하고 open-loop만 |
| 포트 7860에서 dashboard 안 열림 | KADaP 포트포워딩 미설정 | 4단계 다시 확인. 방화벽 등록 필요 표시 있으면 클릭 |
