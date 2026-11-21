# team-harness — 팀 하네스

우리 팀이 Claude Code 로 일할 때 쓰는 하네스 원본이다. 프로젝트 저장소에 들이고, 그 저장소의 CLAUDE.md 가 이 파일들의 위치를 가리키게 해서 쓴다. 규칙은 지난 작업에서 겪은 문제로 정했다.

| 파일 | 내용 | 쓰는 곳 |
|---|---|---|
| `setup-rules.md` | 팀 셋업 규칙 `SU-NN` — 개발 환경 · 저장소 · Jenkins 셋업 | 셋업 계획을 쓸 때 · 계획을 검수할 때 |
| `tool-versions.md` | 팀이 승인한 CI 도구 버전 — JDK · Jenkins · 플러그인 | 내 PC 에 Jenkins 를 셋업할 때 |
| `jenkins-plugins.txt` | Jenkins 플러그인 `이름:버전` 목록 | `tool-versions.md` 가 가리킨다 |

- 규칙을 고칠 때는 이 저장소를 고치고, 프로젝트 저장소에는 다시 들인다.
- 프로젝트마다 다른 사실(컴파일러 버전 · 빌드 명령)은 그 프로젝트의 README 에 있다.
