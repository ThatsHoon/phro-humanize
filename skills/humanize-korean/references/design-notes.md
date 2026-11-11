# Humanize Korean — 설계 근거·버전 히스토리 (design-notes)

> SKILL.md에서 이관된 설계 근거 — **실행 규칙은 SKILL.md 참조.** 이 파일은
> 스킬 발동 시 로드되지 않는다. 규칙을 되돌리려는 기여자가 "왜 이렇게
> 됐는가"를 확인하는 용도다.

## 버전 히스토리 (상세)

- **v1.5 (2026-04-26)** — v1.1 5인 파이프라인 위에 단일 호출 `humanize-monolith` fast path 신설. voice profile·candidate pool·권한 위계 §1~§6은 핫패스 비용 문제로 삭제.
- **v1.6 (2026-05-07)** — KatFish·LREAD 기반 정량 점수 레이어 도입. `scripts/prepare_monolith_input.py`(입력 shim)가 monolith 호출 *전* 외부 사전 처리로 점수를 산출해 결합 입력 파일에 prepend.
- **v1.6.1 (2026-05-07)** — fast 산출물을 `final.md` 1개로 통합(본문 끝 `<!-- HUMANIZE-SUMMARY -->` HTML 주석 블록). monolith 도구 호출 캡 4회 → **3회**.
- **v2.0 (2026-05-07)** — 한국 번역학계 8유형 + post-editese metric 트랙(`metrics_v2.py`) 흡수. 분류 체계 본진 v2.0(활성 패턴 70건 + A-17 hold 1건).
- **v2.0.1** — 패치 릴리스: shim 실행 절차 명문화, 실사용 백포트(격식 상향 금지·구조/각주 보존·과윤문 게이트 코드화), quick-rules 빌드 생성.
- **v2.1.0** — 정밀 모드를 5인 파이프라인 → **3콜 구조**(진단→겨냥 윤문→finalize)로 재편. 옛 4종+web-architect 은퇴. 8,000자 strict 자동 승급 폐지.
- **v2.2.0** — **경량 경로 재설계.** shim이 산출하는 `route_hint`(light|standard|heavy)로 디폴트 경로를 3단 분기. **단일 콜 우선 원칙** 명문화 — 1만자급도 청킹 없이 단일 콜(실측: 청킹 7콜 610K 토큰 → 단일 콜 134K, 품질 동등). 청킹은 shim이 실제로 청크를 2개 이상 만들 때만. finalize는 heavy·의심·사용자 요청 시로 한정.
- **v2.3.0** — **효율화 릴리스.** ① Tier 1 구조 수렴 게이트(`verify_gates.py` 4축: 문자율 + 진단 목표달성 z 수렴 + C-8 대구 전멸 + golden/수치) — 문자 change_rate가 못 보는 구조 편집(쉼표·대구 해체)을 결정적으로 검증, LLM 콜 0. ② 진단 입력을 taxonomy 전량(74.8KB) → `diagnosis-rules.md` 슬림 인덱스(~13KB, 빌드 생성)로 교체, 진단 콜 토큰 35~50%↓. 실측 회귀에서 하중 패턴(C-8·C-11·E-5·D-7) 지목 동등.

## 설계 노트 — 단일 콜 우선 (v2.2 실측 근거)

**1만자 글 실측**: 정밀 청킹 경로(7콜) = **610K 토큰**. 같은 입력 단일 콜 = **134K 토큰**(4.5배 절감), 품질 동등. 폭발 원인은 청크 콜마다 룰북·진단·시스템 프롬프트를 재로드한 것 — 절감은 모델 교체가 아니라 **콜 수 축소**에서 온다. 요즘 모델은 1만자를 단일 콜로 무리 없이 처리하므로, 청킹은 "shim이 실제로 쪼갤 수밖에 없는 초장문"의 예외 경로다.

또 하나의 실증: 어휘 티 0·구조 티만 있는 잘 쓴 글에도 최중량 파이프라인을 돌리고 있었다. v2.2의 route_hint 분기가 이를 차단한다.

