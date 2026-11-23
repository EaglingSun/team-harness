#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Judge(채점자) — 루브릭으로 PR 검수 지적의 설명(message)을 채점한다. 쓰기 전에 채점자부터 사람 판정에 맞춰 본다.

채점자 확인
  python judge.py practice --rubric <루브릭 파일> --out <결과 폴더> [--model sonnet] [--jobs 3] [--resume]
  - judge-practice/practice.json 의 연습 사례 × 루브릭 항목을 항목마다 따로 채점해 사람 판정과 비교한다(일치율 Agreement)
  - 연습 쌍마다 두 설명의 순서를 바꿔 두 번 비교해 같은 쪽을 골랐는지 본다(일관성 Consistency)
지적 채점
  python judge.py actual --rubric <루브릭 파일> --findings <run_cases.py 결과 폴더> --practice-result <practice 결과 폴더>
                  --out <결과 폴더>
  - 결과 폴더의 <사례>.json 지적마다 루브릭 항목별 합격 · 불합격 → 항목별 합격률
  - 같은 루브릭으로 채점자 확인이 통과하지 않았으면 「Judge 미달 상태」로 표시하고 종료 코드 1

Judge 호출: claude -p --tools "" · --json-schema(reason 먼저 · verdict) · --model 고정 · 빈 임시 폴더 · 설정은 project 만
  · 부모 세션의 CLAUDE* 변수를 뺀다. 프롬프트에는 루브릭 항목 · 그 규칙의 coding-rules.md 원문 줄 · 참조 사례 patch · 지적
결과: 칸마다 <결과 폴더>/cells/<칸>.json 에 바로 쓴다 — 한도 · 시간 초과로 멈추면 --resume 으로 남은 칸만 다시 부른다
출력: judge-<루브릭 이름>.json · judge-<루브릭 이름>.md
종료 코드: 0 = 모든 지표 통과 · 1 = 미달 있음 · 2 = Judge 오류 칸 · 기준 표 · 루브릭 · 연습 파일을 읽지 못함
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True  # 팀 하네스 사본 안에 __pycache__ 를 만들지 않는다(사본은 원본과 같게 둔다)
import run_cases as rcm  # noqa: E402

Stop = rcm.Stop
JUDGE_MODEL = "sonnet"
VERDICT_SET = ("합격", "불합격", "모름")
CHOICES = ("A", "B", "비김")


# ---------------------------------------------------------------- 루브릭 · 연습 사례

def parse_rubric(text):
    m = re.search(r"^판정:\s*(.+)$", text, re.M)
    if not m:
        raise Stop("루브릭에 「판정: 합격 · 불합격」 줄이 없다")
    verdicts = [v.strip() for v in m.group(1).split("·") if v.strip()]
    if not {"합격", "불합격"} <= set(verdicts) or not set(verdicts) <= set(VERDICT_SET):
        raise Stop("루브릭 판정 값은 합격 · 불합격(· 모름)이다: %s" % m.group(1))
    parts = re.split(r"^## ", text, flags=re.M)
    items, pair = {}, None
    for sec in parts[1:]:
        head, _, body = sec.partition("\n")
        head = head.strip()
        if head.startswith("항목 "):
            items[head[len("항목 "):].strip()] = body.strip()
        elif head == "쌍 비교":
            pair = body.strip()
    if not items:
        raise Stop("루브릭에 「## 항목 <이름>」 절이 없다")
    return {"verdicts": verdicts, "items": items, "pair": pair, "preamble": parts[0].strip()}


def practice_texts(practice):
    out = [(x["id"], x["message"]) for x in practice.get("items", [])]
    for q in practice.get("pairs", []):
        out += [(q["id"], q["x"]), (q["id"], q["y"])]
    return out


def rubric_leaks(text, practice):
    """루브릭이 연습 사례 · 쌍의 설명 문장을 그대로 품으면 정답을 품은 것이다 — 그 id 목록."""
    hit = []
    for pid, msg in practice_texts(practice):
        if msg.strip() and msg.strip() in text and pid not in hit:
            hit.append(pid)
    return hit


