"""Run `python -m documentation build|check` from the repository."""

import argparse

from documentation.builder import OUTPUT, build_html, write_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the ZEEP POD handbook")
    parser.add_argument("command", choices=("build", "check"))
    args = parser.parse_args()
    if args.command == "build":
        print(write_bundle())
    elif not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != build_html():
        parser.exit(1, "Handbook is stale. Run: python -m documentation build\n")
    else:
        print("Handbook matches its source documents and assets.")


if __name__ == "__main__":
    main()
