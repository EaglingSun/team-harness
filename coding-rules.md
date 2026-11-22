# 팀 코딩 규칙

우리 팀 C 코드의 코딩 규칙이다. PR 검수 Agent 는 PR 이 바꾼 줄을 이 규칙과 `review-rules.md` 의 판단 기준으로 보고, 지적마다 규칙 번호를 붙인다. 규칙마다 적힌 category · severity 를 결과에 그대로 쓴다.

- CR-01 0 · 1 밖의 숫자 리터럴은 `#define` 상수나 enum 이름으로 쓴다. 여러 파일이 쓰는 상수는 `include/vsm_types.h` 에 둔다 (category=magic-number · severity=low)
- CR-02 배열을 읽거나 쓰는 인덱스는 같은 함수 안에서 배열 크기보다 작은지 확인하거나 `% 크기` 로 감싼다 (category=buffer-overflow · severity=high)
- CR-03 헤더에 `extern` 전역 변수를 선언하지 않는다. 모듈 상태는 그 `.c` 파일 범위의 `static` 변수로 두고 함수로만 읽고 쓴다 (category=global-variable · severity=medium)
- CR-04 `test_ref/` 요구사항(`SR-NNN`) 문장에 나오는 값 · 조건을 구현한 줄에는 그 요구사항 번호를 주석으로 단다 (category=req-trace · severity=low)
- CR-05 쓰지 않는 매개변수는 함수 첫 줄에 `(void)이름;` 으로 표시한다 (category=unused-parameter · severity=low)

- 규칙을 더하거나 고칠 때는 이 파일을 고치고 PR 로 올린다. 프로젝트 저장소에는 다시 들인다
- 이 프로젝트에서만 쓰는 규칙은 프로젝트 규칙 파일에 둔다
