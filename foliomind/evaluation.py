"""Evaluate a transparent keyword baseline on the N0 manifest without network access."""

import argparse
import json
from pathlib import Path
from time import perf_counter

from .documents import extract
from .library import Source, currently_authorized


COURSE_TERMS = {
    "计算机网络": ("拥塞", "tcp", "ack", "arp", "以太网", "dns", "路由"),
    "数据库原理": ("事务", "幻读", "回滚", "快照", "查询计划", "索引"),
    "软件工程": ("需求基线", "需求追踪", "验收条件", "变更控制", "评审"),
    "人机交互": ("可用性", "键盘导航", "焦点", "人机交互", "任务走查"),
}
PURPOSE_TERMS = {
    "实验报告": ("本实验", "实验报告", "本报告", "观察结果", "用例"),
    "学习笔记": ("笔记", "记录", "复习", "摘记"),
    "课件": ("第二讲", "课件"),
}


def score_terms(text, rules):
    ranked = sorted(((sum(term in text for term in terms), name) for name, terms in rules.items()), reverse=True)
    if not ranked or not ranked[0][0]:
        return None, True
    close = len(ranked) > 1 and ranked[1][0] > 0 and ranked[0][0] - ranked[1][0] <= 1
    return None if close and ranked[0][0] == ranked[1][0] else ranked[0][1], close


def baseline(doc, courses):
    text = (doc.path.stem + "\n" + "\n".join(segment.text for segment in doc.segments)).casefold()
    rules = {course: COURSE_TERMS.get(course, (course.casefold(),)) for course in courses}
    course, review = score_terms(text, rules)
    purpose, _ = score_terms(text, PURPOSE_TERMS)
    return {"primary_course": course, "purpose": purpose, "needs_review": review}


def evaluate(manifest, pool):
    reference = json.loads(manifest.read_text(encoding="utf-8"))
    root_source = Source.directory(manifest.parent / reference["import_root"],
                                   exclusions=tuple(reference["default_case"]["exclude_directories"]))
    rows = []
    start = perf_counter()
    for sample in reference["samples"]:
        if sample["set"] != pool or "human_reference" not in sample:
            continue
        path = root_source.path / sample["path"]
        if not currently_authorized(path, (root_source,)):
            continue
        doc = extract(path)
        output = baseline(doc, reference["optional_course_list"])
        expected = sample["human_reference"]
        rows.append({"sample": sample["id"], "status": doc.status, "expected": expected, "baseline": output})
    return {
        "set": pool, "evaluated": len(rows),
        "course_matches": sum(r["expected"]["primary_course"] == r["baseline"]["primary_course"] for r in rows),
        "purpose_matches": sum(r["expected"]["purpose"] == r["baseline"]["purpose"] for r in rows),
        "review_matches": sum(r["expected"]["needs_review"] == r["baseline"]["needs_review"] for r in rows),
        "elapsed_seconds": round(perf_counter() - start, 3),
        "real_model": "not_run",
        "samples": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--set", choices=("development", "holdout"), default="holdout")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.manifest.resolve(), args.set), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
