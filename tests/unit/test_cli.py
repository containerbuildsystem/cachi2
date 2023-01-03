import importlib.metadata
import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Callable, Iterator, Optional, Union
from unittest import mock

import pytest
import typer.testing

from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.interface.cli import DEFAULT_OUTPUT, DEFAULT_SOURCE, app

runner = typer.testing.CliRunner()


@pytest.fixture
def tmp_cwd(tmp_path: Path) -> Iterator[Path]:
    """Temporarily change working directory to a pytest tmpdir."""
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(cwd)


@contextmanager
def mock_fetch_deps(
    expect_request: Optional[Request] = None, output: Optional[RequestOutput] = None
) -> Iterator[mock.MagicMock]:
    output = output or RequestOutput.empty()

    with mock.patch("cachi2.interface.cli.resolve_packages") as mock_resolve_packages:
        mock_resolve_packages.return_value = output
        yield mock_resolve_packages

    if expect_request is not None:
        mock_resolve_packages.assert_called_once_with(expect_request)


def invoke_expecting_sucess(app, args: list[str]) -> typer.testing.Result:
    result = runner.invoke(app, args, catch_exceptions=False)
    assert result.exit_code == 0, result.output
    return result


def invoke_expecting_invalid_usage(app, args: list[str]) -> typer.testing.Result:
    result = runner.invoke(app, args)
    assert result.exit_code == 2, (
        f"expected exit_code=2, got exit_code={result.exit_code}\n"
        "command output:\n"
        f"{result.output}"
    )
    return result


def assert_pattern_in_output(pattern: Union[str, re.Pattern], output: str) -> None:
    if isinstance(pattern, re.Pattern):
        match = bool(pattern.search(output))
    else:
        match = pattern in output

    assert match, f"pattern {pattern!r} not found!\noutput:\n{output}"


class TestTopLevelOpts:
    def test_version_option(self):
        expect_version = importlib.metadata.version("cachi2")
        result = invoke_expecting_sucess(app, ["--version"])
        lines = result.output.splitlines()
        assert lines[0] == f"cachi2 {expect_version}"
        assert lines[1].startswith("Supported package managers: gomod")


class TestLogLevelOpt:
    @pytest.mark.parametrize(
        "loglevel_args, expected_level",
        [
            ([], "INFO"),
            (["--log-level=debug"], "DEBUG"),
            (["--log-level", "WARNING"], "WARNING"),
        ],
    )
    def test_loglevel_option(
        self,
        loglevel_args: list[str],
        expected_level: str,
        tmp_cwd,
    ):
        args = ["fetch-deps", "gomod", *loglevel_args]

        with mock_fetch_deps():
            invoke_expecting_sucess(app, args)

        loglevel = logging.getLogger("cachi2").getEffectiveLevel()
        loglevel_name = logging.getLevelName(loglevel)
        assert loglevel_name == expected_level

    def test_unknown_loglevel(self, tmp_cwd):
        args = ["fetch-deps", "gomod", "--log-level=unknown"]
        result = invoke_expecting_invalid_usage(app, args)
        assert "Error: Invalid value for '--log-level': 'unknown' is not one of" in result.output