def load_practice(path, items):
    if not os.path.isfile(path):
        raise Stop("연습 사례 파일이 없다: %s" % path)
    practice = json.load(open(path, encoding="utf-8"))
    for x in practice.get("items", []):
        if sorted(x.get("human", {})) != sorted(items):
            raise Stop("연습 사례 %s 의 사람 판정 항목이 루브릭 항목(%s)과 다르다" % (x.get("id"), ", ".join(items)))
    if not practice.get("items"):
        raise Stop("연습 사례가 없다: %s" % path)
    return practice


def rule_line(rules_text, rule):
    """그 규칙의 표 행 + 상세 절(## CR-NN). 표 행이 하나가 아니면 None."""
    lines = rules_text.replace("\r\n", "\n").split("\n")
    rows, heads, section = rcm.rule_spans(lines, rule)
    if len(rows) != 1:
        return None
    parts = [lines[rows[0]].strip()]
    if section:
        parts.append("\n".join(lines[i] for i in section).strip())
    return "\n\n".join(parts)


# ---------------------------------------------------------------- 프롬프트 · 호출

SINGLE_TAIL = "이유를 먼저 쓰고 판정한다. 파일을 읽거나 도구를 쓰지 않는다. 답은 reason(이유) · verdict(판정) 두 칸이다."
PAIR_TAIL = "이유를 먼저 쓰고 A · B · 비김 가운데 하나를 고른다. 파일을 읽거나 도구를 쓰지 않는다. 답은 reason(이유) · choice(고른 것) 두 칸이다."


def context_block(rule, rline, case, patch, file, line):
    return ("[규칙 원문 — %s]\n%s\n\n[바뀐 코드 — %s change.patch]\n%s\n\n[지적 자리]\nrule: %s\nfile: %s\nline: %s\n"
            % (rule, rline, case, patch.rstrip(), rule, file, line))


def single_prompt(rub, item, ctx_text, message):
    return ("너는 PR 검수 Agent 가 남긴 지적의 설명을 채점한다. 아래 루브릭 항목 하나로만 판정한다.\n\n"
            "[루브릭]\n%s\n\n[항목 %s]\n%s\n\n판정 값: %s\n\n%s\n[채점할 설명(message)]\n%s\n\n%s"
            % (rub["preamble"], item, rub["items"][item], " · ".join(rub["verdicts"]), ctx_text, message, SINGLE_TAIL))


def pair_prompt(rub, ctx_text, a, b):
    items = "\n\n".join("[항목 %s]\n%s" % (k, v) for k, v in rub["items"].items())
    return ("너는 PR 검수 Agent 가 같은 자리에 남긴 지적 설명 두 개를 루브릭으로 비교한다.\n\n"
            "[루브릭]\n%s\n\n%s\n\n[쌍 비교]\n%s\n\n%s\n[설명 A]\n%s\n\n[설명 B]\n%s\n\n%s"
            % (rub["preamble"], items, rub["pair"] or "루브릭 항목으로 더 나은 설명을 고른다. 같으면 비김.", ctx_text, a, b, PAIR_TAIL))


def schema(kind, verdicts):
    key, enum = ("verdict", verdicts) if kind == "single" else ("choice", list(CHOICES))
    return {"type": "object", "additionalProperties": False, "required": ["reason", key],
            "properties": {"reason": {"type": "string", "minLength": 1}, key: {"type": "string", "enum": enum}}}


def find_claude():
    return rcm.find_claude()


def call_judge(exe, prompt, sch, model, env, timeout):
    """Judge 1회 — 빈 임시 폴더에서 도구 없이. (종료 코드, JSON 출력, stderr). 시험에서는 가짜로 바꾼다."""
    cwd = tempfile.mkdtemp(prefix="judge-")
    try:
        return rcm.run([exe, "-p", "--tools", "", "--no-session-persistence", "--output-format", "json",
                        "--json-schema", json.dumps(sch, ensure_ascii=False), "--model", model,
                        "--setting-sources", "project", "--strict-mcp-config"],
                       cwd, env=env, input_bytes=prompt.encode("utf-8"), timeout=timeout)
    finally:
        shutil.rmtree(cwd, ignore_errors=True)


