"""Unified PackeTech entry points for desktop, CLI, and terminal menu modes."""

from __future__ import annotations

from importlib import import_module
import os
import sys


def _run_with_arguments(callback, arguments, *, program_name=None):
    """Run an argparse-style callback with a temporary argument vector.

    Args:
        callback: Zero-argument application entry point that reads ``sys.argv``.
        arguments: Arguments exposed to the selected application mode.
        program_name: Optional branded executable name shown by argparse.

    Returns:
        The callback return value.

    Side effects:
        Replaces ``sys.argv`` only for the duration of the callback and always
        restores it, including when argparse raises ``SystemExit``.
    """
    previous = sys.argv
    sys.argv = [program_name or previous[0], *arguments]
    try:
        return callback()
    finally:
        sys.argv = previous


def terminal_main(argv=None, *, program_name=None):
    """Run PackeTech's CLI or interactive TUI without importing Flet.

    Args:
        argv: Optional arguments for tests and embedded launchers. ``None``
            uses the current process arguments.
        program_name: Optional executable name shown in terminal help.

    Returns:
        The selected terminal application's return value.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    program_name = program_name or os.getenv('PACKETECH_PROG_NAME')
    if arguments and arguments[0] in {'tui', 'menu'}:
        from keenetic_router.apps.tui import main as tui_main

        return _run_with_arguments(
            tui_main,
            arguments[1:],
            program_name=program_name,
        )
    if arguments and arguments[0] == 'cli':
        arguments = arguments[1:]
    from keenetic_router.apps.cli import main as cli_main

    return _run_with_arguments(
        cli_main,
        arguments,
        program_name=program_name,
    )


def main(argv=None):
    """Dispatch the branded ``packetech`` command to GUI, CLI, or TUI.

    With no arguments the desktop application opens. ``tui`` selects the
    interactive terminal menu, ``desktop`` explicitly selects the GUI, and
    every other argument is treated as a regular CLI command.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {'desktop', 'gui'}:
        desktop_run = import_module('keenetic_router.apps.desktop').run
        return _run_with_arguments(desktop_run, arguments[1:] if arguments else [])
    return terminal_main(arguments, program_name='packetech')


if __name__ == '__main__':
    main()
