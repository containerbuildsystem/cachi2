# SPDX-License-Identifier: GPL-3.0-or-later
import ast
import configparser
import functools
import io
import logging
import os.path
import re
import tarfile
import urllib
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Iterable, Optional

from cachi2.core.rooted_path import RootedPath

if TYPE_CHECKING:
    from typing_extensions import TypeGuard

import bs4
import pkg_resources
import requests
from packaging.utils import canonicalize_name, canonicalize_version

from cachi2.core.checksum import ChecksumInfo, must_match_any_checksum
from cachi2.core.config import get_config
from cachi2.core.errors import FetchError, PackageRejected, UnexpectedFormat, UnsupportedFeature
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, ProjectFile, RequestOutput
from cachi2.core.package_managers.general import (
    download_binary_file,
    extract_git_info,
    pkg_requests_session,
)
from cachi2.core.scm import clone_as_tarball

log = logging.getLogger(__name__)

DEFAULT_BUILD_REQUIREMENTS_FILE = "requirements-build.txt"
DEFAULT_REQUIREMENTS_FILE = "requirements.txt"

NOTHING = object()  # A None replacement for cases where the distinction is needed

# Check that the path component of a URL ends with a full-length git ref
GIT_REF_IN_PATH = re.compile(r"@[a-fA-F0-9]{40}$")

# All supported sdist formats, see https://docs.python.org/3/distutils/sourcedist.html
ZIP_FILE_EXT = ".zip"
COMPRESSED_TAR_EXT = ".tar.Z"
SDIST_FILE_EXTENSIONS = [ZIP_FILE_EXT, ".tar.gz", ".tar.bz2", ".tar.xz", COMPRESSED_TAR_EXT, ".tar"]
SDIST_EXT_PATTERN = r"|".join(map(re.escape, SDIST_FILE_EXTENSIONS))

PYPI_URL = "https://pypi.org"

PIP_METADATA_DOC = (
    "https://github.com/containerbuildsystem/cachi2/blob/main/docs/pip.md#project-metadata"
)
PIP_REQUIREMENTS_TXT_DOC = (
    "https://github.com/containerbuildsystem/cachi2/blob/main/docs/pip.md#requirementstxt"
)
PIP_EXTERNAL_DEPS_DOC = (
    "https://github.com/containerbuildsystem/cachi2/blob/main/docs/pip.md#external-dependencies"
)
PIP_NO_SDIST_DOC = "https://github.com/containerbuildsystem/cachi2/blob/main/docs/pip.md#dependency-does-not-distribute-sources"


def fetch_pip_source(request: Request) -> RequestOutput:
    """Resolve and fetch pip dependencies for the given request."""
    components: list[Component] = []
    project_files: list[ProjectFile] = []
    environment_variables: list[EnvironmentVariable] = []

    if request.pip_packages:
        environment_variables = [
            EnvironmentVariable(name="PIP_FIND_LINKS", value="deps/pip", kind="path"),
            EnvironmentVariable(name="PIP_NO_INDEX", value="true", kind="literal"),
        ]

    for package in request.pip_packages:
        info = _resolve_pip(
            request.source_dir.join_within_root(package.path),
            request.output_dir,
            package.requirements_files,
            package.requirements_build_files,
        )

        components.append(Component.from_package_dict(info["package"]))

        for dependency in info["dependencies"]:
            components.append(Component.from_package_dict(dependency))

        replaced_requirements_files = map(_replace_external_requirements, info["requirements"])
        project_files.extend(filter(None, replaced_requirements_files))

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=environment_variables,
        project_files=project_files,
    )


def _get_pip_metadata(package_dir: RootedPath) -> tuple[str, str]:
    """
    Attempt to get the name and version of a Pip package.

    First, try to parse the setup.py script (if present) and extract name and version
    from keyword arguments to the setuptools.setup() call. If either name or version
    could not be resolved and there is a setup.cfg file, try to fill in the missing
    values from metadata.name and metadata.version in the .cfg file.

    If either name or version could not be resolved, raise an error.

    :param package_dir: Path to the root directory of a Pip package
    :return: Tuple of strings (name, version)
    :raises PackageRejected: If either name or version could not be resolved
    """
    name = None
    version = None

    setup_py = SetupPY(package_dir)
    setup_cfg = SetupCFG(package_dir)

    if setup_py.exists():
        log.info("Extracting metadata from setup.py")
        name = setup_py.get_name()
        version = setup_py.get_version()
    else:
        log.warning(
            "No setup.py found in directory %s, package is likely not pip compatible", package_dir
        )

    if not (name and version) and setup_cfg.exists():
        log.info("Filling in missing metadata from setup.cfg")
        name = name or setup_cfg.get_name()
        version = version or setup_cfg.get_version()

    if name:
        log.info("Resolved package name: %r", name)
    if version:
        log.info("Resolved package version: %r", version)

    if not (name and version):
        missing = [attr for attr, value in zip(["name", "version"], [name, version]) if not value]
        raise PackageRejected(
            f"Could not resolve package metadata: {', '.join(missing)}",
            solution=(
                "Please specify package metadata in a way that Cachi2 understands (see the docs)."
            ),
            docs=PIP_METADATA_DOC,
        )

    return name, version


def _any_to_version(obj: Any) -> str:
    """
    Convert any python object to a version string.

    https://github.com/pypa/setuptools/blob/ba209a15247b9578d565b7491f88dc1142ba29e4/setuptools/config.py#L535

    :param obj: object to convert to version
    """
    version = obj

    if not isinstance(version, str):
        if hasattr(version, "__iter__"):
            version = ".".join(map(str, version))
        else:
            version = str(version)

    return pkg_resources.safe_version(version)


def _get_top_level_attr(
    body: list[ast.stmt], attr_name: str, before_line: Optional[int] = None
) -> Any:
    """
    Get attribute from module if it is defined at top level and assigned to a literal expression.

    https://github.com/pypa/setuptools/blob/ba209a15247b9578d565b7491f88dc1142ba29e4/setuptools/config.py#L36

    Note that this approach is not equivalent to the setuptools one - setuptools looks for the
    attribute starting from the top, we start at the bottom. Arguably, starting at the bottom
    makes more sense, but it should not make any real difference in practice.

    :param body: The body of an AST node
    :param attr_name: Name of attribute to search for
    :param before_line: Only look for attributes defined before this line

    :rtype: anything that can be expressed as a literal ("primitive" types, collections)
    :raises AttributeError: If attribute not found
    :raises ValueError: If attribute assigned to something that is not a literal
    """
    try:
        return next(
            ast.literal_eval(node.value)
            for node in reversed(body)
            if (before_line is None or node.lineno < before_line) and isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id == attr_name
        )
    except ValueError:
        raise ValueError(f"{attr_name!r} is not assigned to a literal expression")
    except StopIteration:
        raise AttributeError(f"{attr_name!r} not found")


class SetupFile(ABC):
    """Abstract base class for setup.cfg and setup.py handling."""

    def __init__(self, top_dir: RootedPath, file_name: str) -> None:
        """
        Initialize a SetupFile.

        :param top_dir: Path to root of project directory
        :param file_name: Name of Python setup file, expected to be in the root directory
        """
        self._top_dir = top_dir
        self._file_name = file_name

    @property
    def _setup_file(self) -> RootedPath:
        return self._top_dir.join_within_root(self._file_name)

    def exists(self) -> bool:
        """Check if file exists."""
        return self._setup_file.path.is_file()

    @abstractmethod
    def get_name(self) -> Optional[str]:
        """Attempt to determine the package name. Should only be called if file exists."""

    @abstractmethod
    def get_version(self) -> Optional[str]:
        """Attempt to determine the package version. Should only be called if file exists."""