(v2.1까지의 "왜 5인에서 3콜로" 배경: 옛 5인 파이프라인은 detector span 열거가 0↔18개로 요동쳐 불안정했고, 587줄 taxonomy를 이중 로드해 탐지에만 wall-clock 54%를 썼다. 웹앱 실증에서 "지배 패턴 진단 1콜 + 결정적 지표 수렴"이 동급 품질을 냈고, 3콜 구조는 그 이식이다. v2.2는 같은 원리를 한 단계 더 밀어 진단·finalize조차 필요할 때만 쓰게 했다.)

## 설계 노트 — 진단 슬림 인덱스 (v2.3)

진단(humanize-diagnostician)의 핸드오프 계약은 "정확한 본진 ID + 지배도 판단"이다. taxonomy 전량(74.8KB)의 대부분은 예문·처방·학술 인용·버전주석 — 진단에 불필요. `scripts/build_diagnosis_rules.py`가 SSOT에서 전 패턴 전수(ID·정의·탐지 시그니처)를 ~13KB로 결정적 생성한다(83% 절감). quick-rules로 대체할 수 없는 이유: 진단은 문서 레벨 패턴(C-8 대구·E-1 리듬·D-6 결말공식 등 quick:false 다수)을 반드시 봐야 한다. drift는 CI `--check`가 차단.

## 테스트 시나리오

### Light — 잘 쓴 글
- 입력: 사람이 쓴 칼럼 또는 어휘 티 없는 글 (route_hint=light)
- 기대: monolith 1콜(보수), 변경률 5% 미만, "이미 좋습니다 + 손댄 곳 요약" 보고. 진단·finalize 콜 0

### Standard — 보통의 AI 초안
- 입력: ChatGPT가 생성한 AI 칼럼 초안 (2,000~10,000자, route_hint=standard)
- 기대: 진단 1콜 + 윤문 1콜 = 2콜, **1만자도 청킹 없음**, 변경률 15~25%, 등급 A/B, finalize 생략

### Heavy — 중증·증적 필요
- `--strict` 명시 또는 route_hint=heavy
- 기대: 진단→윤문→finalize 3콜. 변경률 11~22%, `09_finalize.json` verdict=accept/corrected

### 초장문 — 청킹은 shim의 결정
- heavy + shim 청킹 임계 초과 입력 → `--chunk` 실행, manifest body 청크 2+개일 때만 병렬. 청크가 1개로 나오면 단일 콜. 손실 없는 분할 + 헤딩 승격 + 각주 passthrough

### 엣지 케이스 — route_hint 부재
- 구버전 shim·metrics 실패(`00_metrics.error`) → standard 경로로 진행. 게이트는 항상 실행

## 런타임 에이전트 도구 범위 · 결정적 단계 런처

- 런타임 3종(monolith·diagnostician·finalizer) frontmatter에 `tools`(diagnostician `Read, Write` / monolith·finalizer `Read, Write, Edit`)·`omitClaudeMd: true`·`maxTurns`를 둔다. 세 에이전트는 파일 읽기·쓰기만 하므로, 도구를 생략해 MCP·Bash 등 전 도구 정의를 상속하거나 사용자 CLAUDE.md를 싣는 것은 콜마다 낭비다. 실측(2.8K자 light): 서브에이전트 1콜의 고정 컨텍스트 35,167 → 8,301토큰.
- monolith·finalizer에서 `Edit`를 빼면 안 된다. 쓴 뒤 몇 군데를 고칠 때 `Write`밖에 없으면 파일 전체를 다시 출력한다. 같은 실측에서 4.6K자 `final.md`를 세 번 통째로 다시 써 출력 토큰이 13.7K → 26.0K로 늘었다.
- 그래서 백업은 에이전트가 하지 않는다. `scripts/humanize_run.py`가 맡는다 — `prepare`는 기존 `final.md`를 `final_prev.md`로, `finish`는 게이트 exit 1·`--pre-finalize`일 때 `final_pre_finalize.md`로, exit 2일 때 `final_prev.md`로 복사한다. 게이트 밖 사유의 finalize 승급은 `snapshot`.
- 같은 런처가 Phase 1(TAG·run 할당·입력 저장·shim·route_hint)과 Phase 2.4~2.5(서법 복원·쉼표 제거·게이트)를 각각 Bash 1회로 묶는다. 단계마다 도구를 따로 부르면 왕복마다 메인 세션 컨텍스트 전체가 다시 읽힌다. 판정 로직은 기존 스크립트 그대로다.
- 파일 입력은 `--input-file`로 넘긴다. 본문을 Read→Write로 옮기면 같은 본문이 입력 토큰으로 한 번, 출력 토큰으로 또 한 번 나간다.

