# 팀 DVERA 사용 규칙

우리 팀이 CT DVERA 로 단위 테스트를 만들면서 겪은 문제로 정한 규칙이다. DVERA 셋업 계획과 Jenkins 게시 계획을 검수할 때 규칙마다 계획이 지키는지, 어기는지, 계획에 빠졌는지 확인한다. 지적할 때는 규칙 번호를 붙인다. 셋업 일반 규칙은 `setup-rules.md`(`SU-NN`)다.

## 설치 · 설정

- DV-01 설정은 설정 화면 대신 명령으로 한다 — CT 위치는 `lct config ct`, 테스트 생성에 코딩 에이전트의 LLM 을 쓰는 설정은 `lct config test-generator --llm agent`. 확인은 `lct config status` 의 `license full` · `ct set` · `test_generator agent` 세 줄과 `lct doctor` 의 `agent Claude Code installed` 줄이다
- DV-02 `lct license show` · `lct license register` 를 실행하지 않는다. 오류 창이 뜨고 사람이 닫을 때까지 멈춘다. 라이선스는 CT 화면에서 설정하고 `lct config status` 의 `license` 줄로 확인한다
- DV-03 DVERA 를 설치하면 설치 폴더가 사용자 PATH 에 등록된다. 설치한 뒤에는 새 PowerShell 창에서 `lct` 를 실행하고, 설치 전에 띄운 Jenkins 는 새 창에서 다시 띄운다. 설치 전에 연 창은 `lct` 를 찾지 못한다

## 초기설정

- DV-04 다른 폴더나 다른 PC 에서 만든 초기설정 자산으로 「환경 재적용」을 하지 않는다. 이 저장소에서 초기설정을 처음부터 한다
- DV-05 에이전트가 적용 표준 · 등급을 물으면 사람이 답한다. 코드 · 문서에서 짐작하게 두지 않는다
- DV-06 빌드캡처에 줄 클린 빌드로, 컴파일러 폴더를 PATH 앞에 다시 넣는 빌드 스크립트를 그대로 주지 않는다. 그 스크립트가 캡처용 래퍼보다 앞에 원본 컴파일러를 두어 빌드캡처가 `nothing_captured` 나 `capture_bypass_detected` 로 끝난다. 환경 준비(컴파일러 폴더를 PATH 에 넣는 명령)와 make 명령(clean · 빌드)을 따로 답한다. 에이전트가 같은 취지로 제안하면 그 제안을 고른다. 빌드 스크립트는 고치지 않는다
- DV-07 한글이 든 UTF-8 소스에서 분석 첫 실행이 실패하면 분석 설정 파일을 손으로 고치지 않는다. 에이전트가 보정한 뒤 다시 실행하게 둔다
- DV-08 DVERA 작업은 한 번에 하나만 실행한다. `.lct/` 아래 자산 · 잠금 파일을 손으로 고치거나 지우지 않는다
- DV-09 `.lct/` 를 통째로 커밋하지 않는다. 다른 PC 와 공유할 초기설정 자산과 요구사항 · 테스트 연결 기록만 커밋하고, 무엇이 그것인지는 에이전트에게 묻는다. 이 예제에서 초기설정 뒤 `.lct/` 는 50MB 가 넘었고 대부분이 이 PC 의 작업 파일이었다

## 작업 범위

- DV-10 `SU-04` 가 막는 것은 빌드 환경을 맞추려고 README 의 「고치지 않는다」 폴더를 고치는 것이다. 요구사항이 바뀌었거나 DVERA 시험 결과에 따라 `test_ref/` · `src/` · `include/` · `tests/` 를 고치는 것은 작업 브랜치에 커밋하고 PR 로 올린다. 병합은 사람이 한다

## 결과 · Jenkins

- DV-11 `lct ct open` 을 쓰지 않는다. 지금 버전의 CT 는 DVERA 결과를 열지 못한다. 결과는 `lct ci report` 가 만든 파일로 본다 — `ci-report.agent.txt`(파일별 구문 · 줄 · 분기 · 함수 수치) · `junit.xml` · `cobertura.xml`
- DV-12 Jenkins 빌드에서는 `lct ci run` 앞 단계에서 `.lct/workspace/path-vars.json` 에 그 PC 의 컴파일러 위치를 쓴다. 이 값은 PC 마다 다르다
- DV-13 Jenkins 는 `lct` 가 PATH 에 있고 CT 라이선스를 설정한 사용자의 창에서 띄운다
