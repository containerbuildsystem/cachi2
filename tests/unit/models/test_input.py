import re
from pathlib import Path
from typing import Any, cast

import pydantic
import pytest as pytest

from cachi2.core.errors import InvalidInput
from cachi2.core.models.input import (
    GomodPackageInput,
    NpmPackageInput,
    PackageInput,
    PipPackageInput,
    Request,
    parse_user_input,
)
from cachi2.core.rooted_path import RootedPath


def test_parse_user_input() -> None:
    expect_error = re.compile(r"1 validation error for user input\ntype\n  Input should be 'gomod'")
    with pytest.raises(InvalidInput, match=expect_error):
        parse_user_input(GomodPackageInput.model_validate, {"type": "go-package"})


class TestPackageInput:
    @pytest.mark.parametrize(
        "input_data, expect_data",
        [
            (
                {"type": "gomod"},
                {"type": "gomod", "path": Path(".")},
            ),
            (
                {"type": "gomod", "path": "./some/path"},
                {"type": "gomod", "path": Path("some/path")},
            ),
            (
                {"type": "pip"},
                {
                    "type": "pip",
                    "path": Path("."),
                    "requirements_files": None,
                    "requirements_build_files": None,
                    "allow_binary": False,
                },
            ),
            (
                {
                    "type": "pip",
                    "requirements_files": ["reqs.txt"],
                    "requirements_build_files": [],
                    "allow_binary": True,
                },
                {
                    "type": "pip",
                    "path": Path("."),
                    "requirements_files": [Path("reqs.txt")],
                    "requirements_build_files": [],
                    "allow_binary": True,
                },
            ),
        ],
    )
    def test_valid_packages(self, input_data: dict[str, Any], expect_data: dict[str, Any]) -> None:
        adapter = pydantic.TypeAdapter(PackageInput)
        package = cast(PackageInput, adapter.validate_python(input_data))
        assert package.model_dump() == expect_data

    @pytest.mark.parametrize(
        "input_data, expect_error",
        [
            pytest.param(
                {}, r"Unable to extract tag using discriminator 'type'", id="no_type_discrinator"
            ),
            pytest.param(
                {"type": "go-package"},
                r"Input tag 'go-package' found using 'type' does not match any of the expected tags: 'gomod', 'npm', 'pip', 'rpm', 'yarn'",
                id="incorrect_type_tag",
            ),
            pytest.param(
                {"type": "gomod", "path": "/absolute"},
                r"Value error, path must be relative: /absolute",
                id="path_not_relative",
            ),
            pytest.param(
                {"type": "gomod", "path": ".."},
                r"Value error, path contains ..: ..",
                id="gomod_path_references_parent_directory",
            ),
            pytest.param(
                {"type": "gomod", "path": "weird/../subpath"},
                r"Value error, path contains ..: weird/../subpath",
                id="gomod_path_references_parent_directory_2",
            ),
            pytest.param(
                {"type": "pip", "requirements_files": ["weird/../subpath"]},
                r"pip.requirements_files\n  Value error, path contains ..: weird/../subpath",
                id="pip_path_references_parent_directory",
            ),
            pytest.param(
                {"type": "pip", "requirements_build_files": ["weird/../subpath"]},
                r"pip.requirements_build_files\n  Value error, path contains ..: weird/../subpath",
                id="pip_path_references_parent_directory",
            ),
            pytest.param(
                {"type": "pip", "requirements_files": None},
                r"none is not an allowed value",
                id="pip_no_requirements_files",
            ),
            pytest.param(
                {"type": "pip", "requirements_build_files": None},
                r"none is not an allowed value",
                id="pip_no_requirements_build_files",
            ),
        ],
    )
    def test_invalid_packages(self, input_data: dict[str, Any], expect_error: str) -> None:
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            adapter = pydantic.TypeAdapter(PackageInput)
            adapter.validate_python(input_data)


