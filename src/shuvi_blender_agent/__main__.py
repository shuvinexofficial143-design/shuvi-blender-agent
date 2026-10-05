"""Lightweight discovery CLI. No Blender subprocess runs without --probe-versions."""

import argparse
import json
from pathlib import Path

from .discovery import DiscoveryConfig, discover, probe_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shuvi-blender-agent")
    subcommands = parser.add_subparsers(dest="command", required=True)
    discovery = subcommands.add_parser("discover", help="Discover installation paths")
    discovery.add_argument("--path", action="append", default=[], type=Path)
    discovery.add_argument("--root", action="append", default=[], type=Path)
    discovery.add_argument(
        "--probe-versions",
        action="store_true",
        help="Explicitly run discovered executables with --version",
    )
    args = parser.parse_args(argv)
    report = discover(
        DiscoveryConfig(tuple(args.path), tuple(args.root)),
        version_probe=probe_version if args.probe_versions else None,
    )
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.installations else 1


if __name__ == "__main__":
    raise SystemExit(main())
