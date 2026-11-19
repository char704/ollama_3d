"""Evaluate Ollama routing and selection without executing Blender workflows."""

import argparse
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.run import (  # noqa: E402
    ROUTER_SCHEMA,
    ROUTER_SYSTEM,
    SELECTOR_SYSTEM,
    OllamaClient,
    build_selection_request,
    retrieve_candidates,
)

DEFAULT_MODELS = ("qwen3.5:4b", "qwen3.5:0.8b")


def load_cases(path):
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not all(key in case for key in ("id", "prompt", "expected")):
            raise ValueError(f"{path}:{line_number}: id, prompt and expected are required")
        cases.append(case)
    if len(cases) != 30:
        raise ValueError(f"Expected exactly 30 evaluation cases, found {len(cases)}")
    return cases


def _same_value(expected, actual):
    if isinstance(expected, str) and isinstance(actual, str):
        if "/" in expected or "\\" in expected:
            return expected.replace("\\", "/").rstrip("/").casefold() == actual.replace(
                "\\", "/"
            ).rstrip("/").casefold()
    return expected == actual


def _normalized(value):
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, str) and ("/" in value or "\\" in value):
        return value.replace("\\", "/").rstrip("/").casefold()
    return value


def _field_scores(expected, actual, prefix=""):
    scores = []
    if isinstance(expected, dict):
        actual_dict = actual if isinstance(actual, dict) else {}
        for key, value in expected.items():
            name = f"{prefix}.{key}" if prefix else key
            scores.extend(_field_scores(value, actual_dict.get(key), name))
    else:
        scores.append({"field": prefix, "correct": _same_value(expected, actual)})
    return scores


def _call_with_retry(client, attempts, **kwargs):
    errors = []
    started = time.perf_counter()
    for attempt in range(attempts):
        try:
            value, metadata = client.structured(**kwargs)
            return value, metadata, attempt, time.perf_counter() - started, errors
        except Exception as exc:  # Evaluation must record model/protocol failures.
            errors.append(f"{type(exc).__name__}: {exc}")
    return None, None, max(0, attempts - 1), time.perf_counter() - started, errors


def evaluate_case(client, model, case, attempts=2):
    started = time.perf_counter()
    expected = case["expected"]
    router, router_meta, router_retries, router_seconds, router_errors = _call_with_retry(
        client,
        attempts,
        model=model,
        system=ROUTER_SYSTEM,
        user=case["prompt"],
        schema=ROUTER_SCHEMA,
        role="router",
    )
    actual_intent = router.get("intent") if isinstance(router, dict) else None
    record = {
        "id": case["id"],
        "prompt": case["prompt"],
        "expected": expected,
        "actual": {"intent": actual_intent, "capability_id": None, "selection": None},
        "scores": {
            "intent": actual_intent == expected["intent"],
            "capability": None,
            "parameter_exact": None,
            "parameter_fields": [],
            "json_valid": router is not None,
        },
        "retries": router_retries,
        "latency_seconds": {"router": round(router_seconds, 4), "selector": None},
        "metadata": {"router": router_meta, "selector": None},
        "errors": router_errors,
    }
    if actual_intent in ("run_operator", "run_workflow"):
        candidates = retrieve_candidates(case["prompt"], actual_intent, limit=5)
        if candidates:
            schema, prompt = build_selection_request(case["prompt"], actual_intent, candidates)
            selection, selector_meta, retries, seconds, errors = _call_with_retry(
                client,
                attempts,
                model=model,
                system=SELECTOR_SYSTEM,
                user=prompt,
                schema=schema,
                role="selector",
            )
            record["retries"] += retries
            record["latency_seconds"]["selector"] = round(seconds, 4)
            record["metadata"]["selector"] = selector_meta
            record["errors"].extend(errors)
            record["scores"]["json_valid"] = record["scores"]["json_valid"] and selection is not None
            if isinstance(selection, dict):
                record["actual"]["capability_id"] = selection.get("candidate_id")
                payload_key = "params" if actual_intent == "run_operator" else "inputs"
                if actual_intent == "run_operator":
                    actual_payload = {
                        "params": selection.get("params", {}),
                        "model_path": selection.get("model_path"),
                        "output_dir": selection.get("output_dir"),
                    }
                else:
                    actual_payload = {payload_key: selection.get(payload_key, {})}
                record["actual"]["selection"] = actual_payload
    if expected["capability_id"] is not None:
        record["scores"]["capability"] = (
            record["actual"]["capability_id"] == expected["capability_id"]
        )
        record["scores"]["parameter_fields"] = _field_scores(
            expected["selection"], record["actual"]["selection"]
        )
        record["scores"]["parameter_exact"] = _normalized(
            expected["selection"]
        ) == _normalized(record["actual"]["selection"])
    record["latency_seconds"]["total"] = round(time.perf_counter() - started, 4)
    return record


