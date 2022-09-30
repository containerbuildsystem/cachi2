import importlib.metadata
import json
import logging
from itertools import chain
from pathlib import Path
from typing import Optional, Union

import typer
from typer import Option

from cachi2.core.models import Request
from cachi2.core.package_managers import gomod
from cachi2.interface.logging import LogLevel, setup_logging

app = typer.Typer()
log = logging.getLogger(__name__)

DEFAULT_SOURCE = "."
DEFAULT_OUTPUT = "./cachi2-output"


def version_callback(value: bool) -> None:
    """If --version was used, print the cachi2 version and exit."""
    if value:
        print("cachi2", importlib.metadata.version("cachi2"))
        raise typer.Exit()


@app.callback()
def cachi2(  # noqa: D103; docstring becomes part of --help message
    version: bool = Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    # Process top-level options here
    pass


def log_level_callback(log_level: LogLevel) -> None:
    """Set the specified log level."""
    setup_logging(log_level)


# Add this to subcommands, not the top-level options.
LOG_LEVEL_OPTION = Option(
    LogLevel.INFO.value,
    case_sensitive=False,
    callback=log_level_callback,
    help="Set log level.",
)


def maybe_load_json(opt_name: str, opt_value: str) -> Optional[Union[dict, list]]:
    """If the option string looks like a JSON dict or list, parse it. Otherwise, return None."""
    if not opt_value.lstrip().startswith(("{", "[")):
        return None

    try:
        value = json.loads(opt_value)
    except json.JSONDecodeError:
        raise typer.BadParameter(f"{opt_name}: looks like JSON but is not valid JSON")

    return value


@app.command()
def fetch_deps(
    package: list[str] = Option(
        ...,  # Ellipsis makes this option required
        help="Specify package (within the source repo) to process. Can be used multiple times.",
        metavar="PKG",
    ),
    source: Path = Option(DEFAULT_SOURCE, help="Process the git repository at this path."),
    output: Path = Option(DEFAULT_OUTPUT, help="Write output files to this directory."),
    # TODO: let's have actual flags like --gomod-vendor instead?
    flags: str = Option(
        "",
        help="Pass additional flags as a comma-separated list.",
        metavar="FLAGS",
    ),
    log_level: LogLevel = LOG_LEVEL_OPTION,
) -> None:
    """Fetch dependencies for supported package managers."""

    def parse_packages(package_str: str) -> list[dict]:
        """Parse a --package argument into a list of packages (--package may be a JSON list)."""
        json_obj = maybe_load_json("--package", package_str)
        if json_obj is None:
            packages = [{"type": package_str, "path": "."}]
        elif isinstance(json_obj, dict):
            packages = [json_obj]
        else:
            packages = json_obj
        return packages

    parsed_packages = tuple(chain.from_iterable(map(parse_packages, package)))
    if flags:
        parsed_flags = tuple(flag.strip() for flag in flags.split(","))
    else:
        parsed_flags = ()

    request = Request(
        packages=parsed_packages,
        source_dir=source,
        output_dir=output,
        flags=parsed_flags,
    )
    gomod.fetch_gomod_source(request)

    log.info(r"All dependencies fetched successfully \o/")
