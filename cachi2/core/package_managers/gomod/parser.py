import logging
import os
import subprocess  # nosec

from itertools import chain
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    Literal,
    NoReturn,
    Optional,
    Tuple,
    Union,
)

import backoff
import git
import pydantic

from cachi2.core.config import get_config
from cachi2.core.errors import (
    GoModError,
    PackageRejected,
    UnexpectedFormat,
)
from cachi2.core.models.input import Request
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath
from cachi2.core.utils import load_json_stream, run_cmd
from cachi2.core.package_managers.gomod.version import get_golang_version

log = logging.getLogger(__name__)


GOMOD_DOC = "https://github.com/containerbuildsystem/cachi2/blob/main/docs/gomod.md"
GOMOD_INPUT_DOC = f"{GOMOD_DOC}#specifying-modules-to-process"
VENDORING_DOC = f"{GOMOD_DOC}#vendoring"


class _ParsedModel(pydantic.BaseModel):
    """Attributes automatically get PascalCase aliases to make parsing Golang JSON easier.

    >>> class SomeModel(_GolangModel):
            some_attribute: str

    >>> SomeModel.parse_obj({"SomeAttribute": "hello"})
    SomeModel(some_attribute="hello")
    """

    class Config:
        @staticmethod
        def alias_generator(attr_name: str) -> str:
            return "".join(word.capitalize() for word in attr_name.split("_"))

        # allow SomeModel(some_attribute="hello"), not just SomeModel(SomeAttribute="hello")
        allow_population_by_field_name = True


class ParsedModule(_ParsedModel):
    """A Go module as returned by the -json option of various commands (relevant fields only).

    See:
        go help mod download    (Module struct)
        go help list            (Module struct)
    """

    path: str
    version: Optional[str] = None
    main: bool = False
    replace: Optional["ParsedModule"] = None


class ParsedPackage(_ParsedModel):
    """A Go package as returned by the -json option of go list (relevant fields only).

    See:
        go help list    (Package struct)
    """

    import_path: str
    standard: bool = False
    module: Optional[ParsedModule]


