import re
from pathlib import Path
from typing import Any

import pydantic
import pytest as pytest

from cachi2.core.errors import InvalidInput
from cachi2.core.models.input import PackageInput, Request, parse_user_input


def test_parse_user_input():
    expect_error = re.compile(
        r"1 validation error for user input\n"
        r"type\n"
        r"  unexpected value; permitted: .* \(given=go-package; permitted=[^;]*\)"
    )
    with pytest.raises(InvalidInput, match=expect_error):
        parse_user_input(PackageInput.parse_obj, {"type": "go-package"})


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
        ],
    )
    def test_valid_packages(self, input_data: dict[str, Any], expect_data: dict[str, Any]):
        package = PackageInput.parse_obj(input_data)
        assert package.dict() == expect_data

    @pytest.mark.parametrize(
        "input_data, expect_error",
        [
            (
                {},
                r"type\n  field required",
            ),
            (
                {"type": "go-package"},
                r"type\n  unexpected value; permitted: .* given=go-package;",
            ),
            (
                {"type": "gomod", "path": "/absolute"},
                r"path\n  package path must be relative: /absolute",
            ),
            (
                {"type": "gomod", "path": ".."},
                r"path\n  package path contains ..: ..",
            ),
            (
                {"type": "gomod", "path": "weird/../subpath"},
                r"path\n  package path contains ..: weird/../subpath",
            ),
        ],
    )
    def test_invalid_packages(self, input_data: dict[str, Any], expect_error: str):
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            PackageInput.parse_obj(input_data)


class TestRequest:
    def test_valid_request(self, tmp_path: Path):
        tmp_path.joinpath("subpath").mkdir(exist_ok=True)

        request = Request(
            source_dir=str(tmp_path),
            output_dir=str(tmp_path),
            packages=[
                {"type": "gomod"},
                {"type": "gomod", "path": "subpath"},
                # check de-duplication
                {"type": "gomod"},
                {"type": "gomod", "path": "subpath"},
            ],
        )

        assert request.dict() == {
            "source_dir": tmp_path,
            "output_dir": tmp_path,
            "packages": [
                PackageInput(type="gomod"),
                PackageInput(type="gomod", path="subpath"),
            ],
            "flags": frozenset(),
            "dep_replacements": (),
        }

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
        class MadeUpPackage(PackageInput):
            type: str
            some_attr: str = "hello"

        expect_error = f"packages\n  conflict by {('made-up-type', Path('.'))}"
        with pytest.raises(pydantic.ValidationError, match=re.escape(expect_error)):
            Request(
                source_dir=tmp_path,
                output_dir=tmp_path,
                packages=[
                    MadeUpPackage(type="made-up-type"),
                    MadeUpPackage(type="made-up-type", some_attr="goodbye"),
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
                packages=[PackageInput(type="gomod", path=path)],
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
