#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR 검수 Agent 측정 — 사례의 기대 지적(expected.json)과 Agent 가 낸 지적 JSON 을 비교한다.

Agent 의 지적 JSON 은 review-rules.md 2절 형식이다: {"findings": [{rule, file, line, category, severity, message}, ...]}
비교 키는 판정(PASS · FAIL)이 아니라 지적이다 — 규칙 번호가 같고, 파일이 같고, 줄이 기대 범위 안이면 일치.

실행
  python compare.py <사례 폴더>/expected.json <Agent 지적 JSON 파일>      사례 하나
  python compare.py --cases <사례들이 든 폴더> --actual <Agent 지적 JSON 폴더>
                                                     사례 전부 — Agent 지적 JSON 은 <사례 이름>.json 으로 둔다
출력: 사례마다 일치 · 놓침 · 오탐 수와 그 지적. 마지막 줄은 합계.
종료 코드: 0 = 놓침 · 오탐 없음 / 1 = 놓침이나 오탐이 있음 / 2 = 판정 불가(파일이 없거나 형식이 다름)
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FIELDS = ("rule", "file", "line", "category", "severity", "message")


class CannotJudge(Exception):
    """비교할 수 없다 — 파일이 없거나 형식이 다르다. 결과를 일치로 세지 않는다."""


def load_json(path, what):
    if not os.path.isfile(path):
        raise CannotJudge("%s 파일이 없다: %s" % (what, path))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    try:
        return json.loads(text)
    except ValueError as e:
        raise CannotJudge("%s 가 JSON 이 아니다(%s): %s" % (what, e, path))


def load_actual(path):
    data = load_json(path, "Agent 지적")
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise CannotJudge('Agent 지적이 {"findings": [...]} 형식이 아니다: %s' % path)
    for i, f in enumerate(data["findings"]):
        missing = [k for k in FIELDS if k not in f] if isinstance(f, dict) else list(FIELDS)
        if missing:
            raise CannotJudge("Agent 지적 %d 번째에 칸이 없다(%s): %s" % (i + 1, ", ".join(missing), path))
        if not isinstance(f["line"], int):
            raise CannotJudge("Agent 지적 %d 번째의 line 이 정수가 아니다: %s" % (i + 1, path))
    return data["findings"]


def norm(path):
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def places(exp):
    """기대 지적 하나가 인정하는 (파일, 줄 범위) 목록."""
    out = [(norm(exp["file"]), exp["lines"][0], exp["lines"][1])]
    for alt in exp.get("also", []):
        out.append((norm(alt["file"]), alt["lines"][0], alt["lines"][1]))
    return out


def matches(exp, f):
    if f["rule"] != exp["rule"]:
        return False
    return any(norm(f["file"]) == fp and lo <= f["line"] <= hi for fp, lo, hi in places(exp))


def compare_one(expected_path, actual_path):
    expected = load_json(expected_path, "기대 지적")
    exp_list = expected.get("findings")
    if not isinstance(exp_list, list):
        raise CannotJudge('기대 지적이 {"findings": [...]} 형식이 아니다: %s' % expected_path)
    actual = load_actual(actual_path)
    hit = [False] * len(exp_list)
    false_pos = []
    for f in actual:
        found = False
        for i, exp in enumerate(exp_list):
            if matches(exp, f):
                hit[i] = True  # 같은 기대에 여러 지적이 맞아도 일치 1건이다
                found = True
                break
        if not found:
            false_pos.append(f)
    missed = [exp_list[i] for i, h in enumerate(hit) if not h]
    return {"name": expected.get("case", os.path.basename(os.path.dirname(expected_path))),
            "match": sum(hit), "missed": missed, "false_pos": false_pos}


def show(r):
    print("[%s] 일치 %d · 놓침 %d · 오탐 %d" % (r["name"], r["match"], len(r["missed"]), len(r["false_pos"])))
    for e in r["missed"]:
        print("  놓침 %s %s:%d-%d" % (e["rule"], e["file"], e["lines"][0], e["lines"][1]))
    for f in r["false_pos"]:
        print("  오탐 %s %s:%d %s" % (f["rule"], f["file"], f["line"], f["message"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("expected", nargs="?")
    ap.add_argument("actual", nargs="?")
    ap.add_argument("--cases")
    ap.add_argument("--actual-dir", "--actual", dest="actual_dir")
    a = ap.parse_args()

    if a.cases:
        if not a.actual_dir:
            ap.error("--cases 에는 --actual 폴더가 필요하다")
        names = sorted(n for n in os.listdir(a.cases)
                       if os.path.isfile(os.path.join(a.cases, n, "expected.json")))
        if not names:
            print("판정 불가: 사례가 없다 — %s" % a.cases)
            return 2
        pairs = [(n, os.path.join(a.cases, n, "expected.json"), os.path.join(a.actual_dir, n + ".json"))
                 for n in names]
    elif a.expected and a.actual:
        pairs = [(None, a.expected, a.actual)]
    else:
        ap.error("expected.json 과 Agent 지적 JSON, 또는 --cases 와 --actual 을 준다")

    total = {"match": 0, "missed": 0, "false_pos": 0, "cannot": 0}
    for name, exp_path, act_path in pairs:
        try:
            r = compare_one(exp_path, act_path)
        except CannotJudge as e:
            print("[%s] 판정 불가: %s" % (name or exp_path, e))
            total["cannot"] += 1
            continue
        show(r)
        total["match"] += r["match"]
        total["missed"] += len(r["missed"])
        total["false_pos"] += len(r["false_pos"])

    print("합계: 사례 %d · 일치 %d · 놓침 %d · 오탐 %d · 판정 불가 %d"
          % (len(pairs), total["match"], total["missed"], total["false_pos"], total["cannot"]))
    if total["cannot"]:
        return 2
    return 1 if (total["missed"] or total["false_pos"]) else 0


if __name__ == "__main__":
    sys.exit(main())