class SetupCFG(SetupFile):
    """
    Parse metadata.name and metadata.version from a setup.cfg file.

    Aims to match setuptools behaviour as closely as possible, but does make
    some compromises (such as never executing arbitrary Python code).
    """

    # Valid Python name - any sequence of \w characters that does not start with a number
    _name_re = re.compile(r"[^\W\d]\w*")

    def __init__(self, top_dir: RootedPath) -> None:
        """
        Initialize a SetupCFG.

        :param top_dir: Path to root of project directory
        """
        super().__init__(top_dir, "setup.cfg")

    def get_name(self) -> Optional[str]:
        """Get metadata.name if present."""
        name = self._get_option("metadata", "name")
        if not name:
            log.info("No metadata.name in setup.cfg")
            return None

        log.info("Found metadata.name in setup.cfg: %r", name)
        return name

    def get_version(self) -> Optional[str]:
        """
        Get metadata.version if present.

        Partially supports the file: directive (setuptools supports multiple files
        as an argument to file:, this makes no sense for version).

        Partially supports the attr: directive (will only work if the attribute
        being referenced is assigned to a literal expression).
        """
        version = self._get_option("metadata", "version")
        if not version:
            log.info("No metadata.version in setup.cfg")
            return None

        log.debug("Resolving metadata.version in setup.cfg from %r", version)
        version = self._resolve_version(version)
        if not version:
            # Falsy values also count as "failed to resolve" (0, None, "", ...)
            log.info("Failed to resolve metadata.version in setup.cfg")
            return None

        version = _any_to_version(version)
        log.info("Found metadata.version in setup.cfg: %r", version)
        return version

    @functools.cached_property
    def _parsed(self) -> Optional[configparser.ConfigParser]:
        """
        Try to parse config file, return None if parsing failed.

        Will not parse file (or try to) more than once.
        """
        log.debug("Parsing setup.cfg at %r", str(self._setup_file))
        parsed = configparser.ConfigParser()

        with self._setup_file.path.open() as f:
            try:
                parsed.read_file(f)
                return parsed
            except configparser.Error as e:
                log.error("Failed to parse setup.cfg: %s", e)
                return None

    def _get_option(self, section: str, option: str) -> Optional[str]:
        """Get option from config section, return None if option missing or file invalid."""
        if self._parsed is None:
            return None
        try:
            return self._parsed.get(section, option)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return None

    def _resolve_version(self, raw_version: str) -> Optional[str]:
        """Attempt to resolve the version attribute."""
        if raw_version.startswith("file:"):
            file_arg = raw_version[len("file:") :].strip()
            version = self._read_version_from_file(file_arg)
        elif raw_version.startswith("attr:"):
            attr_arg = raw_version[len("attr:") :].strip()
            version = self._read_version_from_attr(attr_arg)
        else:
            version = raw_version
        return version

    def _read_version_from_file(self, file_path: str) -> Optional[str]:
        """Read version from file."""
        version_file = self._top_dir.join_within_root(file_path)
        if version_file.path.is_file():
            version = version_file.path.read_text().strip()
            log.debug("Read version from %r: %r", file_path, version)
            return version
        else:
            log.error("Version file %r does not exist or is not a file", file_path)
            return None

    def _read_version_from_attr(self, attr_spec: str) -> Optional[str]:
        """
        Read version from module attribute.

        Like setuptools, will try to find the attribute by looking for Python
        literals in the AST of the module. Unlike setuptools, will not execute
        the module if this fails.

        https://github.com/pypa/setuptools/blob/ba209a15247b9578d565b7491f88dc1142ba29e4/setuptools/config.py#L354

        :param attr_spec: "import path" of attribute, e.g. package.version.__version__
        """
        module_name, _, attr_name = attr_spec.rpartition(".")
        if not module_name:
            # Assume current directory is a package, look for attribute in __init__.py
            module_name = "__init__"

        log.debug("Attempting to find attribute %r in %r", attr_name, module_name)

        module_file = self._find_module(module_name, self._get_package_dirs())
        if module_file is not None:
            log.debug("Found module %r at %r", module_name, str(module_file))
        else:
            log.error("Module %r not found", module_name)
            return None

        try:
            module_ast = ast.parse(module_file.path.read_text(), module_file.path.name)
        except SyntaxError as e:
            log.error("Syntax error when parsing module: %s", e)
            return None

        try:
            version = _get_top_level_attr(module_ast.body, attr_name)
            log.debug("Found attribute %r in %r: %r", attr_name, module_name, version)
            return version
        except (AttributeError, ValueError) as e:
            log.error("Could not find attribute in %r: %s", module_name, e)
            return None

    def _find_module(
        self, module_name: str, package_dir: Optional[dict[str, str]] = None
    ) -> Optional[RootedPath]:
        """
        Try to find a module in the project directory and return path to source file.

        :param module_name: "import path" of module
        :param package_dir: same semantics as options.package_dir in setup.cfg
        """
        module_path = self._convert_to_path(module_name)
        root_module = module_path.parts[0]

        package_dir = package_dir or {}

        if root_module in package_dir:
            custom_path = Path(package_dir[root_module])
            log.debug("Custom path set for root module %r: %r", root_module, str(custom_path))
            # Custom path replaces the root module
            module_path = custom_path.joinpath(*module_path.parts[1:])
        elif "" in package_dir:
            custom_path = Path(package_dir[""])
            log.debug("Custom path set for all root modules: %r", str(custom_path))
            # Custom path does not replace the root module
            module_path = custom_path / module_path

        package_init = self._top_dir.join_within_root(module_path).join_within_root("__init__.py")
        if package_init.path.is_file():
            return package_init

        module_py = self._top_dir.join_within_root(f"{module_path}.py")
        if module_py.path.is_file():
            return module_py

        return None

    def _convert_to_path(self, module_name: str) -> Path:
        """Check that module name is valid and covert to file path."""
        parts = module_name.split(".")
        if not parts[0]:
            # Relative import (supported only to the extent that one leading '.' is ignored)
            parts.pop(0)
        if not all(self._name_re.fullmatch(part) for part in parts):
            raise PackageRejected(
                f"{module_name!r} is not an accepted module name",
                solution=None,
            )
        return Path(*parts)

    def _get_package_dirs(self) -> Optional[dict[str, str]]:
        """
        Get options.package_dir and convert to dict if present.

        https://github.com/pypa/setuptools/blob/ba209a15247b9578d565b7491f88dc1142ba29e4/setuptools/config.py#L264
        """
        package_dir_value = self._get_option("options", "package_dir")
        if package_dir_value is None:
            return None

        if "\n" in package_dir_value:
            package_items: Iterable[str] = package_dir_value.splitlines()
        else:
            package_items = package_dir_value.split(",")

        # Strip whitespace and discard empty values
        package_items = filter(bool, (p.strip() for p in package_items))

        package_dirs = {}
        for item in package_items:
            package, sep, p_dir = item.partition("=")
            if sep:
                # Otherwise value was malformed ('=' was missing)
                package_dirs[package.strip()] = p_dir.strip()

        return package_dirs


@dataclass(frozen=True)
class ASTPathElement:
    """An element of AST path."""

    node: ast.AST
    attr: str  # Child node is (in) this field
    index: Optional[int] = None  # If field is a list, this is the index of the child node

    @property
    def field(self) -> Any:
        """Return field referenced by self.attr."""
        return getattr(self.node, self.attr)

    def field_is_body(self) -> bool:
        r"""
        Check if the field is a body (a list of statement nodes).

        All 'stmt*' attributes here: https://docs.python.org/3/library/ast.html#abstract-grammar

        Check with the following command:

            curl 'https://docs.python.org/3/library/ast.html#abstract-grammar' |
            grep -E 'stmt\* \w+' --only-matching |
            sort -u
        """
        return self.attr in ("body", "orelse", "finalbody")

    def __str__(self) -> str:
        """Make string representation of path element: <type>(<lineno>).<field>[<index>]."""
        s = self.node.__class__.__name__
        if hasattr(self.node, "lineno"):
            s += f"(#{self.node.lineno})"
        s += f".{self.attr}"
        if self.index is not None:
            s += f"[{self.index}]"
        return s


