import argparse

from keysight_power.connection import open_resource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query *IDN? from a VISA resource.")
    parser.add_argument("--resource", required=True, help="VISA resource string.")
    parser.add_argument("--backend", help="Optional PyVISA backend.")
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="VISA timeout in milliseconds.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    with open_resource(
        args.resource,
        backend=args.backend,
        timeout_ms=args.timeout_ms,
    ) as instrument:
        print(instrument.identify())


if __name__ == "__main__":
    main()
