import enum
import functools
import importlib.metadata
import json
import logging
import shutil
import sys
from itertools import chain
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast

import pydantic
import typer

import cachi2.core.config as config
from cachi2.core.errors import Cachi2Error, InvalidInput, UnexpectedFormat
from cachi2.core.extras.envfile import EnvFormat, generate_envfile
from cachi2.core.models.input import Flag, PackageInput, Request, parse_user_input
from cachi2.core.models.output import BuildConfig
from cachi2.core.models.property_semantics import merge_component_properties
from cachi2.core.models.sbom import Sbom, SPDXPackage, SPDXRelation, SPDXSbom
from cachi2.core.resolver import inject_files_post, resolve_packages, supported_package_managers
from cachi2.core.rooted_path import RootedPath
from cachi2.interface.logging import LogLevel, setup_logging

app = typer.Typer()
log = logging.getLogger(__name__)

DEFAULT_SOURCE = "."
DEFAULT_OUTPUT = "./cachi2-output"


OUTFILE_OPTION = typer.Option(
    None,
    "-o",
    "--output",
    dir_okay=False,
    help="Write to this file instead of standard output.",
)


class SBOMFormat(str, enum.Enum):
    """The type of SBOM to generate."""

    cyclonedx = "cyclonedx"
    spdx = "spdx"


SBOM_TYPE_OPTION = typer.Option(
    SBOMFormat.cyclonedx,
    "--sbom-output-type",
    help=("Format of generated SBOM. Default is CycloneDX"),
)


Paths = list[Path]


