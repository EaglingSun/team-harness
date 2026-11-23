# PR 검수 Agent 정답 묶음

PR 검수 Agent 가 팀 코딩 규칙(`coding-rules.md` CR-01 ~ 05)대로 지적하는지 측정하는 사례 묶음이다. 사례마다 바뀐 코드(`change.patch`)와 기대 지적(`expected.json`)이 있다. 검수 Agent 의 지시나 규칙을 고친 뒤에는 이 묶음으로 다시 측정하고, 결과를 PR 에 붙인다.

| 사례 | 바꾼 것 | 어긴 규칙 | 기대 판정 |
|---|---|---|---|
| `case-01` | 주의 기준을 숫자 리터럴로 쓴 새 함수 | CR-01 | PASS(G3) |
| `case-02` | 헤더에 선언하지 않은 새 함수를 `static` 없이 정의 | CR-02 | FAIL(G2) |
| `case-03` | 헤더의 다른 함수와 접두사가 다른 이름으로 새 공개 함수를 선언 | CR-03 | PASS(G3) |
| `case-04` | 코드가 하는 일을 다시 말하기만 하는 주석을 단 새 함수 | CR-04 | PASS(G3) |
| `case-05` | 이슈 번호 없는 TODO 를 남긴 새 함수 | CR-05 | PASS(G3) |
| `case-06` | 규칙을 모두 지킨 새 함수 | 없음 | PASS(G3) |
| `case-07` | Held-out — 고치는 동안 쓰지 않고 마지막에 한 번 잰다. `case-02` 와 같은 CR-02 의 다른 형태(함수가 아니라 파일 범위 변수 · 이름은 `s_` 로 시작) | CR-02 | FAIL(G2) |

- 판정만으로는 놓친 지적이 보이지 않는다. CR-02 만 severity `high` 라 일곱 가운데 다섯이 PASS 다. 그래서 지적 단위로 비교한다
- `case-06` 은 지적이 없어야 하는 사례다. 여기서 나온 지적은 모두 오탐이다

## 측정 · 채점 순서

통과 기준은 `eval-criteria.md`, 평가 묶음 틀은 `bundle-template.md` 다. 두 스크립트는 기준 표를 읽어 지표마다 통과 · 미달을 판정한다.

| 하는 일 | 명령 |
|---|---|
| 지금 설정으로 측정(case-01 ~ 06) | `python run_cases.py --agent <검수 Agent 이름> --out <결과 폴더>` |
| 설정을 바꿔 측정 | 위 명령에 `--set-model haiku` · `--set-effort low` |
| 규칙 하나를 빼고 측정(Ablation) | 위 명령에 `--drop-rule CR-NN` |
| 여러 결과를 한 표로 | `python run_cases.py --compare <결과 폴더> <결과 폴더> …` — 표는 첫 결과 폴더 옆 `compare-<폴더 이름들>.md` 에도 남는다(`--out <파일>` 로 바꾼다) |
| Held-out 한 번 | `python run_cases.py --agent <이름> --cases case-07 --out <결과 폴더>` |
| 채점자 확인 | `python judge.py practice --rubric rubric-v0.md --out <폴더>` → 같은 명령을 `rubric.md` 로 |
| 루브릭 채점 | `python judge.py actual --rubric rubric.md --findings <측정 결과 폴더> --practice-result <채점자 확인 폴더> --out <폴더>` |

