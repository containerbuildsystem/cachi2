import functools
import importlib.metadata
import json
import logging
import sys
from itertools import chain
from pathlib import Path
from typing import Callable, Optional, Union

import pydantic
import typer
from typer import Argument, Option

from cachi2.core.errors import Cachi2Error
from cachi2.core.extras.envfile import EnvFormat, generate_envfile
from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.package_managers import gomod
from cachi2.interface.logging import LogLevel, setup_logging

app = typer.Typer()
log = logging.getLogger(__name__)

DEFAULT_SOURCE = "."
DEFAULT_OUTPUT = "./cachi2-output"


def die(msg: str) -> None:
    """Print the error message to stderr and exit."""
    print("Error:", msg, file=sys.stderr)
    raise typer.Exit(1)


def friendly_errors(cmd: Callable[..., None]) -> Callable[..., None]:
    """Decorate a CLI command function with an error handler.

    Expected errors will be printed in a friendlier format rather than showing the whole traceback.
    """

    @functools.wraps(cmd)
    def cmd_with_friendlier_errors(*args, **kwargs) -> None:
        try:
            cmd(*args, **kwargs)
        # TODO: wrap pydantic ValidationErrors in our own errors?
        except (Cachi2Error, pydantic.ValidationError) as e:
            die(f"{type(e).__name__}: {e}")

    return cmd_with_friendlier_errors


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
@friendly_errors
def fetch_deps(
    package: list[str] = Option(
        ...,  # Ellipsis makes this option required
        help="Specify package (within the source repo) to process. See usage examples.",
        metavar="PKG",
    ),
    source: Path = Option(
        DEFAULT_SOURCE,
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Process the git repository at this path.",
    ),
    output: Path = Option(
        DEFAULT_OUTPUT,
        file_okay=False,
        resolve_path=True,
        help="Write output files to this directory.",
    ),
    cgo_disable: bool = Option(
        False, "--cgo-disable", help="Set CGO_ENABLED=0 while processing gomod packages."
    ),
    force_gomod_tidy: bool = Option(
        False,
        "--force-gomod-tidy",
        help="Run 'go mod tidy' after downloading go dependencies.",
    ),
    gomod_vendor: bool = Option(
        False,
        "--gomod-vendor",
        help=(
            "Fetch go deps via 'go mod vendor' rather than 'go mod download'. If you "
            "have a vendor/ dir, one of --gomod-vendor/--gomod-vendor-check is required."
        ),
    ),
    gomod_vendor_check: bool = Option(
        False,
        "--gomod-vendor-check",
        help=(
            "Same as gomod-vendor, but will not make unexpected changes if you "
            "already have a vendor/ directory (will fail if changes would be made)."
        ),
    ),
    more_flags: str = Option(
        "",
        "--flags",
        help="Pass additional flags as a comma-separated list.",
        metavar="FLAGS",
    ),
    log_level: LogLevel = LOG_LEVEL_OPTION,
) -> None:
    """Fetch dependencies for supported package managers.

    \b
    # gomod package in the current directory
    cachi2 fetch-deps --package gomod

    \b
    # pip package (not supported yet) in the root of the source directory
    cachi2 fetch-deps --source ./my-repo --package pip

    \b
    # gomod package in a subpath of the source directory (./my-repo/subpath)
    cachi2 fetch-deps --source ./my-repo --package '{
        "type": "gomod",
        "path": "subpath"
    }'

    \b
    # multiple packages
    cachi2 fetch-deps \\
        --package gomod \\
        --package '{"type": "gomod", "path": "subpath"}' \\
        --package '{"type": "pip", "path": "other-path"}'

    \b
    # multiple packages as a JSON list
    cachi2 fetch-deps --package '[
        {"type": "gomod"},
        {"type": "gomod", "path": "subpath"},
        {"type": "pip", "path": "other-path"}
    ]'
    """  # noqa: D301, D202; backslashes intentional, blank line required by black

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

    def combine_flags() -> list[str]:
        flag_names = ["cgo-disable", "force-gomod-tidy", "gomod-vendor", "gomod-vendor-check"]
        flag_values = [cgo_disable, force_gomod_tidy, gomod_vendor, gomod_vendor_check]
        flags = [name for name, value in zip(flag_names, flag_values) if value]
        if more_flags:
            flags.extend(flag.strip() for flag in more_flags.split(","))
        return flags

    parsed_packages = tuple(chain.from_iterable(map(parse_packages, package)))
    request = Request(
        source_dir=source,
        output_dir=output,
        packages=parsed_packages,
        flags=combine_flags(),
    )

    request_output = gomod.fetch_gomod_source(request)

    request.output_dir.mkdir(parents=True, exist_ok=True)
    request.output_dir.joinpath("output.json").write_text(request_output.json())

    log.info(r"All dependencies fetched successfully \o/")


@app.command()
@friendly_errors
def generate_env(
    from_output_dir: Path = Argument(
        ...,
        exists=True,
        file_okay=False,
        help="The output directory populated by a previous fetch-deps command.",
    ),
    for_output_dir: Optional[Path] = Option(
        None, help="Generate output as if the output directory was at this path instead."
    ),
    output: Optional[Path] = Option(
        None,
        "-o",
        "--output",
        dir_okay=False,
        help="Write to this file instead of standard output.",
    ),
    fmt: Optional[EnvFormat] = Option(
        None,
        "-f",
        "--format",
        help="Specify format to use. Default json or based on output file name.",
    ),
):
    """Generate the environment variables needed to use the fetched dependencies."""
    fmt = fmt or (EnvFormat.based_on_suffix(output) if output else EnvFormat.json)
    for_output_dir = (for_output_dir or from_output_dir).resolve()

    output_json = from_output_dir / "output.json"
    fetch_deps_output = RequestOutput.parse_raw(output_json.read_text())

    env_file_content = generate_envfile(fetch_deps_output, fmt, for_output_dir)

    if output:
        with output.open("w") as f:
            print(env_file_content, file=f)
    else:
        print(env_file_content)