## 청크 출력과 summary 블록

- 청크 출력에는 `<!-- HUMANIZE-SUMMARY -->` 블록을 넣지 않는다. 요약은 finalizer가 재조립본 끝에 하나 만든다(Codex 역할 계약과 같은 규칙).
- 실측(22K자 리포트, 12청크): 오케스트레이터가 청크마다 블록을 달게 해 재조립본에 블록 7개가 끼었다(길이비 1.399). 게이트·서법 복원은 첫 블록부터 파일 끝까지를 메타로 보고 자르므로 본문 2,886자만 비교됐고, 문자율 77%로 ABORT가 났다. 오케스트레이터가 원인을 찾아 다시 조립하느라 메인 턴이 늘었다.
- 그래서 두 겹으로 막는다. `reassemble_chunks.py`는 청크 결과의 블록을 떼고 조립한다(리포트 `notes`·`summary_blocks_dropped`). `verify_gates.py`는 블록 뒤에 본문이 남아 있으면 잘린 본문을 재지 않고 exit 3으로 알린다.

## 시도했다가 되돌린 것: 자투리 청크 병합

- 헤딩 강제 컷 때문에 22K자 리포트가 `[75, 2859, 6888, 1534, 305, 803, 4188, 3014, 929, 17, 18, 1484]`자 12청크(monolith 7콜)로 쪼개졌다. 이웃 청크를 7,000자 이하로 합쳐 4청크(4콜)로 줄여 봤다.
- 실측(n=1): 비용 $3.73 → $3.69, 시간 차이 없음. 병렬 청크 콜은 앞부분 프리픽스를 캐시로 공유해, 콜이 하나 늘어도 대부분 싼 캐시 읽기만 는다. 캐시 쓰기는 콜 수가 아니라 본문 분량을 따른다(monolith 캐시 쓰기 134K → 149K).
- 헤딩 보존은 15/15로 문제없었지만, 무결성 가드를 풀 만한 이득이 없어 되돌렸다. 청크 비용을 줄이려면 콜 수가 아니라 콜 안의 턴 수와 출력 분량을 줄여야 한다.

## monolith에 진단 파일을 따로 넘기지 않는다

- standard·heavy의 monolith 입력(`01_input_with_metrics.txt`·`01_chunk_NN_input_with_metrics.txt`)에는 shim `--diagnosis`가 진단을 이미 결합해 둔다.
- 오케스트레이터가 `diagnosis_path`까지 넘기면 monolith가 진단을 한 번 더 Read하고 턴이 하나 는다. 위 병합 실측에서 4콜 중 3콜이 그랬다(본문 전체를 한 번 더 캐시로 읽는다).

## 에이전트 계보 (은퇴·개발용)

**개발용 1회성 5종 (릴리스 회차 전용 — 런타임 미로드, 위치 `agents-dev/`)**
- `translationese-research-distiller` · `korean-translation-scholar` · `taxonomy-gap-analyzer` · `post-editese-metric-engineer` · `quick-rules-integrator` — v2.0 학술 흡수 회차에서 사용된 개발 도구. 윤문 실행과 무관

> v2.1에서 옛 정밀(strict) 파이프라인 4종(`ai-tell-detector`·`korean-style-rewriter`·`content-fidelity-auditor`·`naturalness-reviewer`)과 미사용 `humanize-web-architect`를 은퇴시켰다. 진단·윤문·finalize 3콜이 이들을 대체한다.
