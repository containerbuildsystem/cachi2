import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest import mock

import pydantic
import pytest

from cachi2.core.errors import PackageManagerError, PackageRejected, UnexpectedFormat
from cachi2.core.package_managers.bundler.parser import (
    GEMFILE,
    GEMFILE_LOCK,
    GemDependency,
    GitDependency,
    PathDependency,
    parse_lockfile,
)
from cachi2.core.rooted_path import RootedPath
from tests.common_utils import GIT_REF


@pytest.fixture
def empty_bundler_files(rooted_tmp_path: RootedPath) -> tuple[RootedPath, RootedPath]:
    gemfile_path = rooted_tmp_path.join_within_root(GEMFILE)
    gemfile_path.path.touch()

    lockfile_path = rooted_tmp_path.join_within_root(GEMFILE_LOCK)
    lockfile_path.path.touch()

    return gemfile_path, lockfile_path


SAMPLE_PARSER_OUTPUT = {
    "bundler_version": "2.5.10",
    "dependencies": [{"name": "example", "version": "0.1.0"}],
}


@pytest.fixture
def sample_parser_output() -> dict[str, Any]:
    return deepcopy(SAMPLE_PARSER_OUTPUT)


def test_parse_lockfile_without_bundler_files(rooted_tmp_path: RootedPath) -> None:
    with pytest.raises(PackageRejected) as exc_info:
        parse_lockfile(rooted_tmp_path)

    assert (
        "Gemfile and Gemfile.lock must be present in the package directory"
        in exc_info.value.friendly_msg()
    )


@mock.patch("cachi2.core.package_managers.bundler.parser.run_cmd")
def test_parse_lockfile_os_error(
    mock_run_cmd: mock.MagicMock,
    empty_bundler_files: tuple[RootedPath, RootedPath],
    rooted_tmp_path: RootedPath,
) -> None:
    mock_run_cmd.side_effect = subprocess.CalledProcessError(returncode=1, cmd="cmd")

    with pytest.raises(PackageManagerError) as exc_info:
        parse_lockfile(rooted_tmp_path)

    assert f"Failed to parse {empty_bundler_files[1]}" in exc_info.value.friendly_msg()


@mock.patch("cachi2.core.package_managers.bundler.parser.run_cmd")
@pytest.mark.parametrize(
    "error, expected_error_msg",
    [
        ("LOCKFILE_INVALID_URL", "Input should be a valid URL"),
        ("LOCKFILE_INVALID_URL_SCHEME", "URL scheme should be 'https'"),
        ("LOCKFILE_INVALID_REVISION", "String should match pattern '^[a-fA-F0-9]{40}$'"),
        ("LOCKFILE_INVALID_PATH", "PATH dependencies should be within the package root"),
    ],
)
def test_parse_lockfile_invalid_format(
    mock_run_cmd: mock.MagicMock,
    error: str,
    expected_error_msg: str,
    empty_bundler_files: tuple[RootedPath, RootedPath],
    sample_parser_output: dict[str, Any],
    rooted_tmp_path: RootedPath,
) -> None:
    if error == "LOCKFILE_INVALID_URL":
        sample_parser_output["dependencies"][0].update(
            {
                "type": "git",
                "url": "github",
                "ref": GIT_REF,
            }
        )
    elif error == "LOCKFILE_INVALID_URL_SCHEME":
        sample_parser_output["dependencies"][0].update(
            {
                "type": "git",
                "url": "http://github.com/3scale/json-schema.git",
                "ref": GIT_REF,
            }
        )
    elif error == "LOCKFILE_INVALID_REVISION":
        sample_parser_output["dependencies"][0].update(
            {
                "type": "git",
                "url": "https://github.com/3scale/json-schema.git",
                "ref": "abcd",
            }
        )
    elif error == "LOCKFILE_INVALID_PATH":
        sample_parser_output["dependencies"][0].update(
            {
                "type": "path",
                "subpath": "/root/pathgem",
            }
        )

    mock_run_cmd.return_value = json.dumps(sample_parser_output)
    with pytest.raises((pydantic.ValidationError, UnexpectedFormat)) as exc_info:
        parse_lockfile(rooted_tmp_path)

    assert expected_error_msg in str(exc_info.value)