class TestFetchDeps:
    @pytest.mark.parametrize(
        "path_args, expect_source, expect_output",
        [
            (
                [],
                f"{{cwd}}/{DEFAULT_SOURCE}",
                f"{{cwd}}/{DEFAULT_OUTPUT}",
            ),
            (
                ["--source=./source/dir", "--output=./output/dir"],
                "{cwd}/source/dir",
                "{cwd}/output/dir",
            ),
            (
                ["--source={cwd}/source/dir", "--output={cwd}/output/dir"],
                "{cwd}/source/dir",
                "{cwd}/output/dir",
            ),
        ],
    )
    def test_specify_paths(
        self, path_args: list[str], expect_source: str, expect_output: str, tmp_cwd: Path
    ):
        tmp_cwd.joinpath("source", "dir").mkdir(parents=True, exist_ok=True)

        source_abspath = expect_source.format(cwd=tmp_cwd)
        output_abspath = expect_output.format(cwd=tmp_cwd)
        expect_request = Request(
            source_dir=source_abspath,
            output_dir=output_abspath,
            packages=[{"type": "gomod"}],
        )

        path_args = [arg.format(cwd=tmp_cwd) for arg in path_args]

        with mock_fetch_deps(expect_request):
            invoke_expecting_sucess(app, ["fetch-deps", *path_args, "gomod"])

    @pytest.mark.parametrize(
        "path_args, expect_error",
        [
            (["--source=no-such-dir"], "'--source': Directory 'no-such-dir' does not exist"),
            (["--source=/no-such-dir"], "'--source': Directory '/no-such-dir' does not exist"),
            (["--source=not-a-directory"], "'--source': Directory 'not-a-directory' is a file"),
            (["--output=not-a-directory"], "'--output': Directory 'not-a-directory' is a file"),
        ],
    )
    def test_invalid_paths(self, path_args: list[str], expect_error: str, tmp_cwd: Path):
        tmp_cwd.joinpath("not-a-directory").touch()

        result = invoke_expecting_invalid_usage(app, ["fetch-deps", *path_args])
        assert expect_error in result.output

    def test_no_packages(self):
        result = invoke_expecting_invalid_usage(app, ["fetch-deps"])
        assert "Error: Missing argument 'PKG'" in result.output

    @pytest.mark.parametrize(
        "package_arg, expect_packages",
        [
            # specify a single basic package
            ("gomod", [{"type": "gomod"}]),
            ('{"type": "gomod"}', [{"type": "gomod"}]),
            ('[{"type": "gomod"}]', [{"type": "gomod"}]),
            # specify multiple packages
            (
                '[{"type": "gomod"}, {"type": "gomod", "path": "pkg_a"}]',
                [{"type": "gomod"}, {"type": "gomod", "path": "pkg_a"}],
            ),
            (
                dedent(
                    """
                    [
                        {"type": "gomod"},
                        {"type": "gomod", "path": "pkg_a"},
                        {"type": "gomod", "path": "pkg_b"}
                    ]
                    """
                ),
                [
                    {"type": "gomod"},
                    {"type": "gomod", "path": "pkg_a"},
                    {"type": "gomod", "path": "pkg_b"},
                ],
            ),
            # specify using a 'packages' key
            (
                '{"packages": [{"type": "gomod"}]}',
                [{"type": "gomod"}],
            ),
            (
                dedent(
                    """
                    {"packages": [
                        {"type": "gomod", "path": "pkg_a"},
                        {"type": "gomod", "path": "pkg_b"}
                    ]}
                    """
                ),
                [{"type": "gomod", "path": "pkg_a"}, {"type": "gomod", "path": "pkg_b"}],
            ),
        ],
    )
    def test_specify_packages(self, package_arg: str, expect_packages: list[dict], tmp_cwd: Path):
        tmp_cwd.joinpath("pkg_a").mkdir(exist_ok=True)
        tmp_cwd.joinpath("pkg_b").mkdir(exist_ok=True)

        expect_request = Request(
            source_dir=tmp_cwd / DEFAULT_SOURCE,
            output_dir=tmp_cwd / DEFAULT_OUTPUT,
            packages=expect_packages,
        )
        with mock_fetch_deps(expect_request):
            invoke_expecting_sucess(app, ["fetch-deps", package_arg])

    @pytest.mark.parametrize(
        "package_arg, expect_error_lines",
        [
            # Invalid JSON
            (
                "{notjson}",
                ["'PKG': Looks like JSON but is not valid JSON: '{notjson}'"],
            ),
            (
                "[notjson]",
                ["'PKG': Looks like JSON but is not valid JSON: '[notjson]'"],
            ),
            # Invalid package type
            (
                "idk",
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "No match for discriminator 'type' and value 'idk' (allowed values:",
                ],
            ),
            (
                '[{"type": "idk"}]',
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "No match for discriminator 'type' and value 'idk' (allowed values:",
                ],
            ),
            (
                '{"packages": [{"type": "idk"}]}',
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "No match for discriminator 'type' and value 'idk' (allowed values:",
                ],
            ),
            # Missing package type
            (
                "{}",
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "Discriminator 'type' is missing",
                ],
            ),
            (
                '[{"type": "gomod"}, {}]',
                [
                    "1 validation error for user input",
                    "packages -> 1",
                    "Discriminator 'type' is missing",
                ],
            ),
            (
                '{"packages": [{}]}',
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "Discriminator 'type' is missing",
                ],
            ),
            # Invalid path
            (
                '{"type": "gomod", "path": "/absolute"}',
                [
                    "1 validation error for user input",
                    "packages -> 0 -> GomodPackageInput -> path",
                    "path must be relative: /absolute",
                ],
            ),
            (
                '{"type": "gomod", "path": "weird/../subpath"}',
                [
                    "1 validation error for user input",
                    "packages -> 0 -> GomodPackageInput -> path",
                    "path contains ..: weird/../subpath",
                ],
            ),
            (
                '{"type": "gomod", "path": "suspicious-symlink"}',
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "package path (a symlink?) leads outside source directory: suspicious-symlink",
                ],
            ),
            (
                '{"type": "gomod", "path": "no-such-dir"}',
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "package path does not exist (or is not a directory): no-such-dir",
                ],
            ),
            # Extra fields
            (
                '{"type": "gomod", "what": "dunno"}',
                [
                    "1 validation error for user input",
                    "packages -> 0 -> GomodPackageInput -> what",
                    "extra fields not permitted",
                ],
            ),
            # Invalid format using 'packages' key
            (
                '{"packages": "gomod"}',
                [
                    "1 validation error for user input",
                    "packages",
                    "value is not a valid list",
                ],
            ),
            (
                '{"packages": {"type":"gomod"}}',
                [
                    "1 validation error for user input",
                    "packages",
                    "value is not a valid list",
                ],
            ),
            (
                '{"packages": ["gomod"]}',
                [
                    "1 validation error for user input",
                    "packages -> 0",
                    "Discriminator 'type' is missing",
                ],
            ),
            (
                '{"packages": [{"type": "gomod"}], "what": "dunno"}',
                [
                    "1 validation error for user input",
                    "what",
                    "extra fields not permitted",
                ],
            ),
        ],
    )
    def test_invalid_packages(self, package_arg: str, expect_error_lines: list[str], tmp_cwd: Path):
        tmp_cwd.joinpath("suspicious-symlink").symlink_to("..")

        result = invoke_expecting_invalid_usage(app, ["fetch-deps", package_arg])

        for pattern in expect_error_lines:
            assert_pattern_in_output(pattern, result.output)

    @pytest.mark.parametrize(
        "cli_args, expect_flags",
        [
            (["gomod"], {}),
            (["gomod", "--gomod-vendor"], {"gomod-vendor"}),
            (['{"packages": [{"type":"gomod"}], "flags": ["gomod-vendor"]}'], {"gomod-vendor"}),
            (
                ['{"packages": [{"type":"gomod"}], "flags": ["gomod-vendor"]}', "--gomod-vendor"],
                {"gomod-vendor"},
            ),
            (
                [
                    "gomod",
                    "--gomod-vendor",
                    "--gomod-vendor-check",
                    "--cgo-disable",
                    "--force-gomod-tidy",
                ],
                {"gomod-vendor", "gomod-vendor-check", "cgo-disable", "force-gomod-tidy"},
            ),
            (
                [
                    '{"packages": [{"type":"gomod"}], "flags": ["gomod-vendor", "cgo-disable"]}',
                    "--gomod-vendor-check",
                    "--force-gomod-tidy",
                ],
                {"gomod-vendor", "gomod-vendor-check", "cgo-disable", "force-gomod-tidy"},
            ),
        ],
    )
    def test_specify_flags(self, cli_args: list[str], expect_flags: set[str], tmp_cwd):
        expect_request = Request(
            source_dir=tmp_cwd / DEFAULT_SOURCE,
            output_dir=tmp_cwd / DEFAULT_OUTPUT,
            packages=[{"type": "gomod"}],
            flags=frozenset(expect_flags),
        )
        with mock_fetch_deps(expect_request):
            invoke_expecting_sucess(app, ["fetch-deps", *cli_args])

    @pytest.mark.parametrize(
        "cli_args, expect_error",
        [
            (["gomod", "--no-such-flag"], "Error: No such option: --no-such-flag"),
            (
                ['{"packages": [{"type": "gomod"}], "flags": "not-a-list"}'],
                re.compile(
                    r"1 validation error for user input\n"
                    r"flags\n"
                    r"  value is not a valid list",
                ),
            ),
            (
                ['{"packages": [{"type": "gomod"}], "flags": {"dict": "no-such-flag"}}'],
                re.compile(
                    r"1 validation error for user input\n"
                    r"flags\n"
                    r"  value is not a valid list",
                ),
            ),
            (
                ['{"packages": [{"type": "gomod"}], "flags": ["no-such-flag"]}'],
                re.compile(
                    r"1 validation error for user input\n"
                    r"flags -> 0\n"
                    r"  unexpected value; permitted: .*\(given=no-such-flag",
                ),
            ),
        ],
    )
    def test_invalid_flags(self, cli_args: list[str], expect_error: str):
        result = invoke_expecting_invalid_usage(app, ["fetch-deps", *cli_args])
        assert_pattern_in_output(expect_error, result.output)

    @pytest.mark.parametrize(
        "request_output",
        [
            RequestOutput.empty(),
            RequestOutput(
                packages=[
                    {
                        "name": "cool-package",
                        "version": "v1.0.0",
                        "type": "gomod",
                        "path": ".",
                        "dependencies": [],
                    },
                ],
                environment_variables=[
                    {"name": "GOMOD_SOMETHING", "value": "yes", "kind": "literal"},
                ],
                project_files=[],
            ),
        ],
    )
    def test_write_json_output(self, request_output: RequestOutput, tmp_cwd: Path):
        with mock_fetch_deps(output=request_output):
            invoke_expecting_sucess(app, ["fetch-deps", "gomod"])

        output_json = tmp_cwd / DEFAULT_OUTPUT / "output.json"
        written_output = RequestOutput.parse_file(output_json)

        assert written_output == request_output


