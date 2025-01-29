import logging
import textwrap

import tomlkit
from tomlkit.toml_file import TOMLFile

from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, ProjectFile, RequestOutput
from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import run_cmd

log = logging.getLogger(__name__)


def fetch_cargo_source(request: Request) -> RequestOutput:
    """Fetch the source code for all cargo packages specified in a request."""
    components: list[Component] = []
    environment_variables: list[EnvironmentVariable] = []
    project_files: list[ProjectFile] = []

    for package in request.cargo_packages:
        package_dir = request.source_dir.join_within_root(package.path)
        components.extend(_resolve_cargo_package(package_dir, request.output_dir))
        # cargo allows to specify configuration per-package
        # https://doc.rust-lang.org/cargo/reference/config.html#hierarchical-structure
        project_files.append(_use_vendored_sources(package_dir))

    return RequestOutput.from_obj_list(components, environment_variables, project_files)


def _resolve_cargo_package(package_dir: RootedPath, output_dir: RootedPath) -> list[Component]:
    """Resolve a single cargo package."""
    vendor_dir = output_dir.join_within_root("deps/cargo")
    cmd = ["cargo", "vendor", "--locked", str(vendor_dir)]
    log.info("Fetching cargo dependencies at %s", package_dir)
    run_cmd(cmd=cmd, params={"cwd": package_dir})
    return []


def _use_vendored_sources(package_dir: RootedPath) -> ProjectFile:
    """Make sure cargo will use the vendored sources when building the project."""
    cargo_config = package_dir.join_within_root(".cargo/config.toml")
    cargo_config.path.parent.mkdir(parents=True, exist_ok=True)
    cargo_config.path.touch(exist_ok=True)

    template = """
    [source.crates-io]
    replace-with = "vendored-sources"

    [source.vendored-sources]
    directory = "${output_dir}/deps/cargo"
    """

    toml_file = TOMLFile(cargo_config)
    original_content = toml_file.read()
    original_content.update(tomlkit.parse(textwrap.dedent(template)))
    toml_file.write(original_content)

    return ProjectFile(abspath=cargo_config.path, template=template)