def _bail_out_with_error(e: Cachi2Error) -> None:
    """Report and error and set correct exit code."""
    log.error("%s: %s", type(e).__name__, str(e).replace("\n", r"\n"))
    print(f"Error: {type(e).__name__}: {e.friendly_msg()}", file=sys.stderr)
    raise typer.Exit(2 if e.is_invalid_usage else 1)


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
            _bail_out_with_error(e)
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
            "DEPRECATED (no longer has any effect when set). "
            "Fetch go deps via 'go mod vendor' rather than 'go mod download'. If you "
            "have a vendor/ dir, one of --gomod-vendor/--gomod-vendor-check is required."
        ),
    ),
    gomod_vendor_check: bool = typer.Option(
        False,
        "--gomod-vendor-check",
        help=(
            "DEPRECATED (no longer has any effect when set). "
            "Same as gomod-vendor, but will not make unexpected changes if you "
            "already have a vendor/ directory (will fail if changes would be made)."
        ),
    ),
    sbom_type: SBOMFormat = SBOM_TYPE_OPTION,
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

    deps_dir = output / "deps"
    if deps_dir.exists():
        log.debug(f"Removing existing deps directory '{deps_dir}'")
        shutil.rmtree(deps_dir, ignore_errors=True)

    request_output = resolve_packages(request)

    request.output_dir.path.mkdir(parents=True, exist_ok=True)
    request.output_dir.join_within_root(".build-config.json").path.write_text(
        request_output.build_config.model_dump_json(indent=2, exclude_none=True)
    )

    if sbom_type == SBOMFormat.cyclonedx:
        sbom: Union[Sbom, SPDXSbom] = request_output.generate_sbom()
    else:
        sbom = request_output.generate_sbom().to_spdx()
    request.output_dir.join_within_root("bom.json").path.write_text(
        # the Sbom model has camelCase aliases in some fields
        sbom.model_dump_json(indent=2, by_alias=True, exclude_none=True)
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
    output: Optional[Path] = OUTFILE_OPTION,
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

    for project_file in fetch_deps_output.project_files:
        if project_file.abspath.exists():
            log.info("Overwriting %s", project_file.abspath)
        else:
            log.info("Creating %s", project_file.abspath)
            project_file.abspath.parent.mkdir(exist_ok=True, parents=True)

        content = project_file.resolve_content(output_dir=for_output_dir)
        project_file.abspath.write_text(content)

    inject_files_post(
        from_output_dir=from_output_dir,
        for_output_dir=for_output_dir,
        options=fetch_deps_output.options,
    )


def _prevalidate_sbom_files_args(sbom_files_to_merge: Paths) -> Paths:
    def enough_files_for_merge(sbom_files_to_merge: Paths) -> Paths:
        if len(sbom_files_to_merge) < 2:
            # NOTE: an exception here happens during argument evaluation phase
            # i.e. outside of handle_errors() decorator. Simply raising
            # an exception here will not produce correct exit code, thus
            # the explicit call to exception wrapper.
            _bail_out_with_error(InvalidInput("Need at least two different SBOM files"))
        return sbom_files_to_merge

    def all_files_are_jsons(sbom_files_to_merge: Paths) -> Paths:
        for sbom_file in sbom_files_to_merge:
            try:
                json.loads(sbom_file.read_text())
            except ValueError:
                # See comment in enough_files_for_merge()
                _bail_out_with_error(
                    UnexpectedFormat(f"{sbom_file} does not look like a SBOM file")
                )
        return sbom_files_to_merge

    return all_files_are_jsons(enough_files_for_merge(list(set(sbom_files_to_merge))))


def merge_relationships(
    relationships_list: List[List[SPDXRelation]], doc_ids: List[str], packages: List[SPDXPackage]
) -> List[SPDXRelation]:
    """Merge SPDX relationships.

    Function takes relationships lists and unified list of packages.
    For relationhips lists, map and inverse map of relations are created. SPDX document usually
    contains virtual package which serves as "envelope" for all real packages. These virtual
    packages are searched in the relationships and their ID is stored as middle element.
    """

    def map_relationships(
        relationships: List[SPDXRelation],
    ) -> Tuple[Optional[str], Dict[str, List[str]], Dict[str, str]]:
        relations_map: Dict[str, List[str]] = {}
        inverse_map: Dict[str, str] = {}

        for rel in relationships:
            spdx_id, related_spdx = rel.spdxElementId, rel.relatedSpdxElement
            relations_map.setdefault(spdx_id, []).append(related_spdx)
            inverse_map[related_spdx] = spdx_id

        root_element = next((k for k in relations_map if k not in inverse_map), None)
        return root_element, relations_map, inverse_map

    package_ids = {pkg.SPDXID for pkg in packages}
    root_ids = []
    maps = []
    inv_maps = []
    envelopes = []
    for relationships, doc_id in zip(relationships_list, doc_ids):
        root, _map, inv_map = map_relationships(relationships)
        maps.append(_map)
        inv_maps.append(inv_map)
        if not root:
            root = doc_id
        root_ids.append(root)

    for _map, _inv_map, root_id in zip(maps, inv_maps, root_ids):
        envelope = next((r for r, c in _map.items() if _inv_map.get(r) == root_id), None)
        envelopes.append(envelope)

    merged_relationships = []

    def process_relation(
        rel: SPDXRelation,
        root_main: Optional[str],
        root_other: Optional[str],
        envelope_main: str,
        envelope_other: Optional[str],
    ) -> None:
        new_rel = SPDXRelation(
            spdxElementId=root_main if rel.spdxElementId == root_other else rel.spdxElementId,
            relatedSpdxElement=(
                root_main if rel.relatedSpdxElement == root_other else rel.relatedSpdxElement
            ),
            relationshipType=rel.relationshipType,
        )
        if new_rel.spdxElementId == envelope_other:
            new_rel.spdxElementId = envelope_main
        if new_rel.spdxElementId in package_ids or new_rel.relatedSpdxElement in package_ids:
            merged_relationships.append(new_rel)

    envelope_main = envelopes[0]
    if not envelope_main:
        packages.append(
            SPDXPackage(
                SPDXID="SPDXRef-DocumentRoot-File-",
                name="",
            )
        )
        envelope_main = "SPDXRef-DocumentRoot-File-"
    merged_relationships.append(
        SPDXRelation(
            spdxElementId=root_ids[0],
            relatedSpdxElement="SPDXRef-DocumentRoot-File-",
            relationshipType="DESCRIBES",
        )
    )

    root_main = root_ids[0]

    for relationships, root_id, envelope in zip(relationships_list, root_ids, envelopes):
        for rel in relationships:
            process_relation(rel, root_main, root_id, envelope_main, envelope)

    for envelope in envelopes[1:]:
        envelope_packages: List[Optional[SPDXPackage]] = [
            x for x in packages if x.SPDXID == envelope
        ]
        envelope_package: Optional[SPDXPackage] = (envelope_packages or [None])[0]
        if envelope_package:
            packages.pop(packages.index(envelope_package))
    return merged_relationships


@app.command()
@handle_errors
def merge_sboms(
    sbom_files_to_merge: Paths = typer.Argument(
        ...,
        callback=_prevalidate_sbom_files_args,
        exists=True,
        file_okay=True,
        dir_okay=False,
        resolve_path=True,
        readable=True,
        help="Names of files with SBOMs to merge.",
    ),
    output_sbom_file_name: Optional[Path] = OUTFILE_OPTION,
    sbom_type: SBOMFormat = SBOM_TYPE_OPTION,
    sbom_name: Optional[str] = typer.Option(
        None, "--sbom-name", help="Name of the resulting merged SBOM."
    ),
) -> None:
    """Merge two or more SBOMs into one.

    The command works with Cachi2-generated SBOMs only. You might want to run

    cachi2 fetch-deps <args...>

    first to produce SBOMs to merge.
    """
    sboms_to_merge: List[Union[SPDXSbom, Sbom]] = []
    for sbom_file in sbom_files_to_merge:
        sbom_dict = json.loads(sbom_file.read_text())
        # Remove extra fields which are not in Sbom or SPDXSbom models
        # Both SBom and SPDXSBom models are only subset of cyclonedx and SPDX specifications
        # Therefore we need to make sure only fields accepted by the models are present
        try:
            sboms_to_merge.append(Sbom(**sbom_dict))
        except pydantic.ValidationError:
            try:
                sboms_to_merge.append(SPDXSbom(**sbom_dict))
            except pydantic.ValidationError:
                raise UnexpectedFormat(f"{sbom_file} does not appear to be a valid Cachi2 SBOM.")

    if sbom_type == SBOMFormat.cyclonedx:
        cyclonedx_sboms_to_merge = []
        for _sbom in sboms_to_merge:
            if not isinstance(_sbom, Sbom):
                cyclonedx_sboms_to_merge.append(_sbom.to_cyclonedx())
            else:
                cyclonedx_sboms_to_merge.append(_sbom)
        sbom: Union[Sbom, SPDXSbom] = Sbom(
            components=merge_component_properties(
                chain.from_iterable(s.components for s in cyclonedx_sboms_to_merge)
            )
        )
    else:
        spdx_sboms_to_merge = []
        for _sbom in sboms_to_merge:
            if not isinstance(_sbom, SPDXSbom):
                spdx_sboms_to_merge.append(_sbom.to_spdx())
            else:
                spdx_sboms_to_merge.append(_sbom)

        packages = chain.from_iterable(cast(SPDXSbom, s).packages for s in spdx_sboms_to_merge)
        sbom = SPDXSbom(
            spdxVersion="SPDX-2.3",
            SPDXID="SPDXRef-DOCUMENT",
            dataLicense="CC0-1.0",
            name=sbom_name or cast(SPDXSbom, spdx_sboms_to_merge[0]).name,
            creationInfo=cast(SPDXSbom, spdx_sboms_to_merge[0]).creationInfo,
            packages=[],
        )
        sbom.packages = list(packages)
        root_ids: List[str] = [s.SPDXID for s in spdx_sboms_to_merge]
        sbom.relationships = merge_relationships(
            [s.relationships for s in spdx_sboms_to_merge], root_ids, sbom.packages
        )

    sbom_json = sbom.model_dump_json(indent=2, by_alias=True, exclude_none=True)

    if output_sbom_file_name is not None:
        output_sbom_file_name.write_text(sbom_json)
    else:
        print(sbom_json)


def _get_build_config(output_dir: Path) -> BuildConfig:
    build_config_json = RootedPath(output_dir).join_within_root(".build-config.json").path
    if not build_config_json.exists():
        raise InvalidInput(
            f"No .build-config.json found in {output_dir}. "
            "Please use a directory populated by a previous fetch-deps command."
        )
    return BuildConfig.model_validate_json(build_config_json.read_text())
