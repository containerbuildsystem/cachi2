from cachi2.core.models.input import Request
from cachi2.core.models.output import BuildConfig, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import run_cmd

import json
import re
import logging
from yaml import safe_dump, safe_load

from typing import Any, NamedTuple, Optional, TypedDict


log = logging.getLogger(__name__)


class Plugin(TypedDict):
    """A plugin defined in a yarnrc file."""
    path: str
    spec: str


class YarnRc:
    _yarn_version_regex = re.compile("yarn-[0-9].[0-9].[0-9].cjs")

    """A yarnrc file."""
    def __init__(self, path: RootedPath, data: dict[str, Any]) -> None:
        self._path = path
        self._data = data

    @property
    def plugins(self) -> list[Plugin]:
        return self._data.get("plugins", [])

    @property
    def yarn_path(self) -> Optional[str]:
        return self._data.get("yarnPath", None)

    @property
    def yarn_version(self) -> Optional[str]:
        if not self.yarn_path:
            return None

        matches = self._yarn_version_regex.search(self.yarn_path)

        if matches:
            return matches[0].replace(".cjs", "").replace("-", "@")

        return None

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "YarnRc":
        """Parses the content of a yarnrc file."""
        with file_path.path.open("r") as file:
            data = safe_load(file)

        return YarnRc(file_path, data)

    def merge_data_into_new_file(self, data: dict[str, Any]) -> "YarnRc":
        return YarnRc(
            self._path,
            self._data | data,
        )

    def write(self) -> None:
        """Writes the content of a yarnrc file to disk"""
        with self._path.path.open("w") as file:
            safe_dump(self._data, file)


class PackageJson:
    def __init__(self, path: RootedPath, data: dict[str, Any]) -> None:
        self._path = path
        self._data = data

    @property
    def package_manager(self):
        return self._data.get("packageManager", None)

    @classmethod
    def from_file(cls, file_path: RootedPath) -> "PackageJson":
        """Parses the content of a package.json file."""
        with file_path.path.open("r") as file:
            data = json.load(file)

        return PackageJson(file_path, data)

    def merge_data_into_new_file(self, data: dict[str, Any]) -> "PackageJson":
        return PackageJson(
            self._path,
            self._data | data,
        )

    def write(self) -> None:
        """Writes the content of a yarnrc file to disk"""
        with self._path.path.open("w") as file:
            file_content = json.dumps(self._data, indent=2) + "\n"
            file.write(file_content)


class YarnProject(NamedTuple):
    source_dir: RootedPath
    yarn_rc: YarnRc
    package_json: PackageJson
    yarn_cache: RootedPath

    @property
    def is_zero_installs(self) -> bool:
        return self.yarn_cache.path.exists()

    @classmethod
    def from_path(cls, source_dir: RootedPath) -> "YarnProject":
        # Handle errors: file exists? malformed?
        yarn_rc = YarnRc.from_file(source_dir.join_within_root(".yarnrc.yml")) 
        package_json = PackageJson.from_file(source_dir.join_within_root("package.json"))
        yarn_cache = source_dir.join_within_root(".yarn/cache")

        return YarnProject(source_dir, yarn_rc, package_json, yarn_cache)


class Dependency(TypedDict):
    descriptor: str
    locator: str


class Package(NamedTuple):
    value: str
    version: str
    dependencies: list[Dependency]

    _protocol_regex = re.compile("@[a-z]+:")

    @property
    def locator(self) -> str:
        matches = self._protocol_regex.search(self.value)

        if matches:
            return matches[0][1:-1]

    @property
    def name(self) -> str:
        parts = self.value.split("@")

        # aliased package, starts with @
        if parts[0] == "":
            return "@" + parts[1]

        return parts[0]

    @classmethod
    def from_info_string(cls, info: str) -> "Package":
        data = json.loads(info)

        return Package(
            value=data["value"],
            version=data["children"]["Version"],
            dependencies=[
                dep for dep in data["children"].get("Dependencies", [])
            ]
        )


