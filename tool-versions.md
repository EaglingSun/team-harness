# 팀이 승인한 CI 도구 버전

내 PC 에 Jenkins 를 셋업할 때 이 버전만 쓴다. 최신 판으로 바꾸려면 팀이 이 파일부터 고친다.

| 도구 | 버전 | 받는 곳 |
|---|---|---|
| JDK | Eclipse Temurin `21.0.13+9` · Windows x64 · zip | `https://api.adoptium.net/v3/binary/version/jdk-21.0.13%2B9/windows/x64/jdk/hotspot/normal/eclipse?project=jdk` |
| Jenkins | `2.568.3` · `jenkins.war` | `https://get.jenkins.io/war-stable/2.568.3/jenkins.war` |
| 플러그인 | `jenkins-plugins.txt` 의 80개 · `이름:버전` | `https://updates.jenkins.io/download/plugins/{이름}/{버전}/{이름}.hpi` → Jenkins 홈의 `plugins\{이름}.jpi` |

- 내려받는 양은 JDK 약 205MB · war 약 101MB · 플러그인 약 64MB 다.
- 이 조합으로 Jenkins 를 띄우면 플러그인 80개가 모두 활성이고 로그에 SEVERE 가 없다.