@dataclass(frozen=True)
class SetupBranch:
    """Setup call node, path to setup call from root node."""

    call_node: ast.Call
    node_path: list[ASTPathElement]


class SetupPY(SetupFile):
    """
    Find the setup() call in a setup.py file and extract the `name` and `version` kwargs.

    Will only work for very basic use cases - value of keyword argument must be a literal
    expression or a variable assigned to a literal expression.

    Some supported examples:

    1) trivial

        from setuptools import setup

        setup(name="foo", version="1.0.0")

    2) if __main__

        import setuptools

        name = "foo"
        version = "1.0.0"

        if __name__ == "__main__":
            setuptools.setup(name=name, version=version)

    3) my_setup()

        import setuptools

        def my_setup():
            name = "foo"
            version = "1.0.0"

            setuptools.setup(name=name, version=version)

        my_setup()

    For examples 2) and 3), we do not actually resolve any conditions or check that the
    function containing the setup() call is eventually executed. We simply assume that,
    this being the setup.py script, setup() will end up being called no matter what.
    """

    def __init__(self, top_dir: RootedPath) -> None:
        """
        Initialize a SetupPY.

        :param top_dir: Path to root of project directory
        """
        super().__init__(top_dir, "setup.py")

    def get_name(self) -> Optional[str]:
        """Attempt to extract package name from setup.py."""
        name = self._get_setup_kwarg("name")
        if not name or not isinstance(name, str):
            log.info(
                "Name in setup.py was either not found, or failed to resolve to a valid string"
            )
            return None

        log.info("Found name in setup.py: %r", name)
        return name

    def get_version(self) -> Optional[str]:
        """
        Attempt to extract package version from setup.py.

        As of setuptools version 49.2.1, there is no special logic for passing
        an iterable as version in setup.py. Unlike name, however, it does support
        non-string arguments (except tuples with len() != 1, those break horribly).

        https://github.com/pypa/setuptools/blob/5e60dc50e540a942aeb558aabe7d92ab7eb13d4b/setuptools/dist.py#L462

        Rather than trying to keep edge cases consistent with setuptools, treat them
        consistently within Cachi2.
        """
        version = self._get_setup_kwarg("version")
        if not version:
            # Only truthy values are valid, not any of (0, None, "", ...)
            log.info(
                "Version in setup.py was either not found, or failed to resolve to a valid value"
            )
            return None

        version = _any_to_version(version)
        log.info("Found version in setup.py: %r", version)
        return version

    @functools.cached_property
    def _ast(self) -> Optional[ast.AST]:
        """Try to parse the AST."""
        log.debug("Parsing setup.py at %r", str(self._setup_file))
        try:
            return ast.parse(self._setup_file.path.read_text(), self._setup_file.path.name)
        except SyntaxError as e:
            log.error("Syntax error when parsing setup.py: %s", e)
            return None

    @functools.cached_property
    def _setup_branch(self) -> Optional[SetupBranch]:
        """
        Find setup() call anywhere in the file, return setup branch.

        The file is expected to contain only one setup call. If there are two or more,
        we cannot safely determine which one gets called. In such a case, we will simply
        find and process the first one.

        If setup call not found, return None.
        """
        if self._ast is None:
            return None

        setup_call, setup_path = self._find_setup_call(self._ast)
        if setup_call is None:
            log.error("File does not seem to have a setup call")
            return None

        setup_path.reverse()  # Path is in reverse order
        log.debug("Found setup call on line %s", setup_call.lineno)
        path_repr = " -> ".join(map(str, setup_path))
        log.debug("Pseudo-path: %s", path_repr)
        return SetupBranch(setup_call, setup_path)

    def _find_setup_call(
        self, root_node: ast.AST
    ) -> tuple[Optional[ast.Call], list[ASTPathElement]]:
        """
        Find setup() or setuptools.setup() call anywhere in or under root_node.

        Return call node and path from root node to call node (reversed).
        """
        if self._is_setup_call(root_node):
            return root_node, []

        for name, field in ast.iter_fields(root_node):
            # Field is a node
            if isinstance(field, ast.AST):
                setup_call, setup_path = self._find_setup_call(field)
                if setup_call is not None:
                    setup_path.append(ASTPathElement(root_node, name))
                    return setup_call, setup_path
            # Field is a list of nodes (use any(), nodes will never be mixed with non-nodes)
            elif isinstance(field, list) and any(isinstance(x, ast.AST) for x in field):
                for i, node in enumerate(field):
                    setup_call, setup_path = self._find_setup_call(node)
                    if setup_call is not None:
                        setup_path.append(ASTPathElement(root_node, name, i))
                        return setup_call, setup_path

        return None, []  # No setup call under root_node

    def _is_setup_call(self, node: ast.AST) -> "TypeGuard[ast.Call]":
        """Check if node is setup() or setuptools.setup() call."""
        if not isinstance(node, ast.Call):
            return False

        fn = node.func
        return (isinstance(fn, ast.Name) and fn.id == "setup") or (
            isinstance(fn, ast.Attribute)
            and fn.attr == "setup"
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "setuptools"
        )

    def _get_setup_kwarg(self, arg_name: str) -> Optional[Any]:
        """
        Find setup() call, extract specified argument from keyword arguments.

        If argument value is a variable, then what we do is only a very loose approximation
        of how Python resolves variables. None of the following examples will work:

        1) any indented blocks (unless setup() call appears under the same block)

            with x:
                name = "foo"

            setup(name=name)

        2) late binding

            def my_setup():
                setup(name=name)

            name = "foo"

            my_setup()

        The rationale for not supporting these cases:
        - it is difficult
        - there is no use case for 1) which is both valid and possible to resolve safely
        - 2) seems like a bad enough practice to justify ignoring it
        """
        if self._setup_branch is None:
            return None

        for kw in self._setup_branch.call_node.keywords:
            if kw.arg == arg_name:
                try:
                    value = ast.literal_eval(kw.value)
                    log.debug("setup kwarg %r is a literal: %r", arg_name, value)
                    return value
                except ValueError:
                    pass

                if isinstance(kw.value, ast.Name):
                    log.debug("setup kwarg %r looks like a variable", arg_name)
                    return self._get_variable(
                        kw.value.id, self._setup_branch.call_node, self._setup_branch.node_path
                    )

                expr_type = kw.value.__class__.__name__
                log.error("setup kwarg %r is an unsupported expression: %s", arg_name, expr_type)
                return None

        log.debug("setup kwarg %r not found", arg_name)
        return None

    def _get_variable(
        self, var_name: str, call_node: ast.Call, path_to_call_node: list[ASTPathElement]
    ) -> Optional[Any]:
        """Walk back up the AST along setup branch, look for first assignment of variable."""
        lineno = call_node.lineno

        log.debug("Backtracking up the AST from line %s to find variable %r", lineno, var_name)

        for elem in filter(ASTPathElement.field_is_body, reversed(path_to_call_node)):
            try:
                value = _get_top_level_attr(elem.field, var_name, lineno)
                log.debug("Found variable %r: %r", var_name, value)
                return value
            except ValueError as e:
                log.error("Variable cannot be resolved: %s", e)
                return None
            except AttributeError:
                pass

        log.error("Variable %r not found along the setup call branch", var_name)
        return None