def read_answer(stdout, kind, verdicts, model):
    try:
        w = json.loads(stdout)
    except ValueError as e:
        return {"ok": False, "error": "claude 출력이 JSON 이 아니다: %s" % e}
    if not isinstance(w, dict) or w.get("is_error"):
        return {"ok": False, "error": "claude 오류: %s" % str(w)[:200]}
    models = sorted((w.get("modelUsage") or {}).keys())
    base = {"model": ", ".join(models), "cost_usd": w.get("total_cost_usd")}
    if not any(rcm.model_matches(model, m) for m in models):
        return dict(base, ok=False, error="실제 모델 %s 이 --model %s 와 다르다" % (base["model"], model))
    so = w.get("structured_output")
    if not isinstance(so, dict):
        return dict(base, ok=False, error="구조화 답(structured_output)이 없다")
    reason = so.get("reason")
    key, allowed = ("verdict", verdicts) if kind == "single" else ("choice", CHOICES)
    val = so.get(key)
    if not isinstance(reason, str) or not reason.strip() or val not in allowed:
        return dict(base, ok=False, error="스키마 밖 답: %s" % json.dumps(so, ensure_ascii=False)[:200])
    return dict(base, ok=True, reason=reason.strip(), **{key: val})


def run_cells(jobs_list, a, out_dir, verdicts, env, exe):
    """jobs_list: (칸 id, 종류, 프롬프트 또는 None(오류 사유)). 칸마다 cells/<id>.json 에 쓴다."""
    cells_dir = os.path.join(out_dir, "cells")
    os.makedirs(cells_dir, exist_ok=True)
    results = {}
    todo = []
    for cid, kind, prompt, err in jobs_list:
        path = os.path.join(cells_dir, cid + ".json")
        psha = hashlib.sha256((prompt or err or "").encode("utf-8")).hexdigest()
        if a.resume and os.path.isfile(path):
            old = json.load(open(path, encoding="utf-8"))
            if old.get("ok") and old.get("prompt_sha") == psha:
                results[cid] = old
                continue
        if prompt is None:
            results[cid] = {"id": cid, "kind": kind, "ok": False, "error": err, "prompt_sha": psha}
            json.dump(results[cid], open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            continue
        todo.append((cid, kind, prompt, psha, path))

    def one(job):
        cid, kind, prompt, psha, path = job
        t0 = time.time()
        try:
            rc, so, se = call_judge(exe, prompt, schema(kind, verdicts), a.model, env, a.timeout)
            ans = read_answer(so, kind, verdicts, a.model) if rc == 0 else \
                {"ok": False, "error": "claude 종료 코드 %s: %s" % (rc, (se or so).strip()[:200])}
        except subprocess.TimeoutExpired:
            ans = {"ok": False, "error": "시간 초과(%d초)" % a.timeout}
        except Exception as e:
            ans = {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:200])}
        ans.update({"id": cid, "kind": kind, "prompt_sha": psha, "seconds": round(time.time() - t0, 1)})
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(ans, fh, ensure_ascii=False, indent=1)
        return cid, ans

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        for cid, ans in ex.map(one, todo):
            results[cid] = ans
            print("%s %s%s" % (cid, ans.get("verdict") or ans.get("choice") or "-",
                               "" if ans["ok"] else " 오류=" + ans["error"]), flush=True)
    return results


# ---------------------------------------------------------------- 지표

