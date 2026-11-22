# team-harness — 팀 하네스

우리 팀이 Claude Code 로 일할 때 쓰는 하네스 원본이다. 프로젝트 저장소에 들이고, 그 저장소의 CLAUDE.md 가 이 파일들의 위치를 가리키게 해서 쓴다. 규칙은 지난 작업에서 겪은 문제로 정했다.

| 파일 | 내용 | 쓰는 곳 |
|---|---|---|
| `setup-rules.md` | 팀 셋업 규칙 `SU-NN` — 개발 환경 · 저장소 · Jenkins · GitHub Actions 러너 셋업 | 셋업 계획을 쓸 때 · 계획을 검수할 때 |
| `tool-versions.md` | 팀이 승인한 CI 도구 버전 — JDK · Jenkins · 플러그인 | 내 PC 에 Jenkins 를 셋업할 때 |
| `jenkins-plugins.txt` | Jenkins 플러그인 `이름:버전` 목록 | `tool-versions.md` 가 가리킨다 |
| `coding-rules.md` | 팀 코딩 규칙 `CR-NN` — 규칙마다 category · severity | PR 검수 Agent 의 검수 기준 · 코드를 쓸 때 |
| `review-rules.md` | PR 검수 규칙 — 검수 범위 · 결과 형식(JSON) · PR 코멘트 · 판정(PASS · FAIL · REVIEW · ERROR) | PR 검수 Agent 와 workflow 를 만들 때 |
| `dvera-rules.md` | 팀 DVERA 사용 규칙 `DV-NN` — 설치 · 초기설정 · 작업 범위 · 결과와 Jenkins | DVERA 셋업 계획과 Jenkins 게시 계획을 쓸 때 · 검수할 때 |
| `pr-review-cases/` | PR 검수 Agent 정답 묶음 — 사례 일곱(바뀐 코드 · 기대 지적)과 비교 스크립트 | PR 검수 Agent 를 재고 고친 뒤 다시 잴 때 |

- 규칙을 고칠 때는 이 저장소를 고치고, 프로젝트 저장소에는 다시 들인다.
- 프로젝트마다 다른 사실(컴파일러 버전 · 빌드 명령)은 그 프로젝트의 README 에 있다.
