# PR 검수 Agent 정답 묶음

PR 검수 Agent 가 팀 코딩 규칙(`coding-rules.md` CR-01 ~ 05)대로 지적하는지 측정하는 사례 묶음이다. 사례마다 바뀐 코드(`change.patch`)와 기대 지적(`expected.json`)이 있다. 검수 Agent 의 지시나 규칙을 고친 뒤에는 이 묶음으로 다시 측정하고, 결과를 PR 에 붙인다.

| 사례 | 바꾼 것 | 어긴 규칙 | 기대 판정 |
|---|---|---|---|
| `case-01` | 주의 기준을 숫자 리터럴로 쓴 새 함수 | CR-01 | PASS(G3) |
| `case-02` | 범위를 확인하지 않는 인덱스로 버퍼를 읽는 새 함수 | CR-02 | FAIL(G2) |
| `case-03` | 헤더에 `extern` 전역 변수 선언 | CR-03 | PASS(G3) |
| `case-04` | SR-008 의 개수 조건을 구현하면서 요구사항 번호 주석이 없음 | CR-04 | PASS(G3) |
| `case-05` | 쓰지 않는 매개변수를 표시하지 않은 새 함수 | CR-05 | PASS(G3) |
| `case-06` | 규칙을 모두 지킨 새 함수 | 없음 | PASS(G3) |
| `case-07` | (예비) `static` 이 아닌 파일 범위 모듈 상태 | CR-03 | PASS(G3) |

- 판정만으로는 놓친 지적이 보이지 않는다. CR-02 만 severity `high` 라 일곱 가운데 여섯이 PASS 다. 그래서 지적 단위로 비교한다
- `case-06` 은 지적이 없어야 하는 사례다. 여기서 나온 지적은 모두 오탐이다

## 기준과 적용

- 기준: 예제 코드 `vehicle-speed-monitor` 의 `main`(`b39dde8`)에 요구사항 v2(`test_ref/요구사항.md`)를 들인 상태
- `change.patch` 는 그 기준에서 `git apply` 로 적용된다. 일곱 모두 적용 · 빌드 · 기존 시험이 통과한다
- 적용되지 않으면 `src/` · `include/` 가 기준과 다르다는 뜻이다. patch 를 고치지 말고 무엇이 다른지 확인한다

## 기대 지적 형식 — `expected.json`

```json
{"case": "case-03", "rule_broken": "CR-03", "expected_verdict": "PASS",
 "findings": [{"rule": "CR-03", "severity": "medium", "file": "include/speed_monitor.h", "lines": [18, 18],
               "also": [{"file": "src/speed_monitor.c", "lines": [57, 57]}]}]}
```

- `lines` 는 patch 를 적용한 뒤 파일의 줄 범위다. 함수 하나에 걸친 지적은 그 함수의 첫 줄부터 끝 줄까지 인정한다
- `also` 는 같은 지적으로 인정하는 다른 자리다(선언과 정의 등)
- `findings` 가 비어 있으면 지적이 없어야 한다

## 비교 — `compare.py`

검수 Agent 가 낸 지적 JSON(`review-rules.md` 2절 형식)과 `expected.json` 을 비교한다. 규칙 번호와 파일이 같고 줄이 인정 범위 안이면 일치다.

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
