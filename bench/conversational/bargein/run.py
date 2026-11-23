"""Pointe Conversational Engineering Benchmarks: the one command.

  uv run --locked --extra local python bench/conversational/bargein/run.py bargein --budget-usd 14 [--adapter ...] [--smoke] [--dry-run]
  uv run --locked --extra local python bench/conversational/bargein/run.py corpus      # render the audio only, $0
  uv run --locked --extra local python bench/conversational/bargein/run.py factcheck   # the fact matcher on Whisper, all four voices, $0
  uv run --locked --extra local python bench/conversational/bargein/run.py report <run-id>

This branch builds `bargein`; the other four benchmarks of the design live on their own branches.
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="run.py")
    p.add_argument("command", choices=["bargein", "corpus", "factcheck", "report", "freeze", "hlk", "identifiers",
                                       "actions", "routing", "all"])
    p.add_argument("run_id", nargs="?")
    p.add_argument("--adapter", default=None, help="comma list of keyboard,null,naive,llm-router,pointe")
    p.add_argument("--budget-usd", type=float, default=None)
    p.add_argument("--port-base", type=int, default=9700)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--resume", default=None)
    p.add_argument("--items", default=None, help="glob over item ids, e.g. 'a0*'")
    p.add_argument("--pointe-setup", default=None)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--debug", action="store_true", help="adapter debugging: ledger rows marked debug, never published")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    if args.command in ("hlk", "identifiers", "actions", "routing", "all"):
        print(f"{args.command}: not built on this branch (bench-bargein); see the design, section 5")
        return 2
    if args.command == "bargein":
        from bargein import bench

        if args.budget_usd is not None:
            if args.budget_usd > bench.CAP_USD:
                raise SystemExit(f"bargein's cap is ${bench.CAP_USD:.2f}")
            bench.CAP_USD = args.budget_usd
        return bench.main(args)
    if args.command == "corpus":
        from bargein import bench
        from core import corpus

        pcm, ok = corpus.render(bench.clips(), HERE / "bargein" / "audio.lock")
        print(f"{len(pcm)} clips; matches audio.lock: {ok}")
        return 0
    if args.command == "factcheck":
        from bargein import factcheck

        return factcheck.main()
    if args.command == "report":
        from bargein import report

        return report.main(args.run_id)
    if args.command == "freeze":
        from bargein import report

        return report.freeze()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