class PipRequirementsFile:
    """Parse requirements from a pip requirements file."""

    # Comment lines start with optional leading spaces followed by "#"
    LINE_COMMENT = re.compile(r"(^|\s)#.*$")

    # Options allowed in a requirements file. The values represent whether or not the option
    # requires a value.
    # https://pip.pypa.io/en/stable/reference/pip_install/#requirements-file-format
    OPTIONS = {
        "--constraint": True,
        "--editable": False,  # The required value is the requirement itself, not a parameter
        "--extra-index-url": True,
        "--find-links": True,
        "--index-url": True,
        "--no-binary": True,
        "--no-index": False,
        "--only-binary": True,
        "--pre": False,
        "--prefer-binary": False,
        "--require-hashes": False,
        "--requirement": True,
        "--trusted-host": True,
        "--use-feature": True,
        "-c": True,
        "-e": False,  # The required value is the requirement itself, not a parameter
        "-f": True,
        "--hash": True,
        "-i": True,
        "-r": True,
    }

    # Options that are specific to a single requirement in the requirements file. All other
    # options apply to all the requirements.
    REQUIREMENT_OPTIONS = {"-e", "--editable", "--hash"}

    def __init__(self, file_path):
        """Initialize a PipRequirementsFile.

        :param str | PathLike[str] file_path: the full path to the requirements file
        """
        self.file_path = file_path
        self.__parsed = NOTHING

    @classmethod
    def from_requirements_and_options(cls, requirements, options):
        """Create a new PipRequirementsFile instance from given parameters.

        :param list requirements: list of PipRequirement instances
        :param list options: list of strings of global options
        :return: new instance of PipRequirementsFile
        """
        new_instance = cls(None)
        new_instance.__parsed = {"requirements": list(requirements), "options": list(options)}
        return new_instance

    def write(self, file_obj: IO[str]) -> None:
        """Write the options and requirements to a file."""
        if self.options:
            file_obj.write(" ".join(self.options))
            file_obj.write("\n")
        for requirement in self.requirements:
            file_obj.write(str(requirement))
            file_obj.write("\n")

    def generate_file_content(self) -> str:
        """Generate the file content from the parsed options and requirements."""
        fileobj = io.StringIO()
        self.write(fileobj)
        return fileobj.getvalue()

    @property
    def requirements(self):
        """Return a list of PipRequirement objects."""
        return self._parsed["requirements"]

    @property
    def options(self):
        """Return a list of options."""
        return self._parsed["options"]

    @property
    def _parsed(self):
        """Return the parsed requirements file.

        :return: a dict with the keys ``requirements`` and ``options``
        """
        if self.__parsed is NOTHING:
            parsed = {"requirements": [], "options": []}

            for line in self._read_lines():
                (
                    global_options,
                    requirement_options,
                    requirement_line,
                ) = self._split_options_and_requirement(line)
                if global_options:
                    parsed["options"].extend(global_options)

                if requirement_line:
                    parsed["requirements"].append(
                        PipRequirement.from_line(requirement_line, requirement_options)
                    )

            self.__parsed = parsed

        return self.__parsed

    def _read_lines(self):
        """Read and yield the lines from the requirements file.

        Lines ending in the line continuation character are joined with the next line.
        Comment lines are ignored.
        """
        buffered_line = []

        with open(self.file_path) as f:
            for line in f.read().splitlines():
                if not line.endswith("\\"):
                    buffered_line.append(line)
                    new_line = "".join(buffered_line)
                    new_line = self.LINE_COMMENT.sub("", new_line).strip()
                    if new_line:
                        yield new_line
                    buffered_line = []
                else:
                    buffered_line.append(line.rstrip("\\"))

        # Last line ends in "\"
        if buffered_line:
            yield "".join(buffered_line)

    def _split_options_and_requirement(self, line):
        """Split global and requirement options from the requirement line.

        :param str line: requirement line from the requirements file
        :return: three-item tuple where the first item is a list of global options, the
            second item a list of requirement options, and the last item a str of the
            requirement without any options.
        """
        global_options = []
        requirement_options = []
        requirement = []

        # Indicates the option must be followed by a value
        _require_value = False
        # Reference to either global_options or requirement_options list
        _context_options = None

        for part in line.split():
            if _require_value:
                _context_options.append(part)
                _require_value = False
            elif part.startswith("-"):
                option = None
                value = None
                if "=" in part:
                    option, value = part.split("=", 1)
                else:
                    option = part

                if option not in self.OPTIONS:
                    raise UnexpectedFormat(f"Unknown requirements file option {part!r}")

                _require_value = self.OPTIONS[option]

                if option in self.REQUIREMENT_OPTIONS:
                    _context_options = requirement_options
                else:
                    _context_options = global_options

                if value and not _require_value:
                    raise UnexpectedFormat(
                        f"Unexpected value for requirements file option {part!r}"
                    )

                _context_options.append(option)
                if value:
                    _context_options.append(value)
                    _require_value = False
            else:
                requirement.append(part)

        if _require_value:
            raise UnexpectedFormat(
                f"Requirements file option {_context_options[-1]!r} requires a value"
            )

        if requirement_options and not requirement:
            raise UnexpectedFormat(
                f"Requirements file option(s) {requirement_options!r} can only be applied to a "
                "requirement",
            )

        return global_options, requirement_options, " ".join(requirement)