def resolve_gomod(
    app_dir: RootedPath, request: Request, tmp_dir: Path
) -> tuple[ParsedModule, Iterable[ParsedModule], Iterable[ParsedPackage]]:
    """
    Resolve and fetch gomod dependencies for given app source archive.

    :param app_dir: the full path to the application source code
    :param request: the Cachi2 request this is for
    :param tmp_dir: one temporary directory for all go modules
    :return: a dict containing the Go module itself ("module" key), the list of dictionaries
        representing the dependencies ("module_deps" key), the top package level dependency
        ("pkg" key), and a list of dictionaries representing the package level dependencies
        ("pkg_deps" key)
    :raises GoModError: if fetching dependencies fails
    """
    _protect_against_symlinks(app_dir)

    config = get_config()

    env = {
        "GOPATH": tmp_dir,
        "GO111MODULE": "on",
        "GOCACHE": tmp_dir,
        "PATH": os.environ.get("PATH", ""),
        "GOMODCACHE": "{}/pkg/mod".format(tmp_dir),
    }

    if config.goproxy_url:
        env["GOPROXY"] = config.goproxy_url

    if "cgo-disable" in request.flags:
        env["CGO_ENABLED"] = "0"

    run_params = {"env": env, "cwd": app_dir}

    for dep_replacement in request.dep_replacements:
        name = dep_replacement["name"]
        new_name = dep_replacement.get("new_name", name)
        version = dep_replacement["version"]
        log.info("Applying the gomod replacement %s => %s@%s", name, new_name, version)
        run_gomod_cmd(
            ("go", "mod", "edit", "-replace", f"{name}={new_name}@{version}"),
            run_params,
        )

    # Vendor dependencies if the gomod-vendor flag is set
    flags = request.flags
    should_vendor, can_make_changes = _should_vendor_deps(
        flags, app_dir, config.gomod_strict_vendor
    )
    if should_vendor:
        downloaded_modules = _vendor_deps(app_dir, can_make_changes, run_params)
    else:
        log.info("Downloading the gomod dependencies")
        download_cmd = ["go", "mod", "download", "-json"]
        downloaded_modules = (
            ParsedModule.parse_obj(obj)
            for obj in load_json_stream(_run_download_cmd(download_cmd, run_params))
        )

    if "force-gomod-tidy" in flags or request.dep_replacements:
        run_gomod_cmd(("go", "mod", "tidy"), run_params)

    go_list = ["go", "list", "-e"]
    if not should_vendor:
        # Make Go ignore the vendor dir even if there is one
        go_list.extend(["-mod", "readonly"])

    main_module_name = run_gomod_cmd([*go_list, "-m"], run_params).rstrip()
    main_module = ParsedModule(
        path=main_module_name,
        version=get_golang_version(main_module_name, app_dir, update_tags=True),
        main=True,
        dir=str(app_dir),
    )

    def go_list_deps(pattern: Literal["./...", "all"]) -> Iterator[ParsedPackage]:
        """Run go list -deps -json and return the parsed list of packages.

        The "./..." pattern returns the list of packages compiled into the final binary.

        The "all" pattern includes dependencies needed only for tests. Use it to get a more
        complete module list (roughly matching the list of downloaded modules).
        """
        cmd = [*go_list, "-deps", "-json=ImportPath,Module,Standard,Deps", pattern]
        return map(ParsedPackage.parse_obj, load_json_stream(run_gomod_cmd(cmd, run_params)))

    package_modules = (
        module for pkg in go_list_deps("all") if (module := pkg.module) and not module.main
    )

    all_modules = _deduplicate_resolved_modules(package_modules, downloaded_modules)

    log.info("Retrieving the list of packages")
    all_packages = list(go_list_deps("./..."))

    _validate_local_replacements(all_modules, app_dir)

    return main_module, all_modules, all_packages


def _protect_against_symlinks(app_dir: RootedPath) -> None:
    """Try to prevent go subcommands from following suspicious symlinks.

    The go command doesn't particularly care if the files it reads are subpaths of the directory
    where it is executed. Check some of the common paths that the subcommands may read.

    :raises PathOutsideRoot: if go.mod, go.sum, vendor/modules.txt or any **/*.go file is a symlink
        that leads outside the source directory
    """

    def check_potential_symlink(relative_path: Union[str, Path]) -> None:
        try:
            app_dir.join_within_root(relative_path)
        except PathOutsideRoot as e:
            e.solution = (
                "Found a potentially harmful symlink, which would make the go command read "
                "a file outside of your source repository. Refusing to proceed."
            )
            raise

    check_potential_symlink("go.mod")
    check_potential_symlink("go.sum")
    check_potential_symlink("vendor/modules.txt")
    for go_file in app_dir.path.rglob("*.go"):
        check_potential_symlink(go_file.relative_to(app_dir))


def run_gomod_cmd(cmd: Iterable[str], params: dict[str, Any]) -> str:
    try:
        return run_cmd(cmd, params)
    except subprocess.CalledProcessError as e:
        rc = e.returncode
        raise GoModError(
            f"Processing gomod dependencies failed: `{' '.join(cmd)}` failed with {rc=}"
        ) from e


def _run_download_cmd(cmd: Iterable[str], params: Dict[str, Any]) -> str:
    """Run gomod command that downloads dependencies.

    Such commands may fail due to network errors (go is bad at retrying), so the entire operation
    will be retried a configurable number of times.

    Cachi2 will reuse the same cache directory between retries, so Go will not have to download
    the same dependency twice. The backoff is exponential, Cachi2 will wait 1s -> 2s -> 4s -> ...
    before retrying.
    """
    n_tries = get_config().gomod_download_max_tries

    @backoff.on_exception(
        backoff.expo,
        GoModError,
        jitter=None,  # use deterministic backoff, do not apply jitter
        max_tries=n_tries,
        logger=log,
    )
    def run_go(_cmd: Iterable[str], _params: Dict[str, Any]) -> str:
        log.debug(f"Running {_cmd}")
        return run_gomod_cmd(_cmd, _params)

    try:
        return run_go(cmd, params)
    except GoModError:
        err_msg = (
            f"Processing gomod dependencies failed. Cachi2 tried the {' '.join(cmd)} command "
            f"{n_tries} times."
        )
        raise GoModError(err_msg) from None


