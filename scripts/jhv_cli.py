"""Local JHV export, import, and index maintenance."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.blender import BlenderAdapter
from workflows.jhv_workflow import apply_jhv_vbom, execute_jhv


def main():
    parser = argparse.ArgumentParser(description="Local JHV workflow and asset index")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("refresh-index", help="Refresh the configured JHV library index")
    for action in ("export", "full", "apply"):
        command = commands.add_parser(action)
        command.add_argument("source", metavar="VBOM" if action == "apply" else "EXCEL")
        command.add_argument("output_dir")
        if action != "apply":
            command.add_argument("--sheet", default="")
        if action != "export":
            command.add_argument("--resolver", choices=("legacy", "compare", "sqlite"))
        command.add_argument("--model", required=action != "export")
    args = parser.parse_args()
    if getattr(args, "resolver", None):
        os.environ["JHV_DPC_RESOLVER"] = args.resolver
    if args.action == "refresh-index":
        try:
            result = {"ok": True, **BlenderAdapter().refresh_jhv_index()}
        except (OSError, RuntimeError) as exc:
            result = {"ok": False, "error": str(exc)}
    elif args.action == "apply":
        result = apply_jhv_vbom(args.source, args.model, args.output_dir)
    else:
        result = execute_jhv(args.source, args.output_dir,
                             model_path=args.model if args.action == "full" else None,
                             sheet_name=args.sheet)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