def env_file_as_json(for_output_dir: Path) -> str:
    gocache = f'{{"name": "GOCACHE", "value": "{for_output_dir}/deps/gomod"}}'
    gosumdb = '{"name": "GOSUMDB", "value": "off"}'
    return f"[{gocache}, {gosumdb}]\n"


def env_file_as_env(for_output_dir: Path) -> str:
    return dedent(
        f"""
        export GOCACHE={for_output_dir}/deps/gomod
        export GOSUMDB=off
        """
    ).lstrip()


class TestGenerateEnv:
    ENV_VARS = [
        {"name": "GOCACHE", "value": "deps/gomod", "kind": "path"},
        {"name": "GOSUMDB", "value": "off", "kind": "literal"},
    ]

    @pytest.fixture
    def tmp_cwd_as_output_dir(self, tmp_cwd: Path) -> Path:
        """Change working directory to a tmpdir and write output.json into it."""
        request_output = RequestOutput(
            packages=[], environment_variables=self.ENV_VARS, project_files=[]
        )
        tmp_cwd.joinpath("output.json").write_text(request_output.json())
        return tmp_cwd

    @pytest.mark.parametrize(
        "extra_args, make_output, output_file",
        [
            ([], env_file_as_json, None),
            (["--format=env"], env_file_as_env, None),
            (["--output=cachi2-env.json"], env_file_as_json, "cachi2-env.json"),
            (["--output=cachi2.env"], env_file_as_env, "cachi2.env"),
            (["--output=cachi2-env.sh"], env_file_as_env, "cachi2-env.sh"),
            (["--format=json", "--output=cachi2.env"], env_file_as_json, "cachi2.env"),
        ],
    )
    def test_generate_env(
        self,
        extra_args: list[str],
        make_output: Callable[[Path], str],
        output_file: Optional[str],
        tmp_cwd_as_output_dir: Path,
    ):
        result = invoke_expecting_sucess(
            app, ["generate-env", str(tmp_cwd_as_output_dir), *extra_args]
        )

        expect_output = make_output(tmp_cwd_as_output_dir)
        if output_file is None:
            assert result.output == expect_output
        else:
            assert result.output == ""
            assert Path(output_file).read_text() == expect_output

    @pytest.mark.parametrize("fmt", ["env", "json"])
    @pytest.mark.parametrize(
        "for_output_dir, expect_output_dir",
        [
            ("relative/dir", "{cwd}/relative/dir"),
            ("/absolute/dir", "/absolute/dir"),
        ],
    )
    def test_generate_for_different_output_dir(
        self, fmt: str, for_output_dir: str, expect_output_dir: str, tmp_cwd_as_output_dir: Path
    ):
        result = invoke_expecting_sucess(
            app,
            [
                "generate-env",
                str(tmp_cwd_as_output_dir),
                "--for-output-dir",
                for_output_dir,
                "--format",
                fmt,
            ],
        )

        resolved_output_dir = Path(expect_output_dir.format(cwd=tmp_cwd_as_output_dir))
        if fmt == "env":
            expect_output = env_file_as_env(resolved_output_dir)
        else:
            expect_output = env_file_as_json(resolved_output_dir)

        assert result.stdout == expect_output

    def test_invalid_format(self):
        # Note: .sh is a recognized suffix, but the --format option accepts only 'json' and 'env'
        result = invoke_expecting_invalid_usage(app, ["generate-env", ".", "-f", "sh"])
        assert "Invalid value for '-f' / '--format': 'sh' is not one of" in result.output

    def test_unsupported_suffix(self, caplog: pytest.LogCaptureFixture):
        result = invoke_expecting_invalid_usage(app, ["generate-env", ".", "-o", "env.yaml"])

        msg = "Cannot determine envfile format, unsupported suffix: yaml"
        assert msg in result.output
        assert "  Please use one of the supported suffixes: " in result.output

        # Error message should also be logged, but the extra info should not
        assert msg in caplog.text
        assert "  Please use one of the supported suffixes: " not in caplog.text