def _deduplicate_resolved_modules(
    package_modules: Iterable[ParsedModule],
    downloaded_modules: Iterable[ParsedModule],
) -> Iterable[ParsedModule]:
    def get_unique_key(module: ParsedModule) -> tuple[str, Optional[str]]:
        if not (replace := module.replace):
            return module.path, module.version
        elif replace.version:
            # module/name v1.0.0 => replace/name v1.2.3
            return replace.path, replace.version
        else:
            # module/name v1.0.0 => ./local/path
            return module.path, replace.path

    modules_by_name_and_version: dict[tuple[str, Optional[str]], ParsedModule] = {}

    # package_modules have the replace data, so they should take precedence in the deduplication
    for module in chain(package_modules, downloaded_modules):
        # get the module for this name+version or create a new one
        modules_by_name_and_version.setdefault(get_unique_key(module), module)

    return modules_by_name_and_version.values()


def _should_vendor_deps(
    flags: Iterable[str], app_dir: RootedPath, strict: bool
) -> Tuple[bool, bool]:
    """
    Determine if Cachi2 should vendor dependencies and if it is allowed to make changes.

    This is based on the presence of flags:
    - gomod-vendor-check => should vendor, can only make changes if vendor dir does not exist
    - gomod-vendor => should vendor, can make changes

    :param flags: flags from the Cachi2 request
    :param app_dir: absolute path to the app directory
    :param strict: fail the request if the vendor dir is present but the flags are not used?
    :return: (should vendor: bool, allowed to make changes in the vendor directory: bool)
    :raise PackageRejected: if the vendor dir is present, the flags are not used and we are strict
    """
    vendor = app_dir.join_within_root("vendor").path

    if "gomod-vendor-check" in flags:
        return True, not vendor.exists()
    if "gomod-vendor" in flags:
        return True, True

    if strict and vendor.is_dir():
        raise PackageRejected(
            reason=(
                'The "gomod-vendor" or "gomod-vendor-check" flag must be set when your repository '
                "has vendored dependencies."
            ),
            solution=(
                "Consider removing the vendor/ directory and letting Cachi2 download dependencies "
                "instead.\n"
                "If you do want to keep using vendoring, please pass one of the required flags."
            ),
            docs=VENDORING_DOC,
        )

    return False, False


def _vendor_deps(
    app_dir: RootedPath, can_make_changes: bool, run_params: dict[str, Any]
) -> Iterable[ParsedModule]:
    """
    Vendor golang dependencies.

    If Cachi2 is not allowed to make changes, it will verify that the vendor directory already
    contained the correct content.

    :param app_dir: path to the module directory
    :param can_make_changes: is Cachi2 allowed to make changes?
    :param run_params: common params for the subprocess calls to `go`
    :return: the list of Go modules parsed from vendor/modules.txt
    :raise PackageRejected: if vendor directory changed and Cachi2 is not allowed to make changes
    :raise UnexpectedFormat: if Cachi2 fails to parse vendor/modules.txt
    """
    log.info("Vendoring the gomod dependencies")
    _run_download_cmd(("go", "mod", "vendor"), run_params)
    if not can_make_changes and _vendor_changed(app_dir):
        raise PackageRejected(
            reason=(
                "The content of the vendor directory is not consistent with go.mod. "
                "Please check the logs for more details."
            ),
            solution=(
                "Please try running `go mod vendor` and committing the changes.\n"
                "Note that you may need to `git add --force` ignored files in the vendor/ dir.\n"
                "Also consider whether you really want the -check variant of the flag."
            ),
            docs=VENDORING_DOC,
        )
    return _parse_vendor(app_dir)