def fetch_yarn_source(request: Request) -> RequestOutput:
    project = YarnProject.from_path(request.source_dir)
    _install_yarn(project)

    try:
        _prepare_for_prefetch(project, request)
        packages = _list_dependencies(project.source_dir)
        # _ban_dangerous_scripts_in_git_dependencies(packages)
        # _fetch_dependencies(project)
    except:
        _restore_files(project)
        raise

    components = [_create_component_from_package(package) for package in packages]
    build_config = _generate_build_config()
    _restore_files(project)

    return RequestOutput.from_obj_list(
        components,
        build_config.environment_variables,
        build_config.project_files,
    )


def _install_yarn(project: YarnProject) -> None:
    package_json_version = project.package_json.package_manager
    yarn_rc_version = project.yarn_rc.yarn_version

    if package_json_version:
        if yarn_rc_version and package_json_version != yarn_rc_version:
            raise Exception("Yarn version mismatch in package.json and .yarnrc")
    elif yarn_rc_version:
        _set_yarn_version_in_package_json(yarn_rc_version)
    else:
        raise Exception("Yarn version is not set.")


def _set_yarn_version_in_package_json(package_json: PackageJson, version: str):
    new_file = package_json.merge_data_into_new_file({"packageManager": version})
    new_file.write()


def _prepare_for_prefetch(project: YarnProject, request: Request) -> None:
    data_changes = {
        "checksumBehavior": "throw",
        "enableMirror": True,
        "globalFolder": str(request.output_dir.join_within_root("deps/yarn")),
        "plugins": [],
    }

    changed_yarn_rc = project.yarn_rc.merge_data_into_new_file(data_changes)
    changed_yarn_rc.write()


def _list_dependencies(source_dir: RootedPath) -> list[Package]:
    cmd = ["yarn", "info", "-AR", "--json", "--cache"]

    result = run_cmd(cmd=cmd, params={"cwd": source_dir})

    return [Package.from_info_string(info) for info in result.splitlines()]


def _ban_dangerous_scripts_in_git_dependencies(packages: list[Package]) -> None:
    pass


def _fetch_dependencies(project: YarnProject) -> None:
    cmd = ["yarn", "install", "--mode=skip-build"]

    if project.is_zero_installs:
        cmd = [*cmd, "--immutable-cache", "--check-cache"]

    _run_yarn_cmd(cmd, project.source_dir)


def _run_yarn_cmd(cmd: list[str], source_dir: RootedPath):
    env = {
        "YARN_IGNORE_PATH": "true"
    }

    run_cmd(cmd=cmd, params={"cwd": source_dir, "env": env})


def _restore_files(project: YarnProject) -> None:
    project.yarn_rc.write()
    project.package_json.write()


def _create_component_from_package(package: Package) -> Component:
    return Component(
        name=package.value,
        version=package.version,
        purl=_generate_purl_for_package(package),
    )


def _generate_purl_for_package(package: Package) -> str:
    if package.locator == "npm":
        return f"pkg:npm/{package.name}@{package.version}"
    
    if package.locator == "github" or package.locator == "git":
        name = _find_vcs_package_real_name(package)

        parts = package.value.split("@")

        # len parts == 3 -> aliased packaged (@name)
        url = parts[2] if len(parts) == 3 else parts[1]
        
        return f"pkg:npm/{name}@{package.version}?vcs_url={url}"

    if package.locator == "workspace":
        return f"pkg:npm/{package.name}@{package.version}?vcs_url=thisrepo"

    if package.locator == "https":
        parts = package.value.split("@")

        # len parts == 3 -> aliased packaged (@name)
        url = parts[2] if len(parts) == 3 else parts[1]
        
        return f"pkg:npm/{package.name}@{package.version}?file_url={url}"

    if package.locator == "patch":
        return f"pkg:npm/{package.name}@{package.version}"

    raise Exception(f"Locator {package.locator} not implemented")


def _find_vcs_package_real_name(package: Package) -> str:
    # download the package and look at its package.json
    return package.name


def _generate_build_config() -> BuildConfig:
    return BuildConfig(environment_variables=[], project_files=[])