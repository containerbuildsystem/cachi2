import re
from pathlib import Path
from typing import Any

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


def test_parse_user_input():
    expect_error = re.compile(
        r"1 validation error for user input\n"
        r"type\n"
        r"  unexpected value; permitted: .* \(given=go-package; permitted=[^;]*\)"
    )
    with pytest.raises(InvalidInput, match=expect_error):
        parse_user_input(GomodPackageInput.parse_obj, {"type": "go-package"})


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
                },
            ),
            (
                {"type": "pip", "requirements_files": ["reqs.txt"], "requirements_build_files": []},
                {
                    "type": "pip",
                    "path": Path("."),
                    "requirements_files": [Path("reqs.txt")],
                    "requirements_build_files": [],
                },
            ),
        ],
    )
    def test_valid_packages(self, input_data: dict[str, Any], expect_data: dict[str, Any]):
        # doesn't pass type check: https://github.com/pydantic/pydantic/issues/1847
        package = pydantic.parse_obj_as(PackageInput, input_data)  # type: ignore
        assert package.dict() == expect_data

    @pytest.mark.parametrize(
        "input_data, expect_error",
        [
            (
                {},
                r"Discriminator 'type' is missing",
            ),
            (
                {"type": "go-package"},
                r"No match for discriminator 'type' and value 'go-package' \(allowed values: .*",
            ),
            (
                {"type": "gomod", "path": "/absolute"},
                r"path\n  path must be relative: /absolute",
            ),
            (
                {"type": "gomod", "path": ".."},
                r"path\n  path contains ..: ..",
            ),
            (
                {"type": "gomod", "path": "weird/../subpath"},
                r"path\n  path contains ..: weird/../subpath",
            ),
            (
                {"type": "pip", "requirements_files": ["weird/../subpath"]},
                r"requirements_files -> 0\n  path contains ..: weird/../subpath",
            ),
            (
                {"type": "pip", "requirements_build_files": ["weird/../subpath"]},
                r"requirements_build_files -> 0\n  path contains ..: weird/../subpath",
            ),
            (
                {"type": "pip", "requirements_files": None},
                r"requirements_files\n  none is not an allowed value",
            ),
            (
                {"type": "pip", "requirements_build_files": None},
                r"requirements_build_files\n  none is not an allowed value",
            ),
        ],
    )
    def test_invalid_packages(self, input_data: dict[str, Any], expect_error: str):
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            # doesn't pass type check: https://github.com/pydantic/pydantic/issues/1847
            pydantic.parse_obj_as(PackageInput, input_data)  # type: ignore


class TestRequest:
    def test_valid_request(self, tmp_path: Path):
        tmp_path.joinpath("subpath").mkdir(exist_ok=True)

        request = Request(
            source_dir=str(tmp_path),
            output_dir=str(tmp_path),
            packages=[
                {"type": "gomod"},
                {"type": "gomod", "path": "subpath"},
                {"type": "npm"},
                {"type": "npm", "path": "subpath"},
                {"type": "pip", "requirements_build_files": []},
                # check de-duplication
                {"type": "gomod"},
                {"type": "gomod", "path": "subpath"},
                {"type": "npm"},
                {"type": "npm", "path": "subpath"},
                {"type": "pip", "requirements_build_files": []},
            ],
        )

        assert request.dict() == {
            "source_dir": RootedPath(tmp_path),
            "output_dir": RootedPath(tmp_path),
            "packages": [
                GomodPackageInput(type="gomod"),
                GomodPackageInput(type="gomod", path="subpath"),
                NpmPackageInput(type="npm"),
                NpmPackageInput(type="npm", path="subpath"),
                PipPackageInput(type="pip", requirements_build_files=[]),
            ],
            "flags": frozenset(),
            "dep_replacements": (),
        }
        assert isinstance(request.source_dir, RootedPath)
        assert isinstance(request.output_dir, RootedPath)

    def test_packages_properties(self, tmp_path: Path):
        packages = [{"type": "gomod"}, {"type": "npm"}, {"type": "pip"}]
        request = Request(source_dir=tmp_path, output_dir=tmp_path, packages=packages)
        assert request.gomod_packages == [GomodPackageInput(type="gomod")]
        assert request.npm_packages == [NpmPackageInput(type="npm")]
        assert request.pip_packages == [PipPackageInput(type="pip")]

    @pytest.mark.parametrize("which_path", ["source_dir", "output_dir"])
    def test_path_not_absolute(self, which_path: str):
        input_data = {
            "source_dir": "/source",
            "output_dir": "/output",
            which_path: "relative/path",
            "packages": [],
        }
        expect_error = f"{which_path}\n  path must be absolute: relative/path"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Request.parse_obj(input_data)

    def test_conflicting_packages(self, tmp_path: Path):
        expect_error = f"packages\n  conflict by {('pip', Path('.'))}"
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
    def test_invalid_package_paths(self, path: str, expect_error: str, tmp_path: Path):
        tmp_path.joinpath("suspicious-symlink").symlink_to("..")
        tmp_path.joinpath("not-a-dir").touch()

        with pytest.raises(pydantic.ValidationError, match=re.escape(expect_error)):
            Request(
                source_dir=tmp_path,
                output_dir=tmp_path,
                packages=[GomodPackageInput(type="gomod", path=path)],
            )

    def test_invalid_flags(self):
        expect_error = r"flags -> 0\n  unexpected value; permitted: .* given=no-such-flag"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Request(
                source_dir="/source",
                output_dir="/output",
                packages=[],
                flags=["no-such-flag"],
            )

    def test_empty_packages(self):
        expect_error = r"packages\n  at least one package must be defined, got an empty list"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Request(
                source_dir="/source",
                output_dir="/output",
                packages=[],
            )
