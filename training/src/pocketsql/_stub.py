import argparse
from collections.abc import Callable


def stub(
    prog: str, milestone: str, configure: Callable[[argparse.ArgumentParser], None]
) -> Callable[[list[str] | None], int]:
    """A CLI that parses its final arguments, then exits as not built yet."""

    def main(argv: list[str] | None = None) -> int:
        parser = argparse.ArgumentParser(prog=prog)
        configure(parser)
        parser.parse_args(argv)
        raise SystemExit(f"{prog} is not implemented yet (planned for {milestone}).")

    return main
