#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR 검수 Agent 를 정답 묶음 사례로 측정하고, 통과 기준(eval-criteria.md)으로 지표를 판정한다.

측정
  python run_cases.py --agent <검수 Agent 이름> --out <결과 폴더>
      [--cases case-01,case-02] [--ref HEAD] [--set-model haiku] [--set-effort low] [--drop-rule CR-03]
      [--criteria <통과 기준 파일>] [--jobs 3] [--timeout 600]
  - <ref> 커밋 상태를 사례마다 임시 작업 트리에 꺼내 patch 를 커밋하고, 그 작업 트리에서 검수 Agent 를 부른다
  - --set-model · --set-effort 는 측정 작업 트리의 Agent 정의 머리 칸만 바꾼다. --drop-rule 은 측정 작업 트리의
    team-harness/coding-rules.md 에서 그 규칙의 표 행과 상세 절(## CR-NN)만 지운다. 내 저장소의 파일은 바꾸지 않는다
  - 측정 작업 트리에서는 이 폴더(정답 묶음)를 지운 뒤 Agent 를 부른다. Agent 가 연 파일을 기록한다
  - 측정 프롬프트는 이 스크립트가 고정한다 — 모든 설정을 같은 프롬프트로 잰다. PR 검수 Gate 에서는
    scripts/ 의 검수 스크립트가 만든 프롬프트가 돈다
비교
  python run_cases.py --compare <결과 폴더> <결과 폴더> ... [--criteria <통과 기준 파일>]
  - 사례 × 설정 표 · 지표 · 평균 초 · 합계 USD(소수 넷째 자리) · 합계 입력 토큰(그중 캐시 읽기 · 캐시 생성) · 합계 출력 토큰(그중 thinking) · 1M 토큰당 실효 USD(USD ÷ 전체 토큰 — 모델 단가와 토큰 구성이 섞인 값) · 실제 모델 · 적용 후보와 한 줄 결론(A 대비 후보의 비용 차이가 토큰 수에서 오는지 토큰당 실효 비용에서 오는지)을 낸다
  - 토큰은 result 이벤트 modelUsage 의 모든 모델을 더한 값이다. 입력 토큰 = inputTokens + cacheReadInputTokens +
    cacheCreationInputTokens · 출력 토큰 = outputTokens(thinking 포함 · thinkingTokens 는 따로 기록만). 키가 하나라도 없는 사례 · 그런 사례가 든 합계 · 옛 결과는 「-」 로 낸다.
    적용 후보는 지금처럼 USD · 평균 초로 고른다(토큰은 참고 칸)
  - 규칙을 뺀 폴더가 있으면 같은 설정의 규칙 있는 폴더와 사례마다 ATTRIBUTED · NOT_ATTRIBUTED · 계산 안 함
  - 측정 커밋 · 사례 목록 · 기준 표 · Agent 정의 본문(머리 칸 밖)이 다른 폴더를 섞으면 멈춘다

출력(결과 폴더): <사례>.json(지적 JSON — 형식이 맞을 때만) · <사례>.agent.txt(원출력) · <사례>.opened.txt(연 파일)
                · <사례>.stream.jsonl · compare.txt · summary.json · summary.md
종료 코드: 0 = 모든 지표 통과 · 1 = 미달 있음 · 2 = 실행 오류 · 기준 표 읽기 실패 · 작업 트리 문제 · 환경 변수 ·
          modelUsage 에 토큰 키가 하나도 없는 사례(경고를 낸다 — Claude Code 의 키 이름이 바뀌었을 수 있다)
"""
import argparse
import concurrent.futures
import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
COMPARE = os.path.join(HERE, "compare.py")
CRITERIA = os.path.join(HERE, "eval-criteria.md")
BRANCH_PREFIX = "eval-run/"
WT_DIRNAME = ".eval-wt"
BLOCK_ENV = ("CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_SUBAGENT_MODEL", "ANTHROPIC_MODEL")
FIELDS = ("rule", "file", "line", "category", "severity", "message")
SEVERITIES = ("high", "medium", "low")
RULE_ID = re.compile(r"^[A-Z]{2,}-\d{2,}$")  # CR-01 · 프로젝트 규칙 번호
MODEL_FAMILIES = ("haiku", "sonnet", "opus", "fable")
MEASURE_KEYS = ("cannot", "opened", "recall", "false_pos", "heldout")
# result 이벤트 modelUsage[<실제 모델>] 의 토큰 키(Claude Code 2.1.332 에서 확인) → 기록 이름
TOKEN_KEYS = (("input_tokens", "inputTokens"), ("cache_read_tokens", "cacheReadInputTokens"),
              ("cache_creation_tokens", "cacheCreationInputTokens"), ("output_tokens", "outputTokens"),
              ("thinking_tokens", "thinkingTokens"))
TOKENS_IN = ("input_tokens", "cache_read_tokens", "cache_creation_tokens")  # 입력 토큰 = 입력 + 캐시 읽기 + 캐시 생성
TOKENS_OUT = ("output_tokens",)  # 출력 토큰 = outputTokens(thinking 이 이미 들어 있다 — costUSD 역산)
LABELS = {"cannot": "판정 불가", "opened": "정답 폴더 열람", "recall": "검출률", "false_pos": "오탐", "heldout": "Held-out",
          "rubric_pass": "루브릭 합격률", "agreement": "Judge 일치율", "consistency": "Judge 일관성",
          "judge_errors": "Judge 오류"}
PROMPT = (
    "바뀐 코드를 검수한다. base={base} head={head}. 작업 폴더는 head 를 체크아웃한 저장소 루트다.\n\n"
    "검수 대상 파일과 바뀐 줄(추가 · 변경된 줄, 변경 후 파일의 줄 번호):\n{table}\n\n"
    "diff(-U3):\n{diff}\n\n"
    "먼저 team-harness/coding-rules.md · team-harness/review-rules.md · docs/project-rules.md 를 읽는다. "
    "출력은 review-rules.md 2절의 JSON 객체 하나뿐이다."
)
GIT_LOCK = threading.Lock()


class Stop(Exception):
    """측정 전 확인 실패 · 작업 트리 문제 — 종료 코드 2."""


class FormatError(Exception):
    """Agent 답이 review-rules.md 2절 형식이 아니다 — 지적 파일을 쓰지 않는다(compare.py 가 판정 불가로 센다)."""


# ---------------------------------------------------------------- 공통

def run(cmd, cwd, env=None, input_bytes=None, timeout=180):
    kw = {"input": input_bytes} if input_bytes is not None else {"stdin": subprocess.DEVNULL}
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout, **kw)
    return p.returncode, p.stdout.decode("utf-8", errors="replace"), p.stderr.decode("utf-8", errors="replace")


def git(args, cwd, ok=(0,)):
    rc, out, err = run(["git", "-c", "core.quotepath=false", *args], cwd)
    if rc not in ok:
        raise Stop("git %s 실패: %s" % (" ".join(args[:3]), (err or out).strip()[:300]))
    return out if ok == (0,) else (rc, out)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def token_sum(values):
    """값이 모두 숫자일 때만 합. 하나라도 비면(옛 결과 · 키 이름이 바뀐 Claude Code · 한 사례만 빠짐) None —
    0 으로 채우거나 부분합을 완전한 값처럼 내지 않는다."""
    vals = list(values)
    ok = vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)
    return sum(vals) if ok else None


def token_cell(v):
    return "-" if v is None else str(v)


def usd_cell(v):
    """소수 넷째 자리로 맞춘다 — 0.024 처럼 끝 0 이 빠지면 0.0238 보다 작아 보인다."""
    return "-" if v is None else "%.4f" % v


def run_tokens(r, key):
    """결과 폴더 하나의 토큰 종류별 합(사례 원값). 한 사례라도 비면 None."""
    rows = r.get("cases_detail") or []
    return token_sum(c.get(key) for c in rows) if rows else None


def per_million(r):
    """입력 + 출력 토큰 1M 개당 실효 USD = USD ÷ 전체 토큰. 모델 단가만이 아니라 토큰 구성(캐시 읽기 · 생성 · 출력 비중)도
    섞인 값이다 — 모델 단가로 읽지 않는다. 토큰이 비면 None."""
    tin, tout, usd = r.get("tokens_in_total"), r.get("tokens_out_total"), r.get("cost_total_usd")
    if tin is None or tout is None or usd is None or tin + tout == 0:
        return None
    return usd / (tin + tout) * 1e6


def ratio_text(a, b):
    """a → b 를 읽기 쉽게 — 절반 아래로 줄면 약 1/N · 그보다 작게 줄면 N% 감소 · 늘거나 같으면 N.NN배."""
    if not a or b is None:
        return "-"
    if b <= 0:
        return "0 으로 줄어듦"
    if b < a:
        return "약 1/%d" % round(a / b) if a / b >= 2 else "%d%% 감소" % round((1 - b / a) * 100)
    return "%.2f배" % (b / a)


def conclusion(base, best):
    """한 줄 결론 — 기준(A)과 적용 후보의 비용 차이가 토큰 수에서 오는지, 토큰당 실효 비용(모델 · 토큰 구성)에서 오는지
    코드로 조립한다. 값이 0 · 비어 있으면 원인을 나누지 않고 숫자만 쓴다."""
    import math
    if best is base:
        return "한 줄 결론: 통과한 설정 가운데 %s (%s) 가 가장 싸다 — 다른 설정으로 바꿔 줄일 비용이 없다" % (base["_L"], base["label"])
    ua, ub = base.get("cost_total_usd"), best.get("cost_total_usd")
    head = "한 줄 결론: %s (%s) 는 %s (%s) 보다 USD 가 %s(%s → %s)이고 지표는 %s" % (
        best["_L"], best["label"], base["_L"], base["label"], ratio_text(ua, ub), usd_cell(ua), usd_cell(ub),
        "둘 다 통과" if base["_pass"] else "%s 만 통과" % best["_L"])
    keys = ("tokens_in_total", "tokens_out_total")
    if any(base.get(k) in (None, 0) or best.get(k) is None for k in keys):
        return head + " — 토큰 칸이 비어 비용 차이의 원인을 나눌 수 없다"
    ri, ro = best["tokens_in_total"] / base["tokens_in_total"], best["tokens_out_total"] / base["tokens_out_total"]
    pa, pb = per_million(base), per_million(best)
    tok = (best["tokens_in_total"] + best["tokens_out_total"]) / (base["tokens_in_total"] + base["tokens_out_total"])
    body = " — 토큰은 입력 %.2f배 · 출력 %.2f배" % (ri, ro)
    if not pa or not pb or tok <= 0:  # USD 가 0(반올림 0.0000 포함)이면 로그 비교를 하지 않는다
        return head + body + " — USD 가 0 이라 비용 차이의 원인을 나누지 않는다"
    cause = "토큰당 실효 비용" if abs(math.log(pb / pa)) >= abs(math.log(tok)) else "토큰 수"
    return head + body + "이고 1M 토큰당 실효 USD 가 %.2f → %.2f 이므로 비용 차이는 주로 %s 차이에서 온다(실효 비용은 모델과 토큰 구성이 섞인 값)" % (
        pa, pb, cause)


def sha256_file(path):
    with open(path, "rb") as fh:
        return sha256_bytes(fh.read())


def clean_env(base=None):
    """부모 Claude Code 세션의 변수(CLAUDE*)를 빼고 넘긴다 — 그대로 넘기면 부모 세션의 mod · MCP 도구가 붙는다.
    CLAUDE_CONFIG_DIR(어느 설정 폴더로 로그인했나)은 남긴다."""
    base = dict(os.environ if base is None else base)
    env = {k: v for k, v in base.items() if not (k.upper().startswith("CLAUDE") and k.upper() != "CLAUDE_CONFIG_DIR")}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def find_claude():
    exe = shutil.which("claude")
    if not exe:
        raise Stop("claude 를 PATH 에서 찾지 못했다")
    return exe


def claude_version(exe, env):
    rc, out, err = run([exe, "--version"], HERE, env=env, timeout=60)
    return out.strip() or err.strip()


def call_agent(exe, agent, cwd, prompt, env, timeout):
    """검수 Agent 1회. (종료 코드, stream-json 출력, stderr). 시험에서는 가짜로 바꾼다."""
    return run([exe, "-p", "--agent", agent, "--output-format", "stream-json", "--verbose",
                "--no-session-persistence", "--allowedTools", "Read,Grep,Glob"],
               cwd, env=env, input_bytes=prompt.encode("utf-8"), timeout=timeout)


def show_or_empty(repo, ref, path):
    rc, out = git(["show", "%s:%s" % (ref, path)], repo, ok=(0, 128))
    return out if rc == 0 else ""


# ---------------------------------------------------------------- 통과 기준 표

def read_criteria(path):
    """eval-criteria.md 표에서 지표 키(`키`)와 통과선(`비교식`)을 읽는다. 읽지 못하면 Stop."""
    if not os.path.isfile(path):
        raise Stop("통과 기준 파일이 없다: %s" % path)
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8")
    thresholds = {}
    in_table = False
    for ln in text.splitlines():
        s = ln.strip()
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and cells[0] == "지표":
            in_table = True
            continue
        if not in_table or set(cells[0]) <= set("-: "):
            continue
        if len(cells) < 4:
            raise Stop("통과 기준 표의 칸이 넷이 아니다: %s" % s[:80])
        key = re.search(r"`([a-z_]+)`", cells[0])
        if not key:
            raise Stop("통과 기준 표 지표 칸에 `키` 가 없다: %s" % cells[0][:60])
        cond = re.search(r"`\s*(>=|<=|=)\s*([0-9]+(?:\.[0-9]+)?)\s*`", cells[2])
        if not cond:
            raise Stop("통과 기준 표 「%s」 통과선 칸에 `비교식` 이 없다: %s" % (key.group(1), cells[2][:60]))
        thresholds[key.group(1)] = {"op": cond.group(1), "value": float(cond.group(2)),
                                    "text": cells[2], "label": re.sub(r"\s*`[a-z_]+`", "", cells[0]).strip()}
    if not thresholds:
        raise Stop("통과 기준 표를 찾지 못했다(머리 줄 「| 지표 |」): %s" % path)
    held = re.search(r"^- Held-out 사례:\s*(.+)$", text, re.M)
    heldout = re.findall(r"`(case-[^`]+)`", held.group(1)) if held else []
    return {"thresholds": thresholds, "heldout": heldout, "sha": sha256_bytes(raw), "path": path}


def require_rows(crit, keys):
    missing = [k for k in keys if k not in crit["thresholds"]]
    if missing:
        raise Stop("통과 기준 표에 줄이 없다: %s" % ", ".join(missing))


def passes(th, value):
    if value is None:
        return None
    if th["op"] == ">=":
        return value >= th["value"] - 1e-9
    if th["op"] == "<=":
        return value <= th["value"] + 1e-9
    return abs(value - th["value"]) < 1e-9


def judge_metrics(crit, metrics, keys):
    """지표마다 (값, 통과선, 판정). 값이 None 이면 「해당 없음」."""
    rows = []
    for k in keys:
        th = crit["thresholds"][k]
        v = metrics.get(k)
        ok = passes(th, v)
        rows.append({"key": k, "label": th["label"], "value": v, "threshold": th["text"],
                     "verdict": "해당 없음" if ok is None else ("통과" if ok else "미달")})
    return rows


# ---------------------------------------------------------------- Agent 답 형식(review-rules.md 2절)

def validate_findings_text(text):
    s = text.strip()
    try:
        obj, end = json.JSONDecoder().raw_decode(s)
    except ValueError as e:
        raise FormatError("JSON 객체 하나가 아니다(앞에 글 · 코드펜스 포함): %s" % e)
    if s[end:].strip():
        raise FormatError("JSON 뒤에 글이 있다")
    if not isinstance(obj, dict) or not isinstance(obj.get("findings"), list):
        raise FormatError('최상위가 {"findings": [...]} 가 아니다')
    for i, f in enumerate(obj["findings"], 1):
        if not isinstance(f, dict):
            raise FormatError("지적 %d 이 객체가 아니다" % i)
        missing = [k for k in FIELDS if k not in f]
        if missing:
            raise FormatError("지적 %d 에 칸이 없다: %s" % (i, ", ".join(missing)))
        for k in ("rule", "file", "category", "message"):
            if not isinstance(f[k], str) or not f[k].strip():
                raise FormatError("지적 %d 의 %s 가 비었다" % (i, k))
        if isinstance(f["line"], bool) or not isinstance(f["line"], int):
            raise FormatError("지적 %d 의 line 이 정수가 아니다" % i)
        if f["severity"] not in SEVERITIES:
            raise FormatError("지적 %d 의 severity 가 허용값 밖이다: %r" % (i, f["severity"]))
        if not RULE_ID.match(f["rule"]):
            raise FormatError("지적 %d 의 rule 이 규칙 번호가 아니다: %r" % (i, f["rule"]))
    return obj["findings"]


# ---------------------------------------------------------------- 머리 칸 · 규칙 빼기

def _split_front(text):
    lines = text.split("\n")
    if not lines or lines[0].rstrip("\r") != "---":
        raise Stop("Agent 정의에 머리 칸(--- 로 시작하는 줄)이 없다")
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r") == "---":
            return lines, i
    raise Stop("Agent 정의 머리 칸이 --- 로 닫히지 않았다")


def front_value(text, key):
    lines, end = _split_front(text)
    for ln in lines[1:end]:
        m = re.match(r"^%s:\s*(.*?)\s*$" % re.escape(key), ln.rstrip("\r"))
        if m:
            return m.group(1) or None
    return None


def set_front_text(text, key, value):
    lines, end = _split_front(text)
    cr = "\r" if lines[0].endswith("\r") else ""
    for i in range(1, end):
        if re.match(r"^%s:" % re.escape(key), lines[i]):
            lines[i] = "%s: %s%s" % (key, value, cr)
            return "\n".join(lines)
    lines.insert(end, "%s: %s%s" % (key, value, cr))
    return "\n".join(lines)


def set_front(path, key, value):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    with open(path, "wb") as fh:
        fh.write(set_front_text(text, key, value).encode("utf-8"))


def body_sha_text(text):
    lines, end = _split_front(text)
    body = "\n".join(lines[end + 1:]).replace("\r\n", "\n")
    return sha256_bytes(body.encode("utf-8"))


def body_sha(path):
    with open(path, "rb") as fh:
        return body_sha_text(fh.read().decode("utf-8"))


def rule_spans(lines, rule):
    """coding-rules.md 에서 규칙 하나가 차지하는 줄 — 표 행(| CR-01 | …)과 상세 절(## CR-01 … 다음 ## 앞까지).
    (표 행 번호 목록, 절 줄 번호 목록)"""
    esc = re.escape(rule)
    rows = [i for i, ln in enumerate(lines) if re.match(r"^\|\s*%s\s*\|" % esc, ln.rstrip("\r"))]
    heads = [i for i, ln in enumerate(lines) if re.match(r"^##\s+%s(\s|$)" % esc, ln.rstrip("\r"))]
    section = []
    if len(heads) == 1:
        end = next((j for j in range(heads[0] + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        section = list(range(heads[0], end))
    return rows, heads, section


def drop_rule_text(text, rule):
    lines = text.split("\n")
    rows, heads, section = rule_spans(lines, rule)
    if len(rows) != 1 or len(heads) > 1:
        raise Stop("coding-rules.md 에 「| %s |」 표 행이 %d 개 · 「## %s」 절이 %d 개다(표 행 하나 · 절 하나 이하여야 한다)"
                   % (rule, len(rows), rule, len(heads)))
    drop = set(rows) | set(section)
    kept = [ln for i, ln in enumerate(lines) if i not in drop]
    return "\n".join(kept), lines[rows[0]].rstrip("\r")


def drop_rule(path, rule):
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8")
    new, removed = drop_rule_text(text, rule)
    with open(path, "wb") as fh:
        fh.write(new.encode("utf-8"))
    return removed


def model_matches(setting, actual):
    """머리 칸 model 값과 stream init 의 실제 모델 ID 를 대조한다. 별칭(haiku · sonnet …)은 계열 이름이 ID 에 들어 있어야 한다."""
    if not setting or setting == "inherit":
        return True
    if not actual:
        return False
    s = setting.strip().lower()
    a = actual.strip().lower()
    if s in MODEL_FAMILIES:
        return s in a
    return a == s or a.startswith(s)


# ---------------------------------------------------------------- stream · 연 파일

def parse_stream(text):
    model, result, tools, bad = None, None, [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            model = ev.get("model")
        elif ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tools.append({"name": block.get("name"), "input": block.get("input")})
        elif ev.get("type") == "result":
            result = ev
    return model, result, tools, bad


def tool_targets(tools):
    out = []
    for t in tools:
        inp = t.get("input") or {}
        for key in ("file_path", "path", "pattern", "glob"):
            if isinstance(inp.get(key), str):
                out.append("%s %s=%s" % (t.get("name"), key, inp[key]))
    return out


def opened_answer(targets, dirname):
    return any(dirname in t.replace("\\", "/") for t in targets)


def diff_lines(diff_text):
    result, cur = {}, None
    for ln in diff_text.splitlines():
        if ln.startswith("+++ "):
            p = ln[4:].strip()
            cur = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
            if cur is not None:
                result.setdefault(cur, [])
        elif ln.startswith("@@") and cur is not None:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", ln)
            if m:
                start, count = int(m.group(1)), int(m.group(2)) if m.group(2) is not None else 1
                result[cur].extend(range(start, start + count))
    return result


# ---------------------------------------------------------------- 지표

def compute_metrics(rows, heldout):
    """rows: 사례마다 cannot · match · false_pos · expected · opened. 판정 불가 사례의 기대 지적도 분모에 넣는다."""
    reg = [r for r in rows if r["case"] not in heldout]
    held = [r for r in rows if r["case"] in heldout]

    def rate(rs):
        exp = sum(r["expected"] for r in rs)
        return None if exp == 0 else round(sum(0 if r["cannot"] else r["match"] for r in rs) / exp, 4)

    return {"cannot": sum(1 for r in rows if r["cannot"]),
            "opened": sum(1 for r in rows if r["opened"]),
            "false_pos": sum(0 if r["cannot"] else r["false_pos"] for r in rows),
            "recall": rate(reg) if reg else None,
            "heldout": rate(held) if held else None}


def parse_compare(out, names):
    res = {}
    for ln in out.splitlines():
        m = re.match(r"^\[([^\]]+)\] 일치 (\d+) · 놓침 (\d+) · 오탐 (\d+)$", ln)
        if m:
            res[m.group(1)] = {"cannot": False, "match": int(m.group(2)), "missed": int(m.group(3)),
                               "false_pos": int(m.group(4))}
            continue
        m = re.match(r"^\[([^\]]+)\] 판정 불가: (.*)$", ln)
        if m:
            res[m.group(1)] = {"cannot": True, "match": 0, "missed": 0, "false_pos": 0, "reason": m.group(2)}
    missing = [n for n in names if n not in res]
    if missing:
        raise Stop("compare.py 출력에서 사례를 찾지 못했다: %s" % ", ".join(missing))
    return res


# ---------------------------------------------------------------- 측정

def check_settings_file(path):
    if not os.path.isfile(path):
        return
    try:
        data = json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        raise Stop("설정 파일을 읽지 못했다(%s): %s" % (e, path))
    if not isinstance(data, dict):
        return
    if data.get("effortLevel"):
        raise Stop("설정 파일에 effortLevel 이 있다 — 측정 설정이 섞인다. 측정하는 동안 빼 둔다: %s" % path)
    env = data.get("env") or {}
    hit = [k for k in BLOCK_ENV if isinstance(env, dict) and env.get(k)]
    if hit:
        raise Stop("설정 파일 env 에 %s 가 있다 — 측정 설정이 섞인다: %s" % (", ".join(hit), path))


def preflight_env(repo):
    hit = [k for k in BLOCK_ENV if os.environ.get(k)]
    if hit:
        raise Stop("환경 변수 %s 가 있다 — Agent 정의 머리 칸보다 앞서 측정 설정이 섞인다. 지운 뒤 다시 실행한다" % ", ".join(hit))
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    check_settings_file(os.path.join(config, "settings.json"))
    for name in ("settings.json", "settings.local.json"):
        check_settings_file(os.path.join(repo, ".claude", name))


@contextlib.contextmanager
def run_lock():
    """측정은 한 번에 하나 — 같은 저장소에서 두 측정이 겹치면 작업 트리 · 브랜치 이름이 겹쳐 서로를 지운다. 사례 병렬은 --jobs 가 맡는다."""
    repo = git(["rev-parse", "--show-toplevel"], HERE).strip().replace("/", os.sep)
    path = os.path.join(os.path.dirname(repo), WT_DIRNAME + ".lock")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Stop("다른 측정이 돌고 있다(%s). 측정은 한 번에 하나씩 한다 — 사례 병렬은 --jobs 가 맡는다. 끝난 뒤 다시 실행한다. "
                   "도는 측정이 없는데 이 파일이 남았으면 지운 뒤 다시 실행한다" % path)
    try:
        os.write(fd, ("pid %d · %s\n" % (os.getpid(), datetime.datetime.now().isoformat(timespec="seconds"))).encode("utf-8"))
    finally:
        os.close(fd)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            print("경고: 측정 잠금 파일이 이미 없다 — 측정 중에 누가 지웠다: %s" % path, flush=True)


def leftovers(repo):
    found = [b.strip().lstrip("*+ ").strip() for b in git(["branch", "--list", BRANCH_PREFIX + "*"], repo).splitlines() if b.strip()]
    for ln in git(["worktree", "list", "--porcelain"], repo).splitlines():
        if ln.startswith("worktree ") and WT_DIRNAME in ln.replace("\\", "/"):
            found.append(ln[len("worktree "):])
    wt_root = os.path.join(os.path.dirname(repo), WT_DIRNAME)
    if os.path.isdir(wt_root):
        found += [os.path.join(wt_root, n) for n in os.listdir(wt_root)]
    return found


def measure_one(ctx, case, index):
    stamp_case = "%s-%s" % (ctx["stamp"], case)
    branch = BRANCH_PREFIX + stamp_case
    wt = os.path.join(ctx["wt_root"], stamp_case)
    repo, out = ctx["repo"], ctx["out"]
    row = {"case": case, "rule": ctx["expected"][case].get("rule_broken"), "expected": len(ctx["expected"][case]["findings"]),
           "error": None, "format_ok": False, "opened": False, "model": None}
    created = False
    try:
        with GIT_LOCK:
            os.makedirs(ctx["wt_root"], exist_ok=True)
            git(["worktree", "add", "-q", "-b", branch, wt, ctx["ref"]], repo)
            created = True
        git(["apply", os.path.join(wt, *ctx["rel"].split("/"), case, "change.patch")], wt)
        git(["add", "--", "src", "include"], wt)
        with GIT_LOCK:
            git(["-c", "user.name=eval-run", "-c", "user.email=eval-run@localhost", "commit", "-q", "--no-verify",
                 "-m", "eval-run " + case], wt)
        head = git(["rev-parse", "HEAD"], wt).strip()
        agent = os.path.join(wt, ".claude", "agents", ctx["agent"] + ".md")
        with open(agent, "wb") as fh:
            fh.write(ctx["agent_text"].encode("utf-8"))
        rules = os.path.join(wt, "team-harness", "coding-rules.md")
        if ctx["rules_text"] is not None:
            with open(rules, "wb") as fh:
                fh.write(ctx["rules_text"].encode("utf-8"))
        shutil.rmtree(os.path.join(wt, *ctx["rel"].split("/")))  # 정답 · 사람 판정이 든 폴더 — 측정 작업 트리에서만 지운다
        diff = git(["diff", "-U3", "%s...%s" % (ctx["ref"], head), "--", "src", "include"], wt)
        table = diff_lines(git(["diff", "-U0", "%s...%s" % (ctx["ref"], head), "--", "src", "include"], wt))
        prompt = PROMPT.format(base=ctx["ref"], head=head, table=json.dumps(table, ensure_ascii=False, indent=1), diff=diff)
        t0 = time.time()
        rc, so, se = call_agent(ctx["exe"], ctx["agent"], wt, prompt, ctx["env"], ctx["timeout"])
        row["seconds"] = round(time.time() - t0, 1)
        with open(os.path.join(out, case + ".stream.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(so)
        model, result, tools, bad = parse_stream(so)
        text = (result or {}).get("result") if isinstance((result or {}).get("result"), str) else ""
        with open(os.path.join(out, case + ".agent.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        targets = tool_targets(tools)
        with open(os.path.join(out, case + ".opened.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(targets) + ("\n" if targets else ""))
        # 사례 토큰 = modelUsage 의 모든 모델 합(init 모델만 세면 보조 호출 몫이 빠진다 — USD 도 total_cost_usd 전체다)
        usages = [u for u in ((result or {}).get("modelUsage") or {}).values() if isinstance(u, dict)]
        tok = {k: token_sum(u.get(src) for u in usages) for k, src in TOKEN_KEYS}
        row.update({"head": head, "claude_rc": rc, "model": model, "cost_usd": (result or {}).get("total_cost_usd"),
                    "num_turns": (result or {}).get("num_turns"), "is_error": (result or {}).get("is_error"),
                    "input_tokens": tok["input_tokens"], "cache_read_tokens": tok["cache_read_tokens"],
                    "cache_creation_tokens": tok["cache_creation_tokens"],
                    "output_tokens": tok["output_tokens"], "thinking_tokens": tok["thinking_tokens"],
                    "tokens_in": token_sum(tok[k] for k in TOKENS_IN), "tokens_out": token_sum(tok[k] for k in TOKENS_OUT),
                    "tokens_missing": result is not None and any(tok[k] is None for k in TOKENS_IN + TOKENS_OUT),
                    "stream_bad_lines": bad, "stderr_tail": se.strip()[-300:], "tools": targets,
                    "opened": opened_answer(targets, ctx["answer_dirname"])})
        if rc != 0 or result is None or (result or {}).get("is_error"):
            row["error"] = "claude 실행 오류(종료 코드 %s · is_error %s)" % (rc, (result or {}).get("is_error"))
        elif not model_matches(ctx["front_model"], model):
            row["error"] = "실제 모델 %s 이 머리 칸 model: %s 와 다르다" % (model, ctx["front_model"])
        if row["error"] is None:
            try:
                findings = validate_findings_text(text)
                with open(os.path.join(out, case + ".json"), "w", encoding="utf-8", newline="\n") as fh:
                    json.dump({"findings": findings}, fh, ensure_ascii=False, indent=1)
                row["format_ok"] = True
            except FormatError as e:
                row["format_error"] = str(e)[:200]
    except Exception as e:  # 사례 하나가 죽어도 정리하고 기록을 남긴다
        row["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    finally:
        if created or os.path.exists(wt):
            with GIT_LOCK:
                run(["git", "worktree", "remove", "--force", wt], repo)
                if os.path.exists(wt):
                    shutil.rmtree(wt, ignore_errors=True)
                run(["git", "worktree", "prune"], repo)
                run(["git", "branch", "-D", branch], repo)
    print("%s %s %ss model=%s cost=%s 형식=%s 열람=%s%s" % (
        index, case, row.get("seconds"), row.get("model"), row.get("cost_usd"), row["format_ok"], row["opened"],
        (" 오류=" + row["error"]) if row["error"] else ""), flush=True)
    return row


def measure(a):
    crit = read_criteria(a.criteria)
    require_rows(crit, MEASURE_KEYS)
    repo = git(["rev-parse", "--show-toplevel"], HERE).strip().replace("/", os.sep)
    rel = os.path.relpath(HERE, repo).replace(os.sep, "/")
    preflight_env(repo)
    ref = git(["rev-parse", "--verify", a.ref + "^{commit}"], repo).strip()
    agent_rel = ".claude/agents/%s.md" % a.agent
    rc_, _ = git(["cat-file", "-e", "%s:%s" % (ref, agent_rel)], repo, ok=(0, 128))
    if rc_ != 0:
        raise Stop("측정 커밋에 검수 Agent 정의가 없다: %s" % agent_rel)
    dirty = git(["status", "--porcelain", "--untracked-files=no", "--", agent_rel, "team-harness", "docs/project-rules.md",
                 "CLAUDE.md"], repo).strip()
    if dirty:
        raise Stop("측정하는 파일에 커밋하지 않은 변경이 있다 — 측정은 커밋된 상태만 한다. 커밋하거나 되돌린 뒤 다시:\n" + dirty)
    git(["fetch", "-q", "origin"], repo)
    drc, _ = git(["diff", "--quiet", "origin/main", ref, "--", "src", "include"], repo, ok=(0, 1))
    if drc != 0:
        raise Stop("측정 커밋의 src/ · include/ 가 origin/main 과 다르다 — 정답 묶음 patch 의 기준과 다르다")
    left = leftovers(repo)
    if left:
        raise Stop("이전 측정의 작업 트리 · 브랜치가 남아 있다. 확인하고 지운 뒤 다시 실행한다:\n  " + "\n  ".join(left))
    out = os.path.abspath(a.out)
    if os.path.isdir(out) and os.listdir(out):
        raise Stop("결과 폴더가 이미 있고 비어 있지 않다 — 새 폴더를 준다: %s" % out)
    names_all = sorted(n for n in os.listdir(HERE) if os.path.isfile(os.path.join(HERE, n, "expected.json")))
    if a.cases:
        names = [n.strip() for n in a.cases.split(",") if n.strip()]
        bad = [n for n in names if n not in names_all]
        if bad:
            raise Stop("없는 사례: %s" % ", ".join(bad))
    else:
        names = [n for n in names_all if n not in crit["heldout"]]
    if not names:
        raise Stop("측정할 사례가 없다")

    agent_text = git(["show", "%s:%s" % (ref, agent_rel)], repo)
    if a.set_model:
        agent_text = set_front_text(agent_text, "model", a.set_model)
    if a.set_effort:
        agent_text = set_front_text(agent_text, "effort", a.set_effort)
    front_model, front_effort = front_value(agent_text, "model"), front_value(agent_text, "effort")
    rules_base = git(["show", "%s:team-harness/coding-rules.md" % ref], repo)
    rules_text, removed, left_in = None, None, []
    if a.drop_rule:
        rules_text, removed = drop_rule_text(rules_base, a.drop_rule)
        if re.search(r"\b%s\b" % re.escape(a.drop_rule), rules_text):
            left_in.append("team-harness/coding-rules.md")
        for p in (agent_rel, "team-harness/review-rules.md", "docs/project-rules.md", "CLAUDE.md"):
            src = agent_text if p == agent_rel else show_or_empty(repo, ref, p)
            if re.search(r"\b%s\b" % re.escape(a.drop_rule), src):
                left_in.append(p)

    exe = find_claude()
    env = clean_env()
    os.makedirs(out, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    expected = {n: json.load(open(os.path.join(HERE, n, "expected.json"), encoding="utf-8")) for n in names}
    ctx ={"stamp": stamp, "repo": repo, "rel": rel, "out": out, "ref": ref, "agent": a.agent, "agent_text": agent_text,
           "rules_text": rules_text, "front_model": front_model, "exe": exe, "env": env, "timeout": a.timeout,
           "expected": expected, "answer_dirname": os.path.basename(HERE), "wt_root": os.path.join(os.path.dirname(repo), WT_DIRNAME)}
    print("측정 커밋 %s · 사례 %s · 머리 칸 model=%s effort=%s%s · 병렬 %d" % (
        ref[:7], ",".join(names), front_model or "(없음)", front_effort or "(없음)",
        (" · %s 뺌" % a.drop_rule) if a.drop_rule else "", a.jobs), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = [ex.submit(measure_one, ctx, n, "%d/%d" % (i, len(names))) for i, n in enumerate(names, 1)]
        rows = [f.result() for f in futs]
    try:
        os.rmdir(ctx["wt_root"])
    except OSError:
        pass

    tmp_cases = tempfile.mkdtemp(prefix="eval-cases-")
    try:
        for n in names:  # 잰 사례만 담는다 — compare.py --cases 는 폴더 안 사례를 모두 센다
            shutil.copytree(os.path.join(HERE, n), os.path.join(tmp_cases, n))
        crc, cout, cerr = run([sys.executable, COMPARE, "--cases", tmp_cases, "--actual", out], HERE, timeout=120)
    finally:
        shutil.rmtree(tmp_cases, ignore_errors=True)
    with open(os.path.join(out, "compare.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(cout + cerr)
    by_name = parse_compare(cout, [expected[n].get("case", n) for n in names])
    for r in rows:
        r.update(by_name[expected[r["case"]].get("case", r["case"])])
    metrics = compute_metrics(rows, crit["heldout"])
    verdicts = judge_metrics(crit, metrics, MEASURE_KEYS)
    run_errors = [r["case"] for r in rows if r["error"]]
    failed = [v for v in verdicts if v["verdict"] == "미달"]
    code = 2 if run_errors else (1 if failed else 0)
    tokens_missing = [r["case"] for r in rows if r.get("tokens_missing")]
    if tokens_missing:  # 토큰 칸이 조용히 비지 않게 — 기록 문제로 종료 코드 2(판정 · 통과선은 그대로)
        code = 2
    label = "model=%s" % (front_model or "없음(세션 모델)") + (" · effort=%s" % front_effort if front_effort else "") + \
            (" · %s 뺌" % a.drop_rule if a.drop_rule else "")
    secs = [r["seconds"] for r in rows if isinstance(r.get("seconds"), (int, float))]
    summ = {"made": stamp, "ref": ref, "cases": names, "agent": a.agent, "agent_path": agent_rel,
            "agent_sha": sha256_bytes(agent_text.encode("utf-8")), "agent_body_sha": body_sha_text(agent_text),
            "rules_base_sha": sha256_bytes(rules_base.encode("utf-8")),
            "rules_sha": sha256_bytes((rules_text if rules_text is not None else rules_base).encode("utf-8")),
            "criteria_sha": crit["sha"], "criteria_path": os.path.abspath(a.criteria),
            "set_model": a.set_model, "set_effort": a.set_effort, "front_model": front_model, "front_effort": front_effort,
            "drop_rule": a.drop_rule, "dropped_line": removed, "rule_left_in": left_in, "label": label,
            "claude_version": claude_version(exe, env), "compare_rc": crc,
            "compare_total": (cout.strip().splitlines() or [""])[-1], "metrics": metrics, "verdicts": verdicts,
            "run_errors": run_errors, "cost_total_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4),
            "tokens_in_total": token_sum(r.get("tokens_in") for r in rows),
            "tokens_out_total": token_sum(r.get("tokens_out") for r in rows),
            "tokens_missing": tokens_missing,
            "seconds_avg": round(sum(secs) / len(secs), 1) if secs else None,
            "models": sorted({r["model"] for r in rows if r.get("model")}), "exit_code": code, "cases_detail": rows}
    with open(os.path.join(out, "summary.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summ, fh, ensure_ascii=False, indent=2)
    md = ["# 측정 결과 — %s" % label, "",
          "- 측정 커밋 `%s` · 사례 %s · Claude Code %s · 실제 모델 %s" % (ref[:7], ", ".join(names), summ["claude_version"], ", ".join(summ["models"])),
          "- compare.py: %s" % summ["compare_total"], ""]
    if left_in:
        md.append("- 규칙 번호가 다른 파일에 남음: %s — 빼도 효과가 없는 까닭일 수 있다" % ", ".join(left_in))
        md.append("")
    md += ["| 지표 | 값 | 통과선 | 판정 |", "|---|---|---|---|"]
    md += ["| %s | %s | %s | %s |" % (v["label"], "-" if v["value"] is None else v["value"], v["threshold"], v["verdict"]) for v in verdicts]
    md += ["", "| 사례 | 규칙 | 일치 · 놓침 · 오탐 | 초 | USD | 입력 토큰 | 출력 토큰 | 모델 | 열람 | 오류 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["case"], r["rule"] or "없음", "판정 불가" if r["cannot"] else "%d · %d · %d" % (r["match"], r["missed"], r["false_pos"]),
            r.get("seconds"), "-" if r.get("cost_usd") is None else round(r["cost_usd"], 4),
            token_cell(r.get("tokens_in")), token_cell(r.get("tokens_out")), r.get("model"), "열람" if r["opened"] else "-",
            r["error"] or r.get("format_error") or "-"))
    if tokens_missing:
        md += ["", "- 경고: 토큰 키(%s) 가운데 입력 · 출력에 쓰는 키가 modelUsage 에 없다(일부 또는 전부 — 그 사례 토큰 칸은 -) — Claude Code 의 키 이름이 바뀌었을 수 있다: %s"
               % (", ".join(src for _, src in TOKEN_KEYS), ", ".join(tokens_missing))]
    md += ["", "- 설정마다 한 번 잰 값이다. 통과선 바로 위거나 판정 불가 하나(형식 위반)로 미달이면 그 설정만 한 번 더 잰다", ""]
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md))
    print(cout.rstrip())
    for v in verdicts:
        print("%s %s — 값 %s · 통과선 %s" % (v["verdict"], v["label"], "-" if v["value"] is None else v["value"], v["threshold"]))
    if tokens_missing:
        print("경고: 토큰 키(%s) 가운데 입력 · 출력에 쓰는 키가 modelUsage 에 없다(일부 또는 전부 — 그 사례 토큰 칸은 -) — Claude Code 의 키 이름이 바뀌었을 수 있다. 사례: %s · 종료 코드 2"
              % (", ".join(src for _, src in TOKEN_KEYS), ", ".join(tokens_missing)))
    print("비용 합 %s USD · 평균 %s초 · 합계 입력 토큰 %s · 합계 출력 토큰 %s · 결과 %s · 종료 코드 %d" % (
        summ["cost_total_usd"], summ["seconds_avg"], token_cell(summ["tokens_in_total"]), token_cell(summ["tokens_out_total"]),
        out, code))
    return code


# ---------------------------------------------------------------- 비교

def cell(r):
    if r["cannot"]:
        return "판정 불가"
    if r["missed"] == 0 and r["false_pos"] == 0:
        return "맞힘"
    parts = []
    if r["missed"]:
        parts.append("놓침 %d" % r["missed"])
    if r["false_pos"]:
        parts.append("오탐 %d" % r["false_pos"])
    return " · ".join(parts)


def attribution(with_row, abl_row):
    if with_row["cannot"] or with_row["missed"] or with_row["false_pos"]:
        return "계산 안 함(규칙 있는 판이 이미 틀림)"
    if abl_row["cannot"]:
        return "계산 안 함(판정 불가)"
    if abl_row["missed"] or abl_row["false_pos"]:
        return "ATTRIBUTED"
    return "NOT_ATTRIBUTED"


def compare_runs(dirs, out=None):
    runs = []
    for d in dirs:
        p = os.path.join(d, "summary.json")
        if not os.path.isfile(p):
            raise Stop("summary.json 이 없다: %s" % d)
        s = json.load(open(p, encoding="utf-8"))
        s["_dir"] = d
        runs.append(s)
    base = runs[0]
    for key, name in (("ref", "측정 커밋"), ("cases", "사례 목록"), ("criteria_sha", "통과 기준 표"),
                      ("agent_body_sha", "검수 Agent 정의 본문(머리 칸 밖)")):
        diff = [r["_dir"] for r in runs if r.get(key) != base.get(key)]
        if diff:
            raise Stop("%s 이 다른 결과를 섞었다 — 같은 조건에서 바꾼 것만 비교한다(170쪽):\n  기준 %s\n  다름 %s" % (
                name, base["_dir"], "\n  다름 ".join(diff)))
    letters = [chr(ord("A") + i) for i in range(len(runs))]
    for L, r in zip(letters, runs):
        r["_L"] = L
        r["_pass"] = not r.get("run_errors") and all(v["verdict"] != "미달" for v in r["verdicts"])
    lines = ["## 측정 비교 — 측정 커밋 %s · 사례 %s" % (base["ref"][:7], ", ".join(base["cases"])), ""]
    for r in runs:
        lines.append("- %s: %s — `%s`" % (r["_L"], r["label"], r["_dir"]))
    lines += ["", "| 사례 | 규칙 | " + " | ".join("%s %s" % (r["_L"], r["label"]) for r in runs) + " |",
              "|---|---|" + "---|" * len(runs)]
    detail = [{c["case"]: c for c in r["cases_detail"]} for r in runs]
    for case in base["cases"]:
        rule = detail[0][case].get("rule") or "없음"
        lines.append("| %s | %s | %s |" % (case, rule, " | ".join(cell(d[case]) for d in detail)))
    for v0 in base["verdicts"]:
        k = v0["key"]
        vals = []
        for r in runs:
            v = next(x for x in r["verdicts"] if x["key"] == k)
            vals.append("-" if v["value"] is None else "%s %s" % (v["value"], v["verdict"]))
        lines.append("| %s | %s | %s |" % (v0["label"], v0["threshold"], " | ".join(vals)))
    lines.append("| 평균 초 | | %s |" % " | ".join(str(r.get("seconds_avg")) for r in runs))
    lines.append("| 합계 USD | | %s |" % " | ".join(usd_cell(r.get("cost_total_usd")) for r in runs))
    # 어떤 토큰이 비용을 만드는지 보이게 종류별 줄 · 토큰당 실효 비용이 보이게 1M 토큰당 실효 USD(실장 11/26)
    lines.append("| 합계 입력 토큰 | | %s |" % " | ".join(token_cell(r.get("tokens_in_total")) for r in runs))  # 옛 결과는 -
    for key, name in (("cache_read_tokens", "캐시 읽기"), ("cache_creation_tokens", "캐시 생성")):
        lines.append("| · 그중 %s | | %s |" % (name, " | ".join(token_cell(run_tokens(r, key)) for r in runs)))
    lines.append("| 합계 출력 토큰 | | %s |" % " | ".join(token_cell(r.get("tokens_out_total")) for r in runs))
    lines.append("| · 그중 thinking | | %s |" % " | ".join(token_cell(run_tokens(r, "thinking_tokens")) for r in runs))
    lines.append("| 1M 토큰당 실효 USD | | %s |" % " | ".join(
        "-" if per_million(r) is None else "%.2f" % per_million(r) for r in runs))
    lines.append("| 실제 모델 | | %s |" % " | ".join(", ".join(r.get("models") or []) for r in runs))
    lines.append("| 통과 | | %s |" % " | ".join("통과" if r["_pass"] else ("실행 오류" if r.get("run_errors") else "미달") for r in runs))
    cands = [r for r in runs if r["_pass"] and not r.get("drop_rule")]
    lines.append("")
    if cands:
        best = sorted(cands, key=lambda r: (r.get("cost_total_usd") or 0, r.get("seconds_avg") or 0))[0]
        lines.append("적용 후보: %s (%s) — 통과선을 모두 넘는 설정 가운데 비용이 가장 낮다(같으면 평균 초가 짧은 것). 고르는 사람은 나다"
                     % (best["_L"], best["label"]))
        lines.append(conclusion(runs[0], best))
    else:
        lines.append("적용 후보: 없음 — 통과선을 모두 넘은 설정이 없다. 「미달이면」 순서로 원인을 찾는다")
    lines.append("- 설정마다 한 번 잰 값이다. 통과선 바로 위(놓침 · 오탐 한 건 차이)거나 판정 불가 하나(형식 위반)로 미달이면 그 설정만 한 번 더 잰다")
    for r, d in zip(runs, detail):
        if not r.get("drop_rule"):
            continue
        same = [w for w in runs if not w.get("drop_rule") and w.get("front_model") == r.get("front_model")
                and w.get("front_effort") == r.get("front_effort")]
        lines.append("")
        if not same:
            lines.append("## Ablation — %s %s : 같은 설정의 규칙 있는 판이 없다 — 규칙을 빼지 않고 같은 설정으로 잰 폴더를 함께 준다"
                         % (r["_L"], r["label"]))
            continue
        w = sorted(same, key=lambda x: x["made"])[-1]
        wd = detail[runs.index(w)]
        lines += ["## Ablation(171쪽) — %s %s ↔ 규칙 있는 판 %s %s" % (r["_L"], r["label"], w["_L"], w["label"]), "",
                  "| 사례 | 규칙 있음 | 규칙 뺌 | 판정 |", "|---|---|---|---|"]
        counts = {}
        for case in base["cases"]:
            mark = " (뺀 규칙)" if wd[case].get("rule") == r["drop_rule"] else ""
            at = attribution(wd[case], d[case])
            if mark:
                counts[at] = counts.get(at, 0) + 1
            lines.append("| %s%s | %s | %s | %s |" % (case, mark, cell(wd[case]), cell(d[case]), at))
        lines.append("")
        lines.append("- 뺀 규칙 %s 의 사례: %s" % (r["drop_rule"], " · ".join("%s %d" % kv for kv in sorted(counts.items())) or "없음"))
        if r.get("rule_left_in"):
            lines.append("- 규칙 번호가 다른 파일에 남음: %s" % ", ".join(r["rule_left_in"]))
        lines.append("- 한 번의 차이는 원인의 확증이 아니다 — 조건을 같게 하고, 중요하면 반복한다")
    text = "\n".join(lines) + "\n"
    if not out:  # 설정을 정한 근거가 PR 에 남게 — 첫 결과 폴더 옆에 둔다
        first = os.path.abspath(dirs[0])
        out = os.path.join(os.path.dirname(first), "compare-%s.md" % "+".join(os.path.basename(os.path.abspath(d)) for d in dirs))
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(text + "표를 파일로 남겼다: %s" % out)
    return 0


# ---------------------------------------------------------------- 진입점

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent")
    ap.add_argument("--out")
    ap.add_argument("--cases")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--set-model")
    ap.add_argument("--set-effort")
    ap.add_argument("--drop-rule")
    ap.add_argument("--criteria", default=CRITERIA)
    ap.add_argument("--compare", nargs="+", metavar="결과 폴더")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args(argv)
    try:
        if a.compare:
            read_criteria(a.criteria)
            return compare_runs(a.compare, a.out)
        if not a.agent or not a.out:
            raise Stop("--agent 와 --out 을 준다(비교만 하려면 --compare)")
        with run_lock():
            return measure(a)
    except Stop as e:
        print("멈춤: %s" % e, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