def _percent(numerator, denominator):
    return round(100.0 * numerator / denominator, 2) if denominator else None


def summarize(model, records):
    intent = [item["scores"]["intent"] for item in records]
    capability = [
        item["scores"]["capability"]
        for item in records
        if item["scores"]["capability"] is not None
    ]
    parameter_exact = [
        item["scores"]["parameter_exact"]
        for item in records
        if item["scores"]["parameter_exact"] is not None
    ]
    fields = [
        field["correct"]
        for item in records
        for field in item["scores"]["parameter_fields"]
    ]
    latencies = [item["latency_seconds"]["total"] for item in records]
    sorted_latencies = sorted(latencies)
    p95_index = max(0, math.ceil(0.95 * len(sorted_latencies)) - 1)
    json_valid = [item["scores"]["json_valid"] for item in records]
    expected_intents = sorted({item["expected"]["intent"] for item in records})
    intent_by_expected = {}
    confusion = {}
    for expected_intent in expected_intents:
        subset = [item for item in records if item["expected"]["intent"] == expected_intent]
        correct = sum(item["scores"]["intent"] for item in subset)
        intent_by_expected[expected_intent] = {
            "correct": correct,
            "total": len(subset),
            "percent": _percent(correct, len(subset)),
        }
        confusion[expected_intent] = {}
        for item in subset:
            actual = item["actual"]["intent"] or "error"
            confusion[expected_intent][actual] = confusion[expected_intent].get(actual, 0) + 1
    return {
        "model": model,
        "cases": len(records),
        "intent_accuracy": {"correct": sum(intent), "total": len(intent), "percent": _percent(sum(intent), len(intent))},
        "intent_accuracy_by_expected": intent_by_expected,
        "intent_confusion": confusion,
        "capability_accuracy": {"correct": sum(capability), "total": len(capability), "percent": _percent(sum(capability), len(capability))},
        "parameter_accuracy": {"correct": sum(fields), "total": len(fields), "percent": _percent(sum(fields), len(fields))},
        "exact_parameter_sets": {"correct": sum(parameter_exact), "total": len(parameter_exact), "percent": _percent(sum(parameter_exact), len(parameter_exact))},
        "valid_json": {"correct": sum(json_valid), "total": len(json_valid), "percent": _percent(sum(json_valid), len(json_valid))},
        "error_retries": sum(item["retries"] for item in records),
        "latency_seconds": {
            "mean": round(statistics.mean(latencies), 4),
            "median": round(statistics.median(latencies), 4),
            "p95": round(sorted_latencies[p95_index], 4),
            "total": round(sum(latencies), 4),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument("--prompts", type=Path, default=Path(__file__).with_name("eval_prompts.jsonl"))
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "evidence")
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts must be at least 1")
    cases = load_cases(args.prompts)
    client = OllamaClient(timeout=180)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompts": str(args.prompts.resolve()),
        "execution": "classification_and_selection_only_no_blender_workflow_execution",
        "models": [],
    }
    for model in args.models:
        records = []
        for index, case in enumerate(cases, 1):
            record = evaluate_case(client, model, case, attempts=args.attempts)
            records.append(record)
            print(
                f"[{model}] {index:02d}/{len(cases)} {case['id']}: "
                f"intent={record['actual']['intent']} {record['latency_seconds']['total']:.2f}s",
                flush=True,
            )
        report["models"].append({"summary": summarize(model, records), "cases": records})
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.evidence_dir / f"eval-models-{stamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = args.evidence_dir / "eval-models-latest.json"
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in report["models"]:
        print(json.dumps(item["summary"], ensure_ascii=False, indent=2))
    print(f"Evidence: {output}")


if __name__ == "__main__":
    main()