class TestRequest:
    def test_valid_request(self, tmp_path: Path) -> None:
        tmp_path.joinpath("subpath").mkdir(exist_ok=True)

        request = Request(
            source_dir=str(tmp_path),
            output_dir=str(tmp_path),
            packages=[
                GomodPackageInput(type="gomod"),
                GomodPackageInput(type="gomod", path="subpath"),
                NpmPackageInput(type="npm"),
                NpmPackageInput(type="npm", path="subpath"),
                PipPackageInput(type="pip", requirements_build_files=[]),
                # check de-duplication
                GomodPackageInput(type="gomod"),
                GomodPackageInput(type="gomod", path="subpath"),
                NpmPackageInput(type="npm"),
                NpmPackageInput(type="npm", path="subpath"),
                PipPackageInput(type="pip", requirements_build_files=[]),
            ],
        )

        assert request.model_dump() == {
            "source_dir": RootedPath(tmp_path),
            "output_dir": RootedPath(tmp_path),
            "packages": [
                {"type": "gomod", "path": Path(".")},
                {"type": "gomod", "path": Path("subpath")},
                {"type": "npm", "path": Path(".")},
                {"type": "npm", "path": Path("subpath")},
                {
                    "type": "pip",
                    "path": Path("."),
                    "requirements_files": None,
                    "requirements_build_files": [],
                    "allow_binary": False,
                },
            ],
            "flags": frozenset(),
        }
        assert isinstance(request.source_dir, RootedPath)
        assert isinstance(request.output_dir, RootedPath)

    def test_packages_properties(self, tmp_path: Path) -> None:
        packages = [{"type": "gomod"}, {"type": "npm"}, {"type": "pip"}]
        request = Request(source_dir=tmp_path, output_dir=tmp_path, packages=packages)
        assert request.gomod_packages == [GomodPackageInput(type="gomod")]
        assert request.npm_packages == [NpmPackageInput(type="npm")]
        assert request.pip_packages == [PipPackageInput(type="pip")]

    @pytest.mark.parametrize("which_path", ["source_dir", "output_dir"])
    def test_path_not_absolute(self, which_path: str) -> None:
        input_data = {
            "source_dir": "/source",
            "output_dir": "/output",
            which_path: "relative/path",
            "packages": [],
        }
        expect_error = "Value error, path must be absolute: relative/path"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Request.model_validate(input_data)

    def test_conflicting_packages(self, tmp_path: Path) -> None:
        expect_error = f"Value error, conflict by {('pip', Path('.'))}"
        with pytest.raises(pydantic.ValidationError, match=re.escape(expect_error)):
            Request(
                source_dir=tmp_path,
                output_dir=tmp_path,
                packages=[
                    PipPackageInput(type="pip"),
                    PipPackageInput(type="pip", requirements_files=["foo.txt"]),
                ],
            )

    @pytest.mark.parametrize(
        "path, expect_error",
        [
            ("no-such-dir", "package path does not exist (or is not a directory): no-such-dir"),
            ("not-a-dir", "package path does not exist (or is not a directory): not-a-dir"),
            (
                "suspicious-symlink",
                "package path (a symlink?) leads outside source directory: suspicious-symlink",
            ),
        ],
    )
    def test_invalid_package_paths(self, path: str, expect_error: str, tmp_path: Path) -> None:
        tmp_path.joinpath("suspicious-symlink").symlink_to("..")
        tmp_path.joinpath("not-a-dir").touch()

        with pytest.raises(pydantic.ValidationError, match=re.escape(expect_error)):
            Request(
                source_dir=tmp_path,
                output_dir=tmp_path,
                packages=[GomodPackageInput(type="gomod", path=path)],
            )

    def test_invalid_flags(self) -> None:
        expect_error = r"Input should be 'cgo-disable', 'dev-package-managers', 'force-gomod-tidy', 'gomod-vendor' or 'gomod-vendor-check'"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Request(
                source_dir="/source",
                output_dir="/output",
                packages=[],
                flags=["no-such-flag"],
            )

    def test_empty_packages(self) -> None:
        expect_error = r"Value error, at least one package must be defined, got an empty list"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Request(
                source_dir="/source",
                output_dir="/output",
                packages=[],
            )
