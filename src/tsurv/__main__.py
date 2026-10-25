"""Launch the game: `python -m tsurv` or the `type-survivors` script."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from tsurv.app import TypeSurvivorsApp, is_narrow

if TYPE_CHECKING:
    from collections.abc import Sequence

USAGE: Final = """\
Type Survivors -- type fast or be eaten by the void.

Usage: type-survivors [--resume] [--help]  (or: python -m tsurv ...)

Goal: survive timed waves, kill words before they reach you, and fell
a boss every 5th wave. Death ends the run with a recap card.

Controls (arena): type letters to kill, Esc releases lock, P pauses,
  S suspends while paused, R shows the recap while dead.
Menu: S start, P practice, R resume, H shop, E settings, Q quit.

Flags: --resume restores the suspended checkpoint instead of the menu.
Needs a terminal at least 80 columns wide; NO_COLOR=1 is mono mode.
"""


@dataclass(frozen=True, slots=True)
class Args:
    """Parsed CLI flags (immutable value object)."""

    resume: bool = False
    show_help: bool = False


def parse_args(argv: Sequence[str]) -> Args:
    """Parse --resume/--help; any other flag is a usage error."""
    resume = False
    show_help = False
    for flag in argv:
        if flag == "--resume":
            resume = True
        elif flag in ("--help", "-h"):
            show_help = True
        else:
            msg = f"unknown option: {flag}"
            raise ValueError(msg)
    return Args(resume=resume, show_help=show_help)


def default_profile_dir() -> Path:
    """Checkpoint home: XDG data dir, so --resume survives restarts."""
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "type-survivors"


def build_app(args: Args, profile_dir: Path | None = None) -> TypeSurvivorsApp:
    """Build the app: hub menu by default, checkpoint restore on --resume."""
    if args.resume:
        return TypeSurvivorsApp(profile_dir=profile_dir, resume=True)
    return TypeSurvivorsApp(profile_dir=profile_dir, start_at_hub=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse flags, guard the terminal, and run the game (0 on success)."""
    raw = tuple(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(raw)
    except ValueError as exc:
        _ = sys.stderr.write(f"{exc}\n{USAGE}")
        return 2
    if args.show_help:
        _ = sys.stdout.write(USAGE)
        return 0
    if is_narrow(shutil.get_terminal_size().columns):
        _ = sys.stderr.write("type-survivors needs a terminal 80+ columns wide.\n")
        return 1
    profile_dir = default_profile_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)
    app = build_app(args, profile_dir)
    try:
        app.run()
    except Exception as exc:  # noqa: BLE001 - backend failures vary by terminal
        _ = sys.stderr.write(f"type-survivors cannot start on this terminal: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