class PipRequirement:
    """Parse a requirement and its options from a requirement line."""

    URL_SCHEMES = {"http", "https", "ftp"}

    VCS_SCHEMES = {
        "bzr",
        "bzr+ftp",
        "bzr+http",
        "bzr+https",
        "git",
        "git+ftp",
        "git+http",
        "git+https",
        "hg",
        "hg+ftp",
        "hg+http",
        "hg+https",
        "svn",
        "svn+ftp",
        "svn+http",
        "svn+https",
    }

    # Regex used to determine if a direct access requirement specifies a
    # package name, e.g. "name @ https://..."
    HAS_NAME_IN_DIRECT_ACCESS_REQUIREMENT = re.compile(r"@.+://")

    def __init__(self):
        """Initialize a PipRequirement."""
        # The package name after it has been processed by setuptools, e.g. "_" are replaced
        # with "-"
        self.package = None
        # The package name as defined in the requirement line
        self.raw_package = None
        self.extras = []
        self.version_specs = []
        self.environment_marker = None
        self.hashes = []
        self.qualifiers = {}

        self.kind = None
        self.download_line = None

        self.options = []

        self._url = None

    @property
    def url(self):
        """Extract the URL from the download line of a VCS or URL requirement."""
        if self._url is None:
            if self.kind not in ("url", "vcs"):
                raise ValueError(f"Cannot extract URL from {self.kind} requirement")
            # package @ url ; environment_marker
            parts = self.download_line.split()
            self._url = parts[2]

        return self._url

    def __str__(self):
        """Return the string representation of the PipRequirement."""
        line = []
        line.extend(self.options)
        line.append(self.download_line)
        line.extend(f"--hash={h}" for h in self.hashes)
        return " ".join(line)

    def copy(self, url=None, hashes=None):
        """Duplicate this instance of PipRequirement.

        :param str url: set a new direct access URL for the requirement. If provided, the
            new requirement is always of ``url`` kind.
        :param list hashes: overwrite hash values for the new requirement
        :return: new PipRequirement instance
        """
        options = list(self.options)
        download_line = self.download_line
        if url:
            download_line_parts = []
            download_line_parts.append(self.raw_package)
            download_line_parts.append("@")

            qualifiers_line = "&".join(f"{key}={value}" for key, value in self.qualifiers.items())
            if qualifiers_line:
                download_line_parts.append(f"{url}#{qualifiers_line}")
            else:
                download_line_parts.append(url)

            if self.environment_marker:
                download_line_parts.append(";")
                download_line_parts.append(self.environment_marker)

            download_line = " ".join(download_line_parts)

            # Pip does not support editable mode for requirements installed via an URL, only
            # via VCS. Remove this option to avoid errors later on.
            options = list(set(self.options) - {"-e", "--editable"})
            if self.options != options:
                log.warning(
                    "Removed editable option when copying the requirement %r", self.raw_package
                )

        requirement = self.__class__()

        requirement.package = self.package
        requirement.raw_package = self.raw_package
        # Extras are incorrectly treated as part of the URL itself. If we're setting
        # the URL, clear them.
        requirement.extras = [] if url else list(self.extras)
        # Version specs are ignored by pip when applied to a URL, let's do the same.
        requirement.version_specs = [] if url else list(self.version_specs)
        requirement.environment_marker = self.environment_marker
        requirement.hashes = list(hashes or self.hashes)
        requirement.qualifiers = dict(self.qualifiers)
        requirement.kind = "url" if url else self.kind
        requirement.download_line = download_line
        requirement.options = options

        return requirement

    @classmethod
    def from_line(cls, line, options):
        """Create an instance of PipRequirement from the given requirement and its options.

        Only ``url`` and ``vcs`` direct access requirements are supported. ``file`` is not.

        :param str line: the requirement line
        :param str list: the options associated with the requirement
        :return: PipRequirement instance
        """
        to_be_parsed = line
        qualifiers = {}
        requirement = cls()

        direct_access_kind, is_direct_access = cls._assess_direct_access_requirement(line)
        if is_direct_access:
            if direct_access_kind in ["url", "vcs"]:
                requirement.kind = direct_access_kind
                to_be_parsed, qualifiers = cls._adjust_direct_access_requirement(to_be_parsed)
            else:
                raise UnsupportedFeature(
                    f"Direct references with {direct_access_kind!r} scheme are not supported, "
                    f"{to_be_parsed!r}"
                )
        else:
            requirement.kind = "pypi"

        try:
            parsed = list(pkg_resources.parse_requirements(to_be_parsed))
        except (
            pkg_resources.RequirementParseError,
            pkg_resources.extern.packaging.requirements.InvalidRequirement,
        ) as exc:
            # see https://github.com/pypa/setuptools/pull/2137
            raise UnexpectedFormat(f"Unable to parse the requirement {to_be_parsed!r}: {exc}")

        if not parsed:
            return None
        # parse_requirements is able to process a multi-line string, thus returning multiple
        # parsed requirements. However, since it cannot handle the additional syntax from a
        # requirements file, we parse each line individually. The conditional below should
        # never be reached, but is left here to aid diagnosis in case this assumption is
        # not correct.
        if len(parsed) > 1:
            raise RuntimeError(f"Didn't expect to find multiple requirements in: {line!r}")
        parsed = parsed[0]

        hashes, options = cls._split_hashes_from_options(options)

        requirement.download_line = to_be_parsed
        requirement.options = options
        requirement.package = parsed.project_name
        requirement.raw_package = parsed.name
        requirement.version_specs = parsed.specs
        requirement.extras = parsed.extras
        requirement.environment_marker = str(parsed.marker) if parsed.marker else None
        requirement.hashes = hashes
        requirement.qualifiers = qualifiers

        return requirement

    @classmethod
    def _assess_direct_access_requirement(cls, line):
        """Determine if the line contains a direct access requirement.

        :param str line: the requirement line
        :return: two-item tuple where the first item is the kind of dicrect access requirement,
            e.g. "vcs", and the second item is a bool indicating if the requirement is a
            direct access requirement
        """
        direct_access_kind = None

        if ":" not in line:
            return None, False
        # Extract the scheme from the line and strip off the package name if needed
        # e.g. name @ https://...
        scheme_parts = line.split(":", 1)[0].split("@")
        if len(scheme_parts) > 2:
            raise UnexpectedFormat(
                f"Unable to extract scheme from direct access requirement {line!r}"
            )
        scheme = scheme_parts[-1].lower().strip()

        if scheme in cls.URL_SCHEMES:
            direct_access_kind = "url"
        elif scheme in cls.VCS_SCHEMES:
            direct_access_kind = "vcs"
        else:
            direct_access_kind = scheme

        return direct_access_kind, True

    @classmethod
    def _adjust_direct_access_requirement(cls, line):
        """Modify the requirement line so it can be parsed by pkg_resources and extract qualifiers.

        :param str line: a direct access requirement line
        :return: two-item tuple where the first item is a modified direct access requirement
            line that can be parsed by pkg_resources, and the second item is a dict of the
            qualifiers extracted from the direct access URL
        """
        package_name = None
        qualifiers = {}
        url = line
        environment_marker = None

        if cls.HAS_NAME_IN_DIRECT_ACCESS_REQUIREMENT.search(line):
            package_name, url = line.split("@", 1)

        # For direct access requirements, a space is needed after the semicolon.
        if "; " in url:
            url, environment_marker = url.split("; ", 1)

        parsed_url = urllib.parse.urlparse(url)
        if parsed_url.fragment:
            for section in parsed_url.fragment.split("&"):
                if "=" in section:
                    attr, value = section.split("=", 1)
                    value = urllib.parse.unquote(value)
                    qualifiers[attr] = value
                    if attr == "egg":
                        # Use the egg name as the package name to avoid ambiguity when both are
                        # provided. This matches the behavior of "pip install".
                        package_name = value

        if not package_name:
            raise UnsupportedFeature(
                reason=(
                    f"Dependency name could not be determined from the requirement {line!r} "
                    "(Cachi2 needs the name to be explicitly declared)"
                ),
                solution="Please specify the name of the dependency: <name> @ <url>",
                docs=PIP_EXTERNAL_DEPS_DOC,
            )

        requirement_parts = [package_name.strip(), "@", url.strip()]
        if environment_marker:
            # Although a space before the semicolon is not needed by pip, it is needed when
            # using pkg_resources later on.
            requirement_parts.append(";")
            requirement_parts.append(environment_marker.strip())
        return " ".join(requirement_parts), qualifiers

    @classmethod
    def _split_hashes_from_options(cls, options):
        """Separate the --hash options from the given options.

        :param list options: requirement options
        :return: two-item tuple where the first item is a list of hashes, and the second item
            is a list of options without any ``--hash`` options
        """
        hashes = []
        reduced_options = []
        is_hash = False

        for item in options:
            if is_hash:
                hashes.append(item)
                is_hash = False
                continue

            is_hash = item == "--hash"
            if not is_hash:
                reduced_options.append(item)

        return hashes, reduced_options


def _download_dependencies(
    output_dir: RootedPath, requirements_file: PipRequirementsFile
) -> list[dict[str, Any]]:
    """
    Download sdists (source distributions) of all dependencies in a requirements.txt file.

    :param output_dir: the root output directory for this request
    :param requirements_file: A requirements.txt file
    :return: Info about downloaded packages; all items will contain "kind" and "path" keys
        (and more based on kind, see _download_*_package functions for more details)
    :rtype: list[dict]
    """
    options = _process_options(requirements_file.options)
    trusted_hosts = set(options["trusted_hosts"])

    if options["require_hashes"]:
        log.info("Global --require-hashes option used, will require hashes")
        require_hashes = True
    elif any(req.hashes for req in requirements_file.requirements):
        log.info("At least one dependency uses the --hash option, will require hashes")
        require_hashes = True
    else:
        log.info(
            "No hash options used, will not require hashes unless HTTP(S) dependencies are present."
        )
        require_hashes = False

    _validate_requirements(requirements_file.requirements)
    _validate_provided_hashes(requirements_file.requirements, require_hashes)

    pip_deps_dir = output_dir.join_within_root("deps", "pip")
    pip_deps_dir.path.mkdir(parents=True, exist_ok=True)

    downloads = []

    for req in requirements_file.requirements:
        log.info("Downloading %s", req.download_line)

        if req.kind == "pypi":
            download_info = _download_pypi_package(req, pip_deps_dir, PYPI_URL)
            _check_metadata_in_sdist(download_info["path"])
        elif req.kind == "vcs":
            download_info = _download_vcs_package(req, pip_deps_dir)
        elif req.kind == "url":
            download_info = _download_url_package(req, pip_deps_dir, trusted_hosts)
        else:
            # Should not happen
            raise RuntimeError(f"Unexpected requirement kind: {req.kind!r}")

        log.info(
            "Successfully downloaded %s to %s",
            req.download_line,
            download_info["path"].relative_to(output_dir),
        )

        if require_hashes or req.kind == "url":
            hashes = req.hashes or [req.qualifiers["cachito_hash"]]
            _verify_hash(download_info["path"], hashes)

        download_info["kind"] = req.kind
        downloads.append(download_info)

    return downloads


