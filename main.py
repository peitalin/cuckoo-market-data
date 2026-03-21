from __future__ import annotations

import argparse
from typing import Callable
from typing import Optional
from typing import Sequence

from pipeline import export_from_api_main
from pipeline import generate_synthetic_marketplace_bundle_main
from pipeline import plot_synthetic_marketplace_projections_main
from pipeline import synthetic_marketplace_growth_main
from pipeline import synthetic_marketplace_revenues_main

CommandFn = Callable[[Optional[Sequence[str]]], int]


COMMANDS: dict[str, CommandFn] = {
    "export": export_from_api_main,
    "bundle": generate_synthetic_marketplace_bundle_main,
    "revenues": synthetic_marketplace_revenues_main,
    "growth": synthetic_marketplace_growth_main,
    "plot": plot_synthetic_marketplace_projections_main,
}


def _parse_args(argv: Sequence[str] | None = None) -> tuple[str, list[str]]:
    parser = argparse.ArgumentParser(
        description="Export-CSV entrypoint for raw export, synthetic generation, and chart rendering."
    )
    parser.add_argument(
        "command",
        choices=tuple(COMMANDS.keys()),
        help="Subcommand to run: export | bundle | revenues | growth | plot",
    )
    args, passthrough = parser.parse_known_args(argv)
    return args.command, passthrough


def main(argv: Sequence[str] | None = None) -> int:
    command, passthrough = _parse_args(argv)
    return int(COMMANDS[command](passthrough))


if __name__ == "__main__":
    raise SystemExit(main())
