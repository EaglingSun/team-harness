# 팀 셋업 규칙

우리 팀이 새 PC 와 새 저장소를 셋업하면서 겪은 문제로 정한 규칙이다. 셋업 계획을 검수할 때 규칙마다 계획이 지키는지, 어기는지, 계획에 빠졌는지 확인한다. 지적할 때는 규칙 번호를 붙인다.

## 계획

- SU-01 완료 기준마다 확인 명령과 기대 출력이 있다
- SU-02 사람이 해야 하는 일(로그인 · 승인 창 · 저장소 만들기 · 병합)은 「내가 할 일」로 따로 적는다
- SU-03 점검기는 셋업 전에 한 번 실행해 FAIL 이 나오는지 확인한다. FAIL 이 하나도 없으면 점검기가 아무것도 확인하지 않는 것이다
- SU-04 프로젝트 README 가 「고치지 않는다」고 정한 폴더 · 파일은 고치지 않는다. 빌드가 안 되면 고치지 말고 멈춰서 보고한다
- SU-05 내려받기가 사내망에서 막히거나 회사 정책이 스크립트 실행을 막으면 우회하지 말고 멈춰서 보고한다
- SU-26 계획의 Goal 문장은 요청에서 받은 목표까지만 잡는다. 목표를 넘는 일은 계획 「다음에 할 것」 절에 두고 내가 고르기 전에는 하지 않는다. 실행 중에 내가 정할 것은 실행 전에 묻고, 실행 중에만 할 수 있는 내 일은 단계 안에 「멈춤 지점」으로 적는다
- SU-27 「…가 없다」를 확인하는 점검 항목은 찾는 값이 든 입력으로 한 번 FAIL 이 나는지 시험한다. 점검기가 읽는 파일의 인코딩(UTF-16 · UTF-8)이 점검기가 읽는 방식과 같은지 연다 — Windows PowerShell 5.1 의 `Tee-Object` 는 UTF-16 으로 써서 UTF-8 로 읽으면 SEVERE 를 못 찾고 PASS 가 난다
- SU-34 점검기 · 스크립트가 하위 프로세스를 부를 때 넘길 입력이 없으면 stdin 을 닫는다(Python 은 `stdin=subprocess.DEVNULL`). 닫지 않으면 자식이 부모의 stdin 을 기다리며 멈추고, 시간 상한으로 부모를 끝내도 남은 자식이 출력을 잡고 있어 부르는 쪽이 돌아오지 않는다

## 컴파일러

- SU-06 컴파일러는 프로젝트 README 「빌드 환경」의 배포 파일을 받고 SHA256 을 확인한다. 해시가 다르면 다른 파일로 바꾸지 않고 멈춘다
- SU-07 다른 gcc(MSYS2 · Chocolatey · winget · 이미 PATH 에 있는 gcc)를 설치하거나 대신 쓰지 않는다
- SU-08 컴파일러를 한글이 든 경로(한글 사용자 폴더 · OneDrive 「바탕 화면」 등)에 두지 않는다. 링크 단계에서 `ld.exe: cannot find …crt2.o` 로 깨진다. 프로젝트 폴더는 한글 경로여도 된다
- SU-09 PATH 를 영구히 바꾸지 않는다(`setx` · 시스템 환경 변수). 빌드를 부르는 명령 안에서만 컴파일러 폴더를 PATH 앞에 붙인다

## 빌드 명령 (Windows)