def _process_options(options):
    """
    Process global options from a requirements.txt file.

    | Rejected option     | Reason                                                  |
    |---------------------|---------------------------------------------------------|
    | -i --index-url      | We only support the index which our proxy supports      |
    | --extra-index-url   | We only support one index                               |
    | --no-index          | Index is the only thing we support                      |
    | -f --find-links     | We only support index                                   |
    | --only-binary       | Only sdist                                              |

    | Ignored option      | Reason                                                  |
    |---------------------|---------------------------------------------------------|
    | -c --constraint     | All versions must already be pinned                     |
    | -e --editable       | Only relevant when installing                           |
    | --no-binary         | Implied                                                 |
    | --prefer-binary     | Prefer sdist                                            |
    | --pre               | We do not care if version is pre-release (it is pinned) |
    | --use-feature       | We probably do not have that feature                    |
    | -* --*              | Did not exist when this implementation was done         |

    | Undecided option    | Reason                                                  |
    |---------------------|---------------------------------------------------------|
    | -r --requirement    | We could support this but there is no good reason to    |

    | Relevant option     | Reason                                                  |
    |---------------------|---------------------------------------------------------|
    | --require-hashes    | Hashes are optional, so this makes sense                |
    | --trusted-host      | Disables SSL verification for URL dependencies          |

    :param list[str] options: Global options from a requirements file
    :return: Dict with all the relevant options and their values
    :raise UnsupportedFeature: If any option was rejected
    """
    reject = {
        "-i",
        "--index-url",
        "--extra-index-url",
        "--no-index",
        "-f",
        "--find-links",
        "--only-binary",
    }

    require_hashes = False
    trusted_hosts = []
    ignored = []
    rejected = []

    i = 0
    while i < len(options):
        option = options[i]

        if option == "--require-hashes":
            require_hashes = True
        elif option == "--trusted-host":
            trusted_hosts.append(options[i + 1])
            i += 1
        elif option in reject:
            rejected.append(option)
        elif option.startswith("-"):
            # This is a bit simplistic, option arguments may also start with a '-' but
            # should be good enough for a log message
            ignored.append(option)

        i += 1

    if ignored:
        msg = f"Cachi2 will ignore the following options: {', '.join(ignored)}"
        log.info(msg)

    if rejected:
        msg = f"Cachi2 does not support the following options: {', '.join(rejected)}"
        raise UnsupportedFeature(msg)

    return {
        "require_hashes": require_hashes,
        "trusted_hosts": trusted_hosts,
    }


def _validate_requirements(requirements):
    """
    Validate that all requirements meet Cachi2 expectations.

    :param list[PipRequirement] requirements: All requirements from a file
    :raise PackageRejected: If any requirement does not meet expectations
    :raise UnsupportedFeature: If any requirement uses unsupported features
    """
    for req in requirements:
        # Fail if PyPI requirement is not pinned to an exact version
        if req.kind == "pypi":
            vspec = req.version_specs
            if len(vspec) != 1 or vspec[0][0] not in ("==", "==="):
                msg = f"Requirement must be pinned to an exact version: {req.download_line}"
                raise PackageRejected(
                    msg,
                    solution=(
                        "Please pin all packages as <name>==<version>\n"
                        "You may wish to use a tool such as pip-compile to pin automatically."
                    ),
                    docs=PIP_REQUIREMENTS_TXT_DOC,
                )

        # Fail if VCS requirement uses any VCS other than git or does not have a valid ref
        elif req.kind == "vcs":
            url = urllib.parse.urlparse(req.url)

            if not url.scheme.startswith("git"):
                raise UnsupportedFeature(
                    f"Unsupported VCS for {req.download_line}: {url.scheme} (only git is supported)"
                )

            if not GIT_REF_IN_PATH.search(url.path):
                msg = f"No git ref in {req.download_line} (expected 40 hexadecimal characters)"
                raise PackageRejected(
                    msg,
                    solution=(
                        "Please specify the full commit hash for git URLs or switch to https URLs."
                    ),
                    docs=PIP_EXTERNAL_DEPS_DOC,
                )

        # Fail if URL requirement does not specify exactly one hash (--hash or #cachito_hash)
        # or does not have a recognized file extension
        elif req.kind == "url":
            n_hashes = len(req.hashes) + (1 if req.qualifiers.get("cachito_hash") else 0)
            if n_hashes != 1:
                msg = (
                    f"URL requirement must specify exactly one hash, but specifies {n_hashes}: "
                    f"{req.download_line}."
                )
                raise PackageRejected(
                    msg,
                    solution=(
                        "Please specify the expected hashes for all plain URLs using "
                        "--hash options (one --hash for each)"
                    ),
                    docs=PIP_EXTERNAL_DEPS_DOC,
                )

            url = urllib.parse.urlparse(req.url)
            if not any(url.path.endswith(ext) for ext in SDIST_FILE_EXTENSIONS):
                msg = (
                    "URL for requirement does not contain any recognized file extension: "
                    f"{req.download_line} (expected one of {', '.join(SDIST_FILE_EXTENSIONS)})"
                )
                raise PackageRejected(msg, solution=None)


def _validate_provided_hashes(requirements, require_hashes):
    """
    Validate that hashes are not missing and follow the "algorithm:digest" format.

    :param list[PipRequirement] requirements: All requirements from a file
    :param bool require_hashes: True if hashes are required for all requirements
    :raise PackageRejected: If hashes are missing or have invalid format
    """
    for req in requirements:
        if req.kind == "url":
            hashes = req.hashes or [req.qualifiers["cachito_hash"]]
        else:
            hashes = req.hashes

        if require_hashes and not hashes:
            # This can only happen for non-URL requirements
            # For URL requirements, having a hash is required to pass basic validation
            msg = f"Hash is required, dependency does not specify any: {req.download_line}"
            raise PackageRejected(
                msg,
                solution="Please specify the expected hashes for all dependencies",
                docs=PIP_REQUIREMENTS_TXT_DOC,
            )

        for hash_spec in hashes:
            algorithm, _, digest = hash_spec.partition(":")
            if not digest:
                msg = f"Not a valid hash specifier: {hash_spec!r} (expected algorithm:digest)"
                raise PackageRejected(msg, solution=None)


