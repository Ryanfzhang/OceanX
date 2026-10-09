#!/usr/bin/env python3
"""Read the final answers of one or more arms against what each question asks for.

This is the independent reading the learning step uses (src/oceanx/research/referee.py), applied
to test attempts with the model and key of benchmarking/.env. The model sees a question and a
final answer and nothing else: no research tree, no rubric, no reference. It is not a score.
Per answer it counts what the question asks for and the answer does not give, conclusions
stronger than their support, and superseded numbers still used.

Every arm is read against one list per question, kept under --out/asked, so an arm run later is
read against the same list. A reading that exists is not made again.

About one finding in three is wrong (hand check of 2026-10-09). Compare arms on the counts, and
check by hand the findings a conclusion rests on.

Example: python benchmarking/server/read_answers.py \\
             --runs <RUNS>/OceanX <RUNS>/OceanX-L1 --out <ROOT>/<EXP>/readings
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

COUNTS = ("asked", "not_given", "overclaims", "superseded")


def latest_attempts(arm_dir: Path):
    """The latest attempt of every question of an arm, as evaluate.py takes them."""
    for case in sorted(p for p in arm_dir.iterdir() if p.is_dir() and (p.name[:1] in "QE")):
        attempts = sorted(case.glob("attempt-*/result.json"))
        if attempts:
            yield case.name, attempts[-1].parent


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def counts(reading: dict) -> dict:
    return {"asked": sum(entry["status"] != "unread" for entry in reading["asked"]),
            "not_given": sum(entry["status"] in ("partly", "no") for entry in reading["asked"]),
            "overclaims": len(reading["overclaims"]), "superseded": len(reading["superseded"])}


def read_runs(runs: list[Path], out: Path, llm, *, parallel: int = 4) -> dict:
    """Read every arm's latest answers; returns the counts per question and arm."""
    from oceanx.research.referee import MIN_ANSWER_CHARS, asked_items, read_answer
    cases, arms, skipped = [], [], []
    for arm_dir in (Path(run).expanduser().resolve() for run in runs):
        arm = json.loads((arm_dir / "arm.json").read_text(encoding="utf-8"))["arm"]
        arms.append(arm)
        for task_id, attempt in latest_attempts(arm_dir):
            try:
                question = json.loads((attempt / "query.json").read_text(encoding="utf-8"))["query"]
                answer = (attempt / "answer.md").read_text(encoding="utf-8", errors="replace")
            except (OSError, KeyError, json.JSONDecodeError):
                question, answer = "", ""
            if not question.strip() or len(answer.strip()) < MIN_ANSWER_CHARS:
                skipped.append({"arm": arm, "task_id": task_id, "reason": "no question or no final answer"})
                continue
            cases.append({"arm": arm, "task_id": task_id, "attempt": str(attempt),
                          "question": question, "answer": answer})

    # One list per question, made from the question alone before any answer is read.
    asked, failed, listed = {}, [], set()
    for case in cases:
        task_id, path = case["task_id"], out / "asked" / f"{case['task_id']}.json"
        if task_id in listed:
            continue
        listed.add(task_id)
        saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if saved.get("question") == case["question"]:
            asked[task_id] = saved["asked"]
            continue
        try:
            asked[task_id] = asked_items(case["question"], llm)
        except ValueError as exc:
            failed.append({"arm": None, "task_id": task_id, "reason": str(exc)[:300]})
            continue
        write_json(path, {"question": case["question"], "asked": asked[task_id]})

    def read(case: dict) -> dict | None:
        path = out / case["arm"] / f"{case['task_id']}.json"
        if path.is_file():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("attempt") == case["attempt"]:
                return saved
        reading = {"arm": case["arm"], "task_id": case["task_id"], "attempt": case["attempt"],
                   **read_answer(case["question"], asked[case["task_id"]], case["answer"], llm)}
        write_json(path, reading)
        return reading

    def try_read(case: dict):
        try:
            return case, read(case), None
        except ValueError as exc:
            return case, None, str(exc)[:300]

    table: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(parallel, 1)) as pool:
        for case, reading, error in pool.map(try_read, [c for c in cases if c["task_id"] in asked]):
            if reading is None:
                failed.append({"arm": case["arm"], "task_id": case["task_id"], "reason": error})
            else:
                table.setdefault(case["task_id"], {})[case["arm"]] = counts(reading)

    # Totals over the questions every arm has a reading for, so the arms are compared like with like.
    shared = sorted(task_id for task_id, row in table.items() if all(arm in row for arm in arms))
    totals = {arm: {key: sum(table[task_id][arm][key] for task_id in shared) for key in COUNTS}
              for arm in arms}
    result = {"arms": arms, "questions_read_in_every_arm": shared, "totals": totals,
              "by_question": {task_id: table[task_id] for task_id in sorted(table)},
              "skipped": skipped, "failed": failed}
    write_json(out / "readings.json", result)
    (out / "readings.md").write_text(page(result), encoding="utf-8")
    return result


def page(result: dict) -> str:
    arms = result["arms"]
    lines = ["# Final answers read against their questions", "",
             "Counts from a model that saw only each question and final answer. Not a score: about one",
             "finding in three is wrong, so check by hand the findings a conclusion rests on. Each cell is",
             "asked / not given or partial / conclusions stronger than their support / superseded numbers",
             "still used.", "",
             "| Question | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]

    def cell(row: dict | None) -> str:
        return " / ".join(str(row[key]) for key in COUNTS) if row else "not read"

    for task_id, row in result["by_question"].items():
        lines.append(f"| {task_id} | " + " | ".join(cell(row.get(arm)) for arm in arms) + " |")
    lines.append(f"| Total over the {len(result['questions_read_in_every_arm'])} questions read in every arm | "
                 + " | ".join(cell(result["totals"][arm]) for arm in arms) + " |")
    for name in ("skipped", "failed"):
        if result[name]:
            lines += ["", f"{name.capitalize()}:"] + [
                f"- {item['task_id']} ({item['arm'] or 'its list'}): {item['reason']}" for item in result[name]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=Path, nargs="+", required=True, help="Arm output folders (with arm.json)")
    parser.add_argument("--out", type=Path, required=True, help="Folder for the lists, the readings and the table")
    parser.add_argument("--parallel", type=int, default=4, help="Answers read at the same time")
    args = parser.parse_args(argv)
    from benchmark_models import install_oceanx_models
    install_oceanx_models()
    from oceanx.research.llm import default_llm
    result = read_runs(args.runs, args.out.expanduser().resolve(), default_llm("meta"), parallel=args.parallel)
    print(json.dumps({key: result[key] for key in ("arms", "totals", "skipped", "failed")},
                     ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
