import functools
import importlib.metadata
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import pydantic
import typer

import cachi2.core.config as config
from cachi2.core.errors import Cachi2Error, InvalidInput
from cachi2.core.extras.envfile import EnvFormat, generate_envfile
from cachi2.core.models.input import Flag, PackageInput, Request, parse_user_input
from cachi2.core.models.output import BuildConfig
from cachi2.core.resolver import process_packages, resolve_packages, supported_package_managers
from cachi2.core.rooted_path import RootedPath
from cachi2.interface.logging import LogLevel, setup_logging

app = typer.Typer()
log = logging.getLogger(__name__)

DEFAULT_SOURCE = "."
DEFAULT_OUTPUT = "./cachi2-output"


def handle_errors(cmd: Callable[..., None]) -> Callable[..., None]:
    """Decorate a CLI command function with an error handler.

    All errors will be logged at ERROR level before exiting.
    Expected errors will be printed in a friendlier format rather than showing the whole traceback.
    Errors that we consider invalid usage will result in exit code 2.
    """

    def log_error(error: Exception) -> None:
        log.error("%s: %s", type(error).__name__, str(error).replace("\n", r"\n"))

    @functools.wraps(cmd)
    def cmd_with_error_handling(*args: tuple[Any, ...], **kwargs: dict[str, Any]) -> None:
        try:
            cmd(*args, **kwargs)
        except Cachi2Error as e:
            log_error(e)
            print(f"Error: {type(e).__name__}: {e.friendly_msg()}", file=sys.stderr)
            raise typer.Exit(2 if e.is_invalid_usage else 1)
        except Exception as e:
            log_error(e)
            raise

    return cmd_with_error_handling


def version_callback(value: bool) -> None:
    """If --version was used, print the cachi2 version and exit."""
    if not value:
        return

    print("cachi2", importlib.metadata.version("cachi2"))
    print("Supported package managers:", ", ".join(supported_package_managers))
    raise typer.Exit()


@app.callback()
@handle_errors
def cachi2(  # noqa: D103; docstring becomes part of --help message
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
    config_file: Path = typer.Option(
        None,
        "--config-file",
        help="Read configuration from this file.",
        dir_okay=False,
        exists=True,
        resolve_path=True,
        readable=True,
    ),
    log_level: LogLevel = typer.Option(
        LogLevel.INFO.value,
        "--log-level",
        case_sensitive=False,
        help="Set log level.",
    ),
) -> None:
    setup_logging(log_level)
    if config_file:
        config.set_config(config_file)


def _if_json_then_validate(value: str) -> str:
    if _looks_like_json(value):
        try:
            json.loads(value)
        except json.JSONDecodeError:
            raise typer.BadParameter(f"Looks like JSON but is not valid JSON: {value!r}")
    return value


def _looks_like_json(value: str) -> bool:
    return value.lstrip().startswith(("{", "["))


class _Input(pydantic.BaseModel, extra="forbid"):
    packages: list[PackageInput]
    flags: list[Flag] = list()


