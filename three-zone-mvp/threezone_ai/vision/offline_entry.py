"""Private offline entrypoint for isolated synthetic runs.

MUST NOT be imported by backend.http_server or run.py.
Not an HTTP route. Not registered with the AI gateway or any worker.
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="threezone_ai.vision.offline_entry",
        description="V0 offline synthetic sports-vision evidence (library only)",
    )
    parser.add_argument("source_asset_id", help="asset:synthetic:<id> only")
    parser.add_argument("--escalate", action="store_true", help="run FakeEscalationProvider")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    # Local imports keep `import threezone_ai.vision` from loading this module.
    from threezone_ai.vision.pipeline import run_evidence_pipeline
    from threezone_ai.vision.policy import evaluate_sports_context

    bundle = run_evidence_pipeline(
        args.source_asset_id,
        allow_offline_synthetic=True,
        enable_escalation=bool(args.escalate),
    )
    result = evaluate_sports_context(bundle)
    payload = {
        "bundle": bundle.to_canonical_dict(),
        "policy": result.to_canonical_dict(),
    }
    indent = 2 if args.pretty else None
    sys.stdout.write(json.dumps(payload, indent=indent, sort_keys=True))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