def _download_pypi_package(requirement, pip_deps_dir, pypi_url, pypi_auth=None):
    """
    Download the sdist (source distribution) of a PyPI package.

    The package must be pinned to an exact version using the '==' (or '===') operator.
    While the specification defines the '==' operator as slightly magical (reference:
    https://www.python.org/dev/peps/pep-0440/#version-matching), we treat the version
    as exact (after normalization).

    Does not download any dependencies (implied: ignores extras). Ignores environment
    markers (target environment is not known to Cachi2).

    :param PipRequirement requirement: PyPI requirement from a requirement.txt file
    :param RootedPath pip_deps_dir: The deps/pip directory in a Cachi2 request bundle
    :param str pypi_url: URL of the PyPI server or a proxy
    :param (requests.auth.AuthBase | None) pypi_auth: Authorization for the PyPI server

    :return: Dict with package name, version and download path
    :raises FetchError: if PyPI query failed
    :raises PackageRejected: if sdists for the package is not found or yanked
    """
    timeout = get_config().requests_timeout
    package = requirement.package
    version = requirement.version_specs[0][1]

    # See https://www.python.org/dev/peps/pep-0503/
    package_url = f"{pypi_url.rstrip('/')}/simple/{canonicalize_name(package)}/"
    try:
        pypi_resp = pkg_requests_session.get(package_url, auth=pypi_auth, timeout=timeout)
        pypi_resp.raise_for_status()
    except requests.RequestException as e:
        raise FetchError(f"PyPI query failed: {e}")

    html = bs4.BeautifulSoup(pypi_resp.text, "html.parser")
    # Find all anchors anywhere in the doc, the PEP does not specify where they should be
    links = html.find_all("a")

    sdists = _process_package_links(links, package, version)
    if not sdists:
        raise PackageRejected(
            f"No sdists found for package {package}=={version}",
            solution=(
                "It seems that this version does not exist or isn't published as a sdist "
                "(a zip or a tarball).\n"
                "You may be able to specify the dependency directly via a URL instead, "
                "for example the tarball for a GitHub release."
            ),
            docs=PIP_NO_SDIST_DOC,
        )

    # Choose best candidate based on sorting key
    sdist = max(sdists, key=_sdist_preference)
    if sdist.get("yanked", False):
        raise PackageRejected(
            f"All sdists for package {package}=={version} are yanked",
            solution=(
                f"Please update the {package} version in your requirements file.\n"
                "Usually, when a version gets yanked from PyPI, there will already "
                "be a fixed version available.\n"
                "Otherwise, you may need to pin to the previous version."
            ),
        )

    download_to = pip_deps_dir.join_within_root(sdist["filename"])

    # URLs may be absolute or relative, see https://peps.python.org/pep-0503/
    sdist_url = urllib.parse.urljoin(package_url, sdist["url"])
    download_binary_file(sdist_url, download_to.path, auth=pypi_auth)

    return {
        "package": sdist["name"],
        "version": sdist["version"],
        "path": download_to.path,
    }


def _process_package_links(links, name, version):
    """
    Process links to Python packages.

    Pick out sdists at the specified version, return metadata about found sdists.

    :param Iterable links: Iterable of html anchor elements
    :param str name: Package name
    :param str version: Package version
    :return: List of dicts with processed metadata
    """
    canonical_name = canonicalize_name(name)
    canonical_version = canonicalize_version(version)

    # When matching package name, use a regex that will match any non-canonical
    # variation of the canonical name (it also needs to be case-insensitive).
    # See https://www.python.org/dev/peps/pep-0503/#normalized-names.
    noncanonical_name_pattern = re.escape(canonical_name).replace("\\-", "[-_.]+")
    sdist_re = re.compile(
        # <name>-<version><extension>
        rf"^({noncanonical_name_pattern})-(.+)(?:{SDIST_EXT_PATTERN})$",
        re.IGNORECASE,
    )

    sdists = []

    for link in links:
        match = sdist_re.match(link.text)
        if not match:
            continue

        name, version = match.groups()
        if canonical_version != canonicalize_version(version):
            continue

        sdists.append(
            {
                "name": name,
                "version": version,
                "filename": link.text,
                "url": link.get("href"),
                # https://www.python.org/dev/peps/pep-0592/
                "yanked": link.get("data-yanked") is not None,
            }
        )

    return sdists


def _sdist_preference(sdist_pkg):
    """
    Compute preference for a sdist package, can be used to sort in ascending order.

    Prefer files that are not yanked over ones that are.
    Within the same category (yanked vs. not), prefer .tar.gz > .zip > anything else.

    :param dict sdist_pkg: An item of the "urls" array in a PyPI response
    :return: Tuple of integers to use as sorting key
    """
    # Higher number = higher preference
    yanked_pref = 0 if sdist_pkg.get("yanked", False) else 1

    filename = sdist_pkg["filename"]
    if filename.endswith(".tar.gz"):
        filetype_pref = 2
    elif filename.endswith(".zip"):
        filetype_pref = 1
    else:
        filetype_pref = 0

    return yanked_pref, filetype_pref


def _download_vcs_package(requirement, pip_deps_dir):
    """
    Fetch the source for a Python package from VCS (only git is supported).

    :param PipRequirement requirement: VCS requirement from a requirements.txt file
    :param RootedPath pip_deps_dir: The deps/pip directory in a Cachi2 request bundle

    :return: Dict with package name, download path and git info
    """
    git_info = extract_git_info(requirement.url)

    download_to = pip_deps_dir.join_within_root(_get_external_requirement_filepath(requirement))
    download_to.path.parent.mkdir(exist_ok=True, parents=True)

    clone_as_tarball(git_info["url"], git_info["ref"], to_path=download_to.path)

    return {
        "package": requirement.package,
        "path": download_to.path,
        **git_info,
    }


def _download_url_package(requirement, pip_deps_dir, trusted_hosts):
    """
    Download a Python package from a URL.

    :param PipRequirement requirement: VCS requirement from a requirements.txt file
    :param RootedPath pip_deps_dir: The deps/pip directory in a Cachi2 request bundle
    :param set[str] trusted_hosts: If host (or host:port) is trusted, do not verify SSL

    :return: Dict with package name, download path, original URL and URL with hash
    """
    url = urllib.parse.urlparse(requirement.url)

    download_to = pip_deps_dir.join_within_root(_get_external_requirement_filepath(requirement))
    download_to.path.parent.mkdir(exist_ok=True, parents=True)

    if url.hostname in trusted_hosts:
        log.debug("Disabling SSL verification, %s is a --trusted-host", url.hostname)
        insecure = True
    elif url.port is not None and f"{url.hostname}:{url.port}" in trusted_hosts:
        log.debug("Disabling SSL verification, %s:%s is a --trusted-host", url.hostname, url.port)
        insecure = True
    else:
        insecure = False

    download_binary_file(requirement.url, download_to.path, insecure=insecure)

    if "cachito_hash" in requirement.qualifiers:
        url_with_hash = requirement.url
    else:
        hashes = requirement.hashes
        hash_spec = hashes[0] if hashes else requirement.qualifiers["cachito_hash"]
        url_with_hash = _add_cachito_hash_to_url(url, hash_spec)

    return {
        "package": requirement.package,
        "path": download_to.path,
        "original_url": requirement.url,
        "url_with_hash": url_with_hash,
    }


def _add_cachito_hash_to_url(parsed_url, hash_spec):
    """
    Add the #cachito_hash fragment to URL.

    :param urllib.parse.ParseResult parsed_url: A parsed URL with no cachito_hash in fragment
    :param str hash_spec: A hash specifier - "algorithm:digest", e.g. "sha256:123456"
    :return: Original URL + cachito_hash in fragment
    :rtype: str
    """
    new_fragment = f"cachito_hash={hash_spec}"
    if parsed_url.fragment:
        new_fragment = f"{parsed_url.fragment}&{new_fragment}"
    return parsed_url._replace(fragment=new_fragment).geturl()


def _verify_hash(download_path: Path, hashes: list[str]) -> None:
    """
    Check that the downloaded archive verifies against at least one of the provided hashes.

    :param download_path: Path to downloaded file
    :param hashes: All provided hashes for requirement
    :raise PackageRejected: If computed hash does not match any of the provided hashes
    """

    def to_checksum_info(hash_: str) -> ChecksumInfo:
        algorithm, _, digest = hash_.partition(":")
        return ChecksumInfo(algorithm, digest)

    log.info(f"Verifying checksum of {download_path.name}")
    checksums = list(map(to_checksum_info, hashes))
    must_match_any_checksum(download_path, checksums)


def _download_from_requirement_files(
    output_dir: RootedPath, files: list[RootedPath]
) -> list[dict[str, Any]]:
    """
    Download dependencies listed in the requirement files.

    :param output_dir: the root output directory for this request
    :param files: list of absolute paths to pip requirements files
    :return: Info about downloaded packages; see download_dependencies return docs for further
        reference
    :raises PackageRejected: If requirement file does not exist
    """
    requirements = []
    for req_file in files:
        if not req_file.path.exists():
            raise PackageRejected(
                f"The requirements file does not exist: {req_file}",
                solution="Please check that you have specified correct requirements file paths",
            )
        requirements.extend(_download_dependencies(output_dir, PipRequirementsFile(req_file)))
    return requirements