@app.command()
@handle_errors
def fetch_deps(
    raw_input: str = typer.Argument(
        ...,
        help="Specify package (within the source repo) to process. See usage examples.",
        metavar="PKG",
        callback=_if_json_then_validate,
    ),
    source: Path = typer.Option(
        DEFAULT_SOURCE,
        exists=True,
        file_okay=False,
        resolve_path=True,
        help="Process the git repository at this path.",
    ),
    output: Path = typer.Option(
        DEFAULT_OUTPUT,
        file_okay=False,
        resolve_path=True,
        help="Write output files to this directory.",
    ),
    dev_package_managers: bool = typer.Option(False, "--dev-package-managers", hidden=True),
    cgo_disable: bool = typer.Option(
        False, "--cgo-disable", help="Set CGO_ENABLED=0 while processing gomod packages."
    ),
    force_gomod_tidy: bool = typer.Option(
        False,
        "--force-gomod-tidy",
        help="Run 'go mod tidy' after downloading go dependencies.",
    ),
    gomod_vendor: bool = typer.Option(
        False,
        "--gomod-vendor",
        help=(
            "Fetch go deps via 'go mod vendor' rather than 'go mod download'. If you "
            "have a vendor/ dir, one of --gomod-vendor/--gomod-vendor-check is required."
        ),
    ),
    gomod_vendor_check: bool = typer.Option(
        False,
        "--gomod-vendor-check",
        help=(
            "Same as gomod-vendor, but will not make unexpected changes if you "
            "already have a vendor/ directory (will fail if changes would be made)."
        ),
    ),
) -> None:
    """Fetch dependencies for supported package managers.

    \b
    # gomod package in the current directory
    cachi2 fetch-deps gomod

    \b
    # pip package in the root of the source directory
    cachi2 fetch-deps --source ./my-repo pip

    \b
    # gomod package in a subpath of the source directory (./my-repo/subpath)
    cachi2 fetch-deps --source ./my-repo '{
        "type": "gomod",
        "path": "subpath"
    }'

    \b
    # multiple packages as a JSON list
    cachi2 fetch-deps '[
        {"type": "gomod"},
        {"type": "gomod", "path": "subpath"},
        {"type": "pip", "path": "other-path"}
    ]'

    \b
    # multiple packages and flags as a JSON list
    cachi2 fetch-deps '{
        "packages": [
            {"type": "gomod"},
            {"type": "gomod", "path": "subpath"},
            {"type": "pip", "path": "other-path"}
        ],
        "flags": [
            "gomod-vendor"
        ]
    }'
    """  # noqa: D301, D202; backslashes intentional, blank line required by black

    def normalize_input() -> dict[str, list[Any]]:
        """Format raw_input so it can be parsed by the _Input class."""
        if _looks_like_json(raw_input):
            parsed_input = json.loads(raw_input)

            if isinstance(parsed_input, dict):
                if "packages" in parsed_input.keys():
                    # is a dict with list of packages and possibly flags
                    return parsed_input
                else:
                    # is a dict representing a package
                    return {"packages": [parsed_input]}
            else:
                # is a list
                return {"packages": parsed_input}
        else:
            # is a str
            return {"packages": [{"type": raw_input}]}

    def combine_option_and_json_flags(json_flags: list[Flag]) -> list[str]:
        flag_names = [
            "cgo-disable",
            "dev-package-managers",
            "force-gomod-tidy",
            "gomod-vendor",
            "gomod-vendor-check",
        ]
        flag_values = [
            cgo_disable,
            dev_package_managers,
            force_gomod_tidy,
            gomod_vendor,
            gomod_vendor_check,
        ]
        flags = [name for name, value in zip(flag_names, flag_values) if value]

        if json_flags:
            flags.extend(flag.strip() for flag in json_flags)

        return flags

    input = parse_user_input(_Input.model_validate, normalize_input())

    request = parse_user_input(
        Request.model_validate,
        {
            "source_dir": source,
            "output_dir": output,
            "packages": input.packages,
            "flags": combine_option_and_json_flags(input.flags),
        },
    )

    request_output = resolve_packages(request)

    request.output_dir.path.mkdir(parents=True, exist_ok=True)
    request.output_dir.join_within_root(".build-config.json").path.write_text(
        request_output.build_config.model_dump_json()
    )

    sbom = request_output.generate_sbom()
    request.output_dir.join_within_root("bom.json").path.write_text(
        # the Sbom model has camelCase aliases in some fields
        sbom.model_dump_json(by_alias=True, exclude_none=True)
    )

    log.info(r"All dependencies fetched successfully \o/")


FROM_OUTPUT_DIR_ARG = typer.Argument(
    ...,
    exists=True,
    file_okay=False,
    resolve_path=True,
    help="The output directory populated by a previous fetch-deps command.",
)
FOR_OUTPUT_DIR_OPTION = typer.Option(
    None,
    resolve_path=True,
    help="Generate output as if the output directory was at this path instead.",
)


@app.command()
@handle_errors
def generate_env(
    from_output_dir: Path = FROM_OUTPUT_DIR_ARG,
    for_output_dir: Optional[Path] = FOR_OUTPUT_DIR_OPTION,
    output: Optional[Path] = typer.Option(
        None,
        "-o",
        "--output",
        dir_okay=False,
        help="Write to this file instead of standard output.",
    ),
    fmt: Optional[EnvFormat] = typer.Option(
        None,
        "-f",
        "--format",
        help="Specify format to use. Default json or based on output file name.",
    ),
) -> None:
    """Generate the environment variables needed to use the fetched dependencies."""
    fmt = fmt or (EnvFormat.based_on_suffix(output) if output else EnvFormat.json)
    for_output_dir = for_output_dir or from_output_dir
    fetch_deps_output = _get_build_config(from_output_dir)

    env_file_content = generate_envfile(fetch_deps_output, fmt, for_output_dir)

    if output:
        with output.open("w") as f:
            print(env_file_content, file=f)
    else:
        print(env_file_content)


@app.command()
@handle_errors
def inject_files(
    from_output_dir: Path = FROM_OUTPUT_DIR_ARG,
    for_output_dir: Optional[Path] = FOR_OUTPUT_DIR_OPTION,
) -> None:
    """Inject the project files needed to use the fetched dependencies."""
    for_output_dir = for_output_dir or from_output_dir
    fetch_deps_output = _get_build_config(from_output_dir)

    if os.path.exists(os.path.join(from_output_dir, "deps/rpm")):
        process_packages(from_output_dir)

    for project_file in fetch_deps_output.project_files:
        if project_file.abspath.exists():
            log.info("Overwriting %s", project_file.abspath)
        else:
            log.info("Creating %s", project_file.abspath)
            project_file.abspath.parent.mkdir(exist_ok=True, parents=True)

        content = project_file.resolve_content(output_dir=for_output_dir)
        project_file.abspath.write_text(content)


def _get_build_config(output_dir: Path) -> BuildConfig:
    build_config_json = RootedPath(output_dir).join_within_root(".build-config.json").path
    if not build_config_json.exists():
        raise InvalidInput(
            f"No .build-config.json found in {output_dir}. "
            "Please use a directory populated by a previous fetch-deps command."
        )
    return BuildConfig.model_validate_json(build_config_json.read_text())