- SU-10 Claude Code 가 현재 폴더의 배치 파일 · 실행 파일을 부를 때는 `.\` 를 붙인다. Claude Code 는 cmd 가 현재 폴더에서 실행 파일을 찾지 않게 해 둔다(`NoDefaultCurrentDirectoryInExePath=1`)
- SU-11 `.bat` · `.cmd` 는 CRLF 로 저장하고, 저장소에서 꺼낼 때도 CRLF 가 되도록 `.gitattributes` 에 적는다. `chcp 65001` 을 쓰는 배치가 LF 면 exit 1 로 끝난다
- SU-12 한글이 든 `.ps1` 은 UTF-8 BOM 으로 저장한다. BOM 이 없으면 Windows PowerShell 5.1 에서 파싱 오류가 난다
- SU-13 Jenkins 가 실행할 빌드 · 시험 명령은 내 창의 PATH 에 기대지 않는다. 명령 스스로 컴파일러를 찾는다

## 저장소

- SU-14 빌드 산출물(`*.o` · `*.exe` · `test-results/`)과 Jenkins 실행 파일 · Jenkins 홈은 저장소에 넣지 않는다
- SU-15 내 저장소는 팀 원본 템플릿에서 만든다(GitHub **Use this template** · Private). 빈 저장소를 만들어 파일을 옮겨 오지 않는다
- SU-24 개인 무료 계정의 Private 저장소는 GitHub 브랜치 보호를 켤 수 없다(API 403). `main` 직접 push 금지는 `.claude/settings.json` 권한과 CLAUDE.md 규칙으로 두고, PR 체크가 빨강이어도 병합 버튼은 눌린다는 것을 알고 병합한다
- SU-25 Windows Git 은 꺼낼 때 줄바꿈을 CRLF 로 바꾼다(`core.autocrlf=true` 기본). 들인 파일이 팀 원본과 같은지는 줄바꿈까지 같은지로 확인한다

## Jenkins

- SU-16 Jenkins 는 실습 내내 열어 둘 내 창에서, 내 사용자로 띄운다. 창을 닫으면 Jenkins 가 멈춘다. Windows 서비스로 띄우지 않는다 — Jenkins 의 Checkout 은 같은 사용자의 Git 자격 증명을 쓴다
- SU-17 Jenkins job 이 읽는 저장소 주소 · 브랜치가 내 저장소 · `main` 인지 job 설정에서 확인한다
- SU-18 8080 포트를 이미 쓰는 프로그램이 있으면 다른 포트로 띄운다
- SU-19 이 Jenkins 는 `127.0.0.1` 에서만 열려 GitHub 이 병합을 알려 줄 수 없다. 병합 뒤 빌드가 저절로 시작되게 job 이 저장소를 주기적으로 확인한다(Poll SCM)
- SU-20 JDK · Jenkins · 플러그인은 `tool-versions.md` 의 버전으로 받는다. 최신 판과 설치 마법사의 추천 플러그인을 쓰지 않는다 — 최신 JUnit 플러그인은 Jenkins 2.589 이상을 요구해 2.568.3 에서 로드되지 않는다
- SU-21 받은 플러그인 파일 수가 `jenkins-plugins.txt` 줄 수와 같은지 확인하고, 빠진 것만 다시 받는다. 여러 개를 동시에 받으면 일부가 순간 실패한다
- SU-22 Jenkins 를 띄운 뒤 활성 플러그인 수가 목록 수와 같고 로그에 SEVERE 가 없는지 확인한다. 플러그인이 빠진 채 띄우면 job 이 보이지 않는 것 말고는 화면에 실패가 드러나지 않는다
- SU-23 설치 마법사를 끄고 띄운 Jenkins 는 로그인 없이 열린다. `127.0.0.1` 에서만 열고 다른 주소로 열지 않는다

## GitHub Actions · 러너

- SU-28 self-hosted 러너는 내 저장소에 Windows x64 로 등록하고, PR 검수가 도는 동안 러너를 띄운 내 창을 열어 둔다. 창이 닫히면 job 이 `Queued` 에서 멈춘다
- SU-29 러너를 끄고 다시 켠 직후 2 ~ 3분은 `A session for this runner already exists` 가 나고, 그사이 다시 실행한 job 은 `Queued` 로 남는다. 그 job 은 취소한 뒤 다시 실행한다
- SU-30 러너에서 쓰는 Claude Code 는 그 PC 에 로그인된 것을 그대로 쓴다. API 키 · 개인 토큰을 저장소나 시크릿에 두지 않고, PR 에 코멘트를 다는 토큰은 `github.token` 이다
- SU-31 PR 에 결과 코멘트 · 인라인 코멘트를 다는 workflow 는 `permissions` 에 `pull-requests: write` 와 `issues: write` 를 적는다
- SU-32 workflow 를 Windows `cmd` 셸로 돌리며 Python 이 한글을 출력하면 그 단계 `env` 에 `PYTHONIOENCODING: utf-8` 을 둔다
- SU-33 workflow 에 `paths` 를 걸면 그 경로의 파일을 바꾸지 않은 PR 에서는 workflow 가 돌지 않는다. 검수가 돌았는지는 PR 의 Checks 에 그 workflow 가 있는지로 확인한다