def _default_requirement_file_list(path: RootedPath, devel: bool = False) -> list[RootedPath]:
    """
    Get the paths for the default pip requirement files, if they are present.

    :param path: the full path to the application source code
    :param devel: whether to return the build requirement files
    :return: list of str representing the absolute paths to the Python requirement files
    """
    filename = DEFAULT_BUILD_REQUIREMENTS_FILE if devel else DEFAULT_REQUIREMENTS_FILE
    req = path.join_within_root(filename)
    return [req] if req.path.is_file() else []


def _resolve_pip(
    app_path: RootedPath,
    output_dir: RootedPath,
    requirement_files: Optional[list[Path]] = None,
    build_requirement_files: Optional[list[Path]] = None,
) -> dict[str, Any]:
    """
    Resolve and fetch pip dependencies for the given pip application.

    :param app_path: the full path to the application source code
    :param output_dir: the root output directory for this request
    :param list requirement_files: a list of str representing paths to the Python requirement files
        to be used to compile a list of dependencies to be fetched
    :param list build_requirement_files: a list of str representing paths to the Python build
        requirement files to be used to compile a list of build dependencies to be fetched
    :return: a dictionary that has the following keys:
        ``package`` which is the dict representing the main Package,
        ``dependencies`` which is a list of dicts representing the package Dependencies
        ``requirements`` which is a list of absolute paths for the processed requirement files
    :raises PackageRejected | UnsupportedFeature: if the package is not cachi2-pip compatible
    """
    pkg_name, pkg_version = _get_pip_metadata(app_path)

    # This could be an empty list
    if requirement_files is None:
        resolved_req_files = _default_requirement_file_list(app_path)
    else:
        resolved_req_files = [app_path.join_within_root(r) for r in requirement_files]

    # This could be an empty list
    if build_requirement_files is None:
        resolved_build_req_files = _default_requirement_file_list(app_path, devel=True)
    else:
        resolved_build_req_files = [app_path.join_within_root(r) for r in build_requirement_files]

    requires = _download_from_requirement_files(output_dir, resolved_req_files)
    buildrequires = _download_from_requirement_files(output_dir, resolved_build_req_files)

    # Mark all build dependencies as Cachi2 dev dependencies
    for dependency in buildrequires:
        dependency["dev"] = True

    def _version(dep: dict) -> str:
        if dep["kind"] == "pypi":
            version = dep["version"]
        elif dep["kind"] == "vcs":
            # Version is "git+" followed by the URL used to to fetch from git
            version = f"git+{dep['url']}@{dep['ref']}"
        else:
            # Version is the original URL with #cachito_hash added if it was not present
            version = dep["url_with_hash"]
        return version

    dependencies = [
        {
            "name": dep["package"],
            "version": _version(dep),
            "type": "pip",
            "dev": dep.get("dev", False),
        }
        for dep in (requires + buildrequires)
    ]

    return {
        "package": {"name": pkg_name, "version": pkg_version, "type": "pip"},
        "dependencies": dependencies,
        "requirements": [*resolved_req_files, *resolved_build_req_files],
    }


def _get_external_requirement_filepath(requirement: PipRequirement) -> Path:
    """Get the relative path under deps/pip/ where a URL or VCS requirement should be placed."""
    if requirement.kind == "url":
        package = requirement.package
        hashes = requirement.hashes
        hash_spec = hashes[0] if hashes else requirement.qualifiers["cachito_hash"]
        algorithm, _, digest = hash_spec.partition(":")
        orig_url = urllib.parse.urlparse(requirement.url)
        file_ext = next(ext for ext in SDIST_FILE_EXTENSIONS if orig_url.path.endswith(ext))
        # e.g. external-pyarn/pyarn-external-sha256-deadbeef.tar.gz
        filepath = Path(f"external-{package}", f"{package}-external-{algorithm}-{digest}{file_ext}")
    elif requirement.kind == "vcs":
        git_info = extract_git_info(requirement.url)
        repo = git_info["repo"]
        ref = git_info["ref"]
        # e.g. github.com/containerbuildsystem/pyarn/pyarn-external-gitcommit-badbeef.tar.gz
        filepath = Path(
            git_info["host"],
            git_info["namespace"],  # namespaces can contain '/' but pathlib can handle that
            repo,
            f"{repo}-external-gitcommit-{ref}.tar.gz",
        )
    else:
        raise ValueError(f"{requirement.kind=} is neither 'url' nor 'vcs'")

    return filepath


def _iter_zip_file(file_path: Path):
    with zipfile.ZipFile(file_path, "r") as zf:
        yield from zf.namelist()


def _iter_tar_file(file_path: Path):
    with tarfile.open(file_path, "r") as tar:
        for member in tar:
            yield member.name


def _is_pkg_info_dir(path: str) -> bool:
    """Simply check whether a path represents the PKG_INFO directory.

    Generally, it is in the format for example: pkg-1.0/PKG_INFO

    :param str path: a path.
    :return: True if it is, otherwise False is returned.
    :rtype: bool
    """
    parts = os.path.split(path)
    return len(parts) == 2 and parts[1] == "PKG-INFO"


def _check_metadata_in_sdist(sdist_path: Path):
    """Check if a downloaded sdist package has metadata.

    :param sdist_path: the path of a sdist package file.
    :type sdist_path: pathlib.Path
    :raise PackageRejected: if the sdist is invalid.
    """
    if sdist_path.name.endswith(ZIP_FILE_EXT):
        files_iter = _iter_zip_file(sdist_path)
    elif sdist_path.name.endswith(COMPRESSED_TAR_EXT):
        log.warning("Skip checking metadata from compressed sdist %s", sdist_path.name)
        return
    elif any(map(sdist_path.name.endswith, SDIST_FILE_EXTENSIONS)):
        files_iter = _iter_tar_file(sdist_path)
    else:
        # Invalid usage of the method (Cachi2 doesn't download files without a known extension)
        raise ValueError(
            f"Cannot check metadata from {sdist_path}, "
            f"which does not have a known supported extension.",
        )

    try:
        if not any(map(_is_pkg_info_dir, files_iter)):
            raise PackageRejected(
                f"{sdist_path.name} does not include metadata (there is no PKG-INFO file). "
                "It is not a valid sdist and cannot be downloaded from PyPI.",
                solution=(
                    "Consider editing your requirements file to download the package from git "
                    "or a direct download URL instead."
                ),
                docs=PIP_NO_SDIST_DOC,
            )
    except tarfile.ReadError as e:
        raise PackageRejected(
            f"Cannot open {sdist_path} as a Tar file. Error: {str(e)}", solution=None
        )
    except zipfile.BadZipFile as e:
        raise PackageRejected(
            f"Cannot open {sdist_path} as a Zip file. Error: {str(e)}", solution=None
        )


def _replace_external_requirements(requirements_file_path: RootedPath) -> Optional[ProjectFile]:
    """Generate an updated requirements file.

    Replace the urls of external dependencies with file paths (templated).
    If no updates are needed, return None.
    """
    requirements_file = PipRequirementsFile(requirements_file_path)

    def maybe_replace(requirement: PipRequirement) -> Optional[PipRequirement]:
        if requirement.kind in ("url", "vcs"):
            path = _get_external_requirement_filepath(requirement)
            templated_abspath = Path("${output_dir}", "deps", "pip", path)
            return requirement.copy(url=f"file://{templated_abspath}")
        return None

    replaced = [maybe_replace(requirement) for requirement in requirements_file.requirements]
    if not any(replaced):
        # No need for a custom requirements file
        return None

    requirements = [
        replaced or original for replaced, original in zip(replaced, requirements_file.requirements)
    ]
    replaced_requirements_file = PipRequirementsFile.from_requirements_and_options(
        requirements, requirements_file.options
    )

    return ProjectFile(
        abspath=Path(requirements_file_path).resolve(),
        template=replaced_requirements_file.generate_file_content(),
    )