def practice_metrics(practice, items, cells, pairs):
    total = agree = always = unknown = errors = 0
    split = []
    per_item = {k: [0, 0] for k in items}
    for x in practice["items"]:
        for k in items:
            total += 1
            per_item[k][1] += 1
            human = x["human"][k]
            always += 1 if human == "합격" else 0
            c = cells.get("%s.%s" % (x["id"], k))
            if c and not c.get("ok"):
                errors += 1
            got = c.get("verdict") if c and c.get("ok") else None
            if got == "모름":
                unknown += 1
            if got == human:
                agree += 1
                per_item[k][0] += 1
            else:
                split.append({"id": x["id"], "item": k, "human": human, "judge": got or "오류",
                              "reason": (c or {}).get("reason") or (c or {}).get("error") or "칸 없음"})
    pair_rows, consistent = [], 0
    for q in practice.get("pairs", []):
        c1, c2 = pairs.get(q["id"] + ".xy"), pairs.get(q["id"] + ".yx")
        for c in (c1, c2):
            if c and not c.get("ok"):
                errors += 1
        m1 = {"A": "x", "B": "y", "비김": "tie"}.get(c1.get("choice")) if c1 and c1.get("ok") else None
        m2 = {"A": "y", "B": "x", "비김": "tie"}.get(c2.get("choice")) if c2 and c2.get("ok") else None
        same = m1 is not None and m1 == m2
        consistent += 1 if same else 0
        pair_rows.append({"id": q["id"], "x_first": m1 or "오류", "y_first": m2 or "오류", "same": same, "human": q.get("human")})
    npairs = len(practice.get("pairs", []))
    return {"agreement": round(agree / total, 4) if total else None,
            "always_pass": round(always / total, 4) if total else None,
            "consistency": round(consistent / npairs, 4) if npairs else None,
            "unknown": unknown, "judge_errors": errors,
            "per_item": {k: round(v[0] / v[1], 4) if v[1] else None for k, v in per_item.items()},
            "split": split, "pairs": pair_rows}


# ---------------------------------------------------------------- 실행

def prepare(a):
    crit = rcm.read_criteria(a.criteria)
    with open(a.rubric, "rb") as fh:
        rubric_raw = fh.read()
    rub = parse_rubric(rubric_raw.decode("utf-8"))
    out = os.path.abspath(a.out)
    if os.path.isdir(out) and os.listdir(out) and not a.resume:
        raise Stop("결과 폴더가 이미 있다 — 남은 칸만 이어 돌리려면 --resume, 새로 하려면 새 폴더: %s" % out)
    os.makedirs(out, exist_ok=True)
    if not os.path.isfile(a.rules):
        raise Stop("팀 코딩 규칙 파일이 없다: %s" % a.rules)
    rules_text = open(a.rules, encoding="utf-8").read()
    return crit, rub, hashlib.sha256(rubric_raw).hexdigest(), out, rules_text


def ctx_for(a, rules_text, case, rule, file, line):
    rline = rule_line(rules_text, rule)
    if rline is None:
        return None, "규칙 원문을 찾지 못했다: %s" % rule
    patch_path = os.path.join(a.cases_dir, case, "change.patch")
    if not os.path.isfile(patch_path):
        return None, "참조 사례 patch 가 없다: %s" % patch_path
    patch = open(patch_path, encoding="utf-8").read()
    return context_block(rule, rline, case, patch, file, line), None