@mock.patch("cachi2.core.package_managers.bundler.parser.run_cmd")
def test_parse_gemlock(
    mock_run_cmd: mock.MagicMock,
    empty_bundler_files: tuple[RootedPath, RootedPath],
    sample_parser_output: dict[str, Any],
    rooted_tmp_path: RootedPath,
    caplog: pytest.LogCaptureFixture,
) -> None:
    base_dep: dict[str, str] = sample_parser_output["dependencies"][0]
    sample_parser_output["dependencies"] = [
        {
            "type": "git",
            "url": "https://github.com/3scale/json-schema.git",
            "ref": GIT_REF,
            **base_dep,
        },
        {
            "type": "path",
            "subpath": "vendor/pathgem",
            **base_dep,
        },
        {
            "type": "rubygems",
            "source": "https://rubygems.org/",
            **base_dep,
        },
    ]

    mock_run_cmd.return_value = json.dumps(sample_parser_output)
    result = parse_lockfile(rooted_tmp_path)

    expected_deps = [
        GitDependency(
            name="example",
            version="0.1.0",
            url="https://github.com/3scale/json-schema.git",
            ref=GIT_REF,
        ),
        PathDependency(
            name="example",
            version="0.1.0",
            root=str(rooted_tmp_path),
            subpath="vendor/pathgem",
        ),
        GemDependency(name="example", version="0.1.0", source="https://rubygems.org/"),
    ]

    assert f"Package {rooted_tmp_path.path.name} is bundled with version 2.5.10" in caplog.messages
    assert result == expected_deps


@mock.patch("cachi2.core.package_managers.bundler.parser.run_cmd")
def test_parse_gemlock_empty(
    mock_run_cmd: mock.MagicMock,
    empty_bundler_files: tuple[RootedPath, RootedPath],
    rooted_tmp_path: RootedPath,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_run_cmd.return_value = '{"bundler_version": "2.5.10", "dependencies": []}'
    result = parse_lockfile(rooted_tmp_path)

    assert f"Package {rooted_tmp_path.path.name} is bundled with version 2.5.10" in caplog.messages
    assert result == []


@pytest.mark.parametrize(
    "source",
    [
        "https://rubygems.org",
        "https://dedicatedprivategemrepo.com",
    ],
)
@mock.patch("cachi2.core.package_managers.bundler.parser.download_binary_file")
def test_dependencies_could_be_downloaded(
    mock_downloader: mock.MagicMock,
    caplog: pytest.LogCaptureFixture,
    source: str,
) -> None:
    base_destination = RootedPath("/tmp/foo")
    dependency = GemDependency(name="foo", version="0.0.2", source=source)
    expected_source_url = f"{source}/gems/foo-0.0.2.gem"
    expected_destination = base_destination.join_within_root(Path("foo-0.0.2.gem"))

    dependency.download_to(base_destination)

    assert f"Downloading gem {dependency.name}" in caplog.messages
    mock_downloader.assert_called_once_with(expected_source_url, expected_destination)


@mock.patch("cachi2.core.package_managers.bundler.parser.Repo.clone_from")
def test_download_git_dependency_works(
    mock_git_clone: mock.Mock,
    rooted_tmp_path: RootedPath,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dep = GitDependency(
        name="example",
        version="0.1.0",
        url="https://github.com/user/repo.git",
        ref=GIT_REF,
    )
    dep_path = rooted_tmp_path.join_within_root(f"{dep.repo_name}-{dep.ref[:12]}").path

    dep.download_to(deps_dir=rooted_tmp_path)
    assert f"Cloning git repository {dep.url}" in caplog.messages

    mock_git_clone.assert_called_once_with(
        url=str(dep.url),
        to_path=dep_path,
        env={"GIT_TERMINAL_PROMPT": "0"},
    )
    assert dep_path.exists()


@mock.patch("cachi2.core.package_managers.bundler.parser.Repo.clone_from")
def test_download_duplicate_git_dependency_is_skipped(
    mock_git_clone: mock.Mock,
    rooted_tmp_path: RootedPath,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dep = GitDependency(
        name="example",
        version="0.1.0",
        url="https://github.com/user/repo.git",
        ref=GIT_REF,
    )
    dep_path = rooted_tmp_path.join_within_root(f"{dep.repo_name}-{dep.ref[:12]}").path

    dep.download_to(deps_dir=rooted_tmp_path)
    dep.download_to(deps_dir=rooted_tmp_path)
    assert f"Skipping existing git repository {dep.url}" in caplog.messages

    mock_git_clone.assert_called_once_with(
        url=str(dep.url),
        to_path=dep_path,
        env={"GIT_TERMINAL_PROMPT": "0"},
    )
    assert dep_path.exists()