class TestInjectFiles:
    @pytest.fixture
    def tmp_cwd_as_output_dir(self, tmp_cwd: Path) -> Path:
        """Change working directory to a tmpdir and write output.json into it.

        Also create one of the project files in the output to test overwriting vs. creating.
        """
        tmp_cwd.joinpath("requirements.txt").touch()
        project_files = [
            {
                "abspath": tmp_cwd / "requirements.txt",
                "template": "foo @ file://${output_dir}/deps/pip/foo.tar.gz",
            },
            {
                "abspath": tmp_cwd / "some-dir" / "requirements-extra.txt",
                "template": "bar @ file://${output_dir}/deps/pip/bar.tar.gz",
            },
        ]
        request_output = RequestOutput(
            packages=[], environment_variables=[], project_files=project_files
        )
        tmp_cwd.joinpath("output.json").write_text(request_output.json())
        return tmp_cwd

    @pytest.mark.parametrize("for_output_dir", [None, "/cachi2/output"])
    def test_inject_files(
        self,
        for_output_dir: Optional[str],
        tmp_cwd_as_output_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ):
        tmp_path = tmp_cwd_as_output_dir

        if not for_output_dir:
            invoke_expecting_sucess(app, ["inject-files", str(tmp_path)])
        else:
            invoke_expecting_sucess(
                app, ["inject-files", str(tmp_path), "--for-output-dir", for_output_dir]
            )

        expect_output_dir = for_output_dir or tmp_path

        assert (
            tmp_path.joinpath("requirements.txt").read_text()
            == f"foo @ file://{expect_output_dir}/deps/pip/foo.tar.gz"
        )
        assert (
            tmp_path.joinpath("some-dir/requirements-extra.txt").read_text()
            == f"bar @ file://{expect_output_dir}/deps/pip/bar.tar.gz"
        )

        assert f"Overwriting {tmp_path / 'requirements.txt'}" in caplog.text
        assert f"Creating {tmp_path / 'some-dir' / 'requirements-extra.txt'}" in caplog.text