def finish(a, out, stem, mode, rub_sha, crit, metrics, keys, cells, extra_md, extra_ok=True, note=None):
    verdicts = rcm.judge_metrics(crit, metrics, keys)
    code = 2 if metrics.get("judge_errors") else (1 if any(v["verdict"] == "미달" for v in verdicts) or not extra_ok else 0)
    cost = round(sum((c.get("cost_usd") or 0) for c in cells.values()), 4)
    models = sorted({c["model"] for c in cells.values() if c.get("model")})
    res = {"made": datetime.datetime.now().strftime("%Y%m%d-%H%M%S"), "mode": mode, "rubric": os.path.abspath(a.rubric),
           "rubric_sha": rub_sha, "model": a.model, "models": models, "metrics": metrics, "verdicts": verdicts,
           "status": "통과" if code == 0 else ("오류" if code == 2 else "미달"), "note": note,
           "cost_total_usd": cost, "exit_code": code, "cells": cells}
    with open(os.path.join(out, "judge-%s.json" % stem), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    md = ["# Judge %s — %s" % (mode, os.path.basename(a.rubric)), "",
          "- Judge 모델 %s(실제 %s) · 칸 %d · 비용 %s USD" % (a.model, ", ".join(models) or "-", len(cells), cost)]
    if note:
        md.append("- %s" % note)
    md += ["", "| 지표 | 값 | 통과선 | 판정 |", "|---|---|---|---|"]
    md += ["| %s | %s | %s | %s |" % (v["label"], "-" if v["value"] is None else v["value"], v["threshold"], v["verdict"]) for v in verdicts]
    md += [""] + extra_md
    with open(os.path.join(out, "judge-%s.md" % stem), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(md) + "\n")
    print("\n".join(md))
    print("종료 코드 %d · 결과 %s" % (code, os.path.join(out, "judge-%s.json" % stem)))
    return code


def practice_mode(a):
    crit, rub, rub_sha, out, rules_text = prepare(a)
    rcm.require_rows(crit, ["agreement", "consistency", "judge_errors"])
    items = list(rub["items"])
    practice = load_practice(a.practice, items)
    leak = rubric_leaks(open(a.rubric, encoding="utf-8").read(), practice)
    if leak:
        raise Stop("루브릭이 연습 문장을 그대로 품고 있다(%s) — 경계 예시는 연습 사례와 다른 문장으로 쓴다" % ", ".join(leak))
    jobs = []
    for x in practice["items"]:
        ctx, err = ctx_for(a, rules_text, x["case"], x["rule"], x["file"], x["line"])
        for k in items:
            jobs.append(("%s.%s" % (x["id"], k), "single", single_prompt(rub, k, ctx, x["message"]) if ctx else None, err))
    for q in practice.get("pairs", []):
        ctx, err = ctx_for(a, rules_text, q["case"], q["rule"], q["file"], q["line"])
        jobs.append((q["id"] + ".xy", "pair", pair_prompt(rub, ctx, q["x"], q["y"]) if ctx else None, err))
        jobs.append((q["id"] + ".yx", "pair", pair_prompt(rub, ctx, q["y"], q["x"]) if ctx else None, err))
    print("연습 사례 %d × 항목 %d + 쌍 %d × 순서 2 · Judge 모델 %s" % (len(practice["items"]), len(items),
                                                             len(practice.get("pairs", [])), a.model), flush=True)
    res = run_cells(jobs, a, out, rub["verdicts"], rcm.clean_env(), find_claude())
    cells = {k: v for k, v in res.items() if v.get("kind") == "single"}
    pairs = {k: v for k, v in res.items() if v.get("kind") == "pair"}
    m = practice_metrics(practice, items, cells, pairs)
    md = ["- 「늘 합격만 주는 채점자」의 일치율 %s — 일치율 하나만 보지 않는다(166쪽)" % m["always_pass"],
          "- 항목별 일치율: %s · 「모름」 %d · 오류 칸 %d" % (" · ".join("%s %s" % kv for kv in m["per_item"].items()), m["unknown"], m["judge_errors"]),
          "", "갈린 칸 — 사람 판정과 다른 것(166쪽 ③ 이 칸을 읽고 루브릭 문장을 고친다)", "",
          "| 연습 사례 | 항목 | 사람 | Judge | Judge 이유 |", "|---|---|---|---|---|"]
    md += ["| %s | %s | %s | %s | %s |" % (s["id"], s["item"], s["human"], s["judge"], s["reason"].replace("|", "/")[:160]) for s in m["split"]] or []
    if not m["split"]:
        md.append("| - | - | - | - | 갈린 칸 없음 |")
    md += ["", "쌍 비교 — 순서를 바꿔도 같은 쪽을 골랐나(x · y 는 연습 쌍의 두 설명)", "",
           "| 연습 쌍 | x 를 A 로 | y 를 A 로 | 같음 | 사람이 고른 쪽 |", "|---|---|---|---|---|"]
    md += ["| %s | %s | %s | %s | %s |" % (p["id"], p["x_first"], p["y_first"], "같음" if p["same"] else "다름", p["human"]) for p in m["pairs"]]
    metrics = {k: m[k] for k in ("agreement", "consistency", "judge_errors", "always_pass", "unknown", "per_item")}
    metrics.update({"split": m["split"], "pairs": m["pairs"]})
    return finish(a, out, os.path.splitext(os.path.basename(a.rubric))[0], "practice", rub_sha, crit, metrics,
                  ["agreement", "consistency", "judge_errors"], res, md)


def actual_mode(a):
    crit, rub, rub_sha, out, rules_text = prepare(a)
    rcm.require_rows(crit, ["rubric_pass", "judge_errors"])
    if not a.findings or not os.path.isdir(a.findings):
        raise Stop("--findings 에 run_cases.py 결과 폴더를 준다")
    items = list(rub["items"])
    judge_ok, note = False, None
    pr = os.path.join(a.practice_result or "", "judge-%s.json" % os.path.splitext(os.path.basename(a.rubric))[0])
    if a.practice_result and os.path.isfile(pr):
        p = json.load(open(pr, encoding="utf-8"))
        judge_ok = p.get("mode") == "practice" and p.get("rubric_sha") == rub_sha and p.get("status") == "통과"
    if not judge_ok:
        note = "Judge 미달 상태 — 같은 루브릭으로 한 채점자 확인(judge.py practice)이 통과하지 않았다. 이 합격률을 믿지 않는다"
    jobs, found = [], []
    for name in sorted(os.listdir(a.findings)):
        if not re.match(r"^case-[^.]+\.json$", name):
            continue
        case = name[:-5]
        data = json.load(open(os.path.join(a.findings, name), encoding="utf-8"))
        for i, f in enumerate(data.get("findings", []), 1):
            found.append((case, i, f))
            ctx, err = ctx_for(a, rules_text, case, f["rule"], f["file"], f["line"])
            for k in items:
                jobs.append(("%s.%d.%s" % (case, i, k), "single", single_prompt(rub, k, ctx, f["message"]) if ctx else None, err))
    if not found:
        raise Stop("채점할 지적이 없다: %s" % a.findings)
    print("지적 %d × 항목 %d · Judge 모델 %s" % (len(found), len(items), a.model), flush=True)
    res = run_cells(jobs, a, out, rub["verdicts"], rcm.clean_env(), find_claude())
    metrics = {"judge_errors": sum(1 for c in res.values() if not c.get("ok"))}
    md = ["| 지적 | rule | " + " | ".join(items) + " | message |", "|---|---|" + "---|" * len(items) + "---|"]
    rates = {}
    for k in items:
        passed = sum(1 for case, i, f in found if res.get("%s.%d.%s" % (case, i, k), {}).get("verdict") == "합격")
        rates[k] = round(passed / len(found), 4)
    for case, i, f in found:
        vals = [res["%s.%d.%s" % (case, i, k)].get("verdict") or "오류" for k in items]
        md.append("| %s #%d | %s | %s | %s |" % (case, i, f["rule"], " | ".join(vals), f["message"].replace("|", "/")[:120]))
    metrics["per_item"] = rates
    code = None
    verdict_keys = []
    for k in items:  # 루브릭 항목마다 같은 통과선
        metrics["rubric_pass_" + k] = rates[k]
        crit["thresholds"]["rubric_pass_" + k] = dict(crit["thresholds"]["rubric_pass"], label="루브릭 합격률 — " + k)
        verdict_keys.append("rubric_pass_" + k)
    code = finish(a, out, os.path.splitext(os.path.basename(a.rubric))[0], "actual", rub_sha, crit, metrics,
                  verdict_keys + ["judge_errors"], res, md, extra_ok=judge_ok, note=note)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("practice", "actual"))
    ap.add_argument("--rubric", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=JUDGE_MODEL)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--practice", default=os.path.join(HERE, "judge-practice", "practice.json"))
    ap.add_argument("--findings")
    ap.add_argument("--practice-result")
    ap.add_argument("--rules", default=os.path.join(os.path.dirname(HERE), "coding-rules.md"))
    ap.add_argument("--cases-dir", default=HERE)
    ap.add_argument("--criteria", default=os.path.join(HERE, "eval-criteria.md"))
    a = ap.parse_args(argv)
    try:
        return practice_mode(a) if a.mode == "practice" else actual_mode(a)
    except Stop as e:
        print("멈춤: %s" % e, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
