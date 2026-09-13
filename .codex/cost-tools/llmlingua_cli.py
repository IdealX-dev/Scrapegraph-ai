"""Inspect LLMLingua availability; text compression requires a reviewed caller."""
from __future__ import annotations

import argparse
import importlib.metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print("llmlingua " + importlib.metadata.version("llmlingua"))
        return 0
    parser.print_help()
    print("Compression is not enabled in this command. A reviewed caller must select "
          "eligible prose, retain its original and validate candidate quality before use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