- `run_cases.py` 출력: `summary.md`(지표 표 · 사례별 결과) · `summary.json` · `compare.txt` · 사례마다 지적 JSON · Agent 원출력 · 연 파일. `--compare` 는 사례 × 설정 표 · 지표 · 평균 초 · 합계 USD · 실제 모델 · 적용 후보와, 규칙을 뺀 결과가 있으면 사례마다 ATTRIBUTED · NOT_ATTRIBUTED 를 낸다
- `judge.py` 출력: `judge-<루브릭 이름>.md` · `.json`(일치율 · 일관성 · 「늘 합격」 비교값 · 갈린 칸 · 쌍 표 / 루브릭 합격률). 칸마다 바로 저장하므로 한도 · 시간 초과로 멈추면 `--resume` 으로 남은 칸만 다시 부른다
- 종료 코드(측정 · 채점 — 두 스크립트 같음): 0 = 모든 지표 통과 · 1 = 미달 있음 · 2 = 실행 오류 · 기준 표를 읽지 못함. `--compare` 는 표를 만들면 0 이다 — 설정마다 통과 여부는 표에서 읽는다
- 측정은 한 번에 하나씩 한다. 같은 저장소에서 측정 둘을 겹쳐 돌리면 뒤의 것이 멈춘다(사례 병렬은 `--jobs`)
- 측정 프롬프트는 `run_cases.py` 가 고정한다 — 모든 설정을 같은 프롬프트로 잰다. PR 검수 Gate 에서는 `scripts/` 의 검수 스크립트가 만든 프롬프트가 돈다. 그래서 측정 결과와 Gate 결과가 다를 수 있다

## 기준과 적용

- 기준: 예제 코드 `vehicle-speed-monitor` 의 `main`(`b39dde8`)에 요구사항 v2(`test_ref/요구사항.md`)를 들인 상태
- `change.patch` 는 그 기준에서 `git apply` 로 적용된다. 일곱 모두 적용 · 빌드 · 기존 시험이 통과한다
- 적용되지 않으면 `src/` · `include/` 가 기준과 다르다는 뜻이다. patch 를 고치지 말고 무엇이 다른지 확인한다

## 기대 지적 형식 — `expected.json`

```json
{"case": "case-03", "rule_broken": "CR-03", "expected_verdict": "PASS",
 "findings": [{"rule": "CR-03", "severity": "low", "file": "include/speed_monitor.h", "lines": [17, 18],
               "also": [{"file": "src/speed_monitor.c", "lines": [56, 60]}]}]}
```

- `lines` 는 patch 를 적용한 뒤 파일의 줄 범위다. 함수 하나에 걸친 지적은 그 함수의 첫 줄부터 끝 줄까지 인정한다. 지적 대상(함수 · 변수 · 선언) 바로 위의 한 줄 머리 주석도 같은 지적의 자리로 인정한다
- `also` 는 같은 지적으로 인정하는 다른 자리다(선언과 정의 등)
- `findings` 가 비어 있으면 지적이 없어야 한다

## 비교 — `compare.py`

검수 Agent 가 낸 지적 JSON(`review-rules.md` 2절 형식)과 `expected.json` 을 비교한다. 규칙 번호와 파일이 같고 줄이 인정 범위 안이면 일치다. `run_cases.py` 가 측정 뒤 이 스크립트를 부른다.

```
python compare.py case-03/expected.json <Agent 지적 JSON>
python compare.py --cases . --actual <사례 이름.json 을 모아 둔 폴더>
```

- 출력: 사례마다 일치 · 놓침 · 오탐과 그 지적, 마지막 줄에 합계
- 종료 코드: 0 = 놓침 · 오탐 없음 · 1 = 놓침이나 오탐이 있음 · 2 = 판정 불가(파일이 없거나 JSON 형식이 다름)
- 판정 불가는 일치로 치지 않는다. Agent 가 JSON 대신 설명 문장을 냈으면 그 사례는 판정 불가다

## 검수 Agent 가 이 폴더를 보지 않게

- 이 폴더에는 답이 들어 있다. 측정할 때 검수 Agent 에게는 바뀐 코드만 준다
- 측정한 뒤에는 Agent 가 이 폴더의 파일을 열었는지 실행 기록에서 확인한다. 열었으면 그 측정은 버린다
- `run_cases.py` 가 측정 작업 트리에서 이 폴더를 지우고, Agent 가 연 파일을 `<사례>.opened.txt` 에 남겨 「정답 폴더 열람」 지표로 판정한다