def _validate_local_replacements(modules: Iterable[ParsedModule], app_path: RootedPath) -> None:
    replaced_paths = [
        (module.path, module.replace.path)
        for module in modules
        if module.replace and module.replace.path.startswith(".")
    ]

    for name, path in replaced_paths:
        try:
            app_path.join_within_root(path)
        except PathOutsideRoot as e:
            e.solution = (
                f"The module '{name}' is being replaced by the local path '{path}', "
                "which falls outside of the repository root. Refusing to proceed."
            )
            raise

def _parse_vendor(module_dir: RootedPath) -> Iterable[ParsedModule]:
    """Parse modules from vendor/modules.txt."""
    modules_txt = module_dir.join_within_root("vendor", "modules.txt")
    if not modules_txt.path.exists():
        return []

    def fail_for_unexpected_format(msg: str) -> NoReturn:
        solution = (
            "Does `go mod vendor` make any changes to modules.txt?\n"
            "If not, please let the maintainers know that Cachi2 fails to parse valid modules.txt"
        )
        raise UnexpectedFormat(f"vendor/modules.txt: {msg}", solution=solution)

    def parse_module_line(line: str) -> ParsedModule:
        parts = line.removeprefix("# ").split()
        # name version
        if len(parts) == 2:
            name, version = parts
            return ParsedModule(path=name, version=version)
        # name => path
        if len(parts) == 3 and parts[1] == "=>":
            name, _, path = parts
            return ParsedModule(path=name, replace=ParsedModule(path=path))
        # name => new_name new_version
        if len(parts) == 4 and parts[1] == "=>":
            name, _, new_name, new_version = parts
            return ParsedModule(path=name, replace=ParsedModule(path=new_name, version=new_version))
        # name version => path
        if len(parts) == 4 and parts[2] == "=>":
            name, version, _, path = parts
            return ParsedModule(path=name, version=version, replace=ParsedModule(path=path))
        # name version => new_name new_version
        if len(parts) == 5 and parts[2] == "=>":
            name, version, _, new_name, new_version = parts
            return ParsedModule(
                path=name,
                version=version,
                replace=ParsedModule(path=new_name, version=new_version),
            )
        fail_for_unexpected_format(f"unexpected module line format: {line!r}")

    modules: list[ParsedModule] = []
    module_has_packages: list[bool] = []

    for line in modules_txt.path.read_text().splitlines():
        if line.startswith("# "):  # module line
            modules.append(parse_module_line(line))
            module_has_packages.append(False)
        elif not line.startswith("#"):  # package line
            if not modules:
                fail_for_unexpected_format(f"package has no parent module: {line}")
            module_has_packages[-1] = True
        elif not line.startswith("##"):  # marker line
            fail_for_unexpected_format(f"unexpected format: {line!r}")

    return (module for module, has_packages in zip(modules, module_has_packages) if has_packages)


def _vendor_changed(app_dir: RootedPath) -> bool:
    """Check for changes in the vendor directory."""
    repo_root = app_dir.root
    vendor = app_dir.path.relative_to(repo_root).joinpath("vendor")
    modules_txt = vendor / "modules.txt"

    repo = git.Repo(repo_root)
    # Add untracked files but do not stage them
    repo.git.add("--intent-to-add", "--force", "--", app_dir)

    try:
        # Diffing modules.txt should catch most issues and produce relatively useful output
        modules_txt_diff = repo.git.diff("--", str(modules_txt))
        if modules_txt_diff:
            log.error("%s changed after vendoring:\n%s", modules_txt, modules_txt_diff)
            return True

        # Show only if files were added/deleted/modified, not the full diff
        vendor_diff = repo.git.diff("--name-status", "--", str(vendor))
        if vendor_diff:
            log.error("%s directory changed after vendoring:\n%s", vendor, vendor_diff)
            return True
    finally:
        repo.git.reset("--", app_dir)

    return False
