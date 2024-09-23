from unittest import mock

import pytest
from git.repo import Repo

from cachi2.core.errors import PackageRejected
from cachi2.core.package_managers.bundler.main import (
    _get_main_package_name_and_version,
    _resolve_bundler_package,
)
from cachi2.core.package_managers.bundler.parser import (
    GemDependency,
    GitDependency,
    ParseResult,
    PathDependency,
)
from cachi2.core.rooted_path import RootedPath
from tests.common_utils import GIT_REF


@mock.patch("cachi2.core.package_managers.bundler.main._get_main_package_name_and_version")
@mock.patch("cachi2.core.package_managers.bundler.main.parse_lockfile")
@mock.patch("cachi2.core.package_managers.bundler.parser.GemDependency.download_to")
@mock.patch("cachi2.core.package_managers.bundler.parser.GitDependency.download_to")
@mock.patch("cachi2.core.package_managers.bundler.parser.PathDependency.download_to")
def test_resolve_bundler_package(
    mock_path_dep_download_to: mock.Mock,
    mock_git_dep_download_to: mock.Mock,
    mock_gem_dep_download_to: mock.Mock,
    mock_parse_lockfile: mock.Mock,
    mock_get_main_package_name_and_version: mock.Mock,
    rooted_tmp_path_repo: RootedPath,
) -> None:
    Repo(rooted_tmp_path_repo).create_remote("origin", "git@github.com:user/repo.git")

    package_dir = rooted_tmp_path_repo
    output_dir = rooted_tmp_path_repo.join_within_root("cachi2-output")
    deps_dir = output_dir.join_within_root("deps", "bundler")

    gem_dep = GemDependency(
        name="my-gem-dep",
        version="0.1.0",
        source="https://rubygems.org",
    )
    git_dep = GitDependency(
        name="my-git-dep",
        version="0.1.0",
        url="https://github.com/rubygems/example.git",
        ref=GIT_REF,
    )
    path_dep = PathDependency(
        name="my-path-dep",
        version="0.1.0",
        root=package_dir,
        subpath="vendor",
    )

    deps = [gem_dep, git_dep, path_dep]

    mock_parse_lockfile.return_value = deps
    mock_get_main_package_name_and_version.return_value = ("name", None)

    components = _resolve_bundler_package(package_dir=package_dir, output_dir=output_dir)

    mock_parse_lockfile.assert_called_once_with(package_dir)
    mock_get_main_package_name_and_version.assert_called_once_with(package_dir, deps)
    mock_gem_dep_download_to.assert_called_with(deps_dir)
    mock_git_dep_download_to.assert_called_with(deps_dir)
    mock_path_dep_download_to.assert_called_with(deps_dir)

    assert len(components) == len(deps) + 1  # + 1 for the "main" package
    assert deps_dir.path.exists()


def test_get_main_package_name_and_version(rooted_tmp_path: RootedPath) -> None:
    dependencies: ParseResult = [
        GemDependency(
            name="my_gem_dep",
            version="0.1.0",
            source="https://rubygems.org",
        ),
        PathDependency(
            name="my_path_dep",
            version="0.2.0",
            root=str(rooted_tmp_path),
            subpath=".",
        ),
    ]

    name, version = _get_main_package_name_and_version(
        package_dir=rooted_tmp_path, dependencies=dependencies
    )
    assert name == "my_path_dep"
    assert version == "0.2.0"


def test_get_main_package_name_and_version_from_repo(rooted_tmp_path_repo: RootedPath) -> None:
    repo = Repo(rooted_tmp_path_repo)
    repo.create_remote("origin", "git@github.com:user/example.git")

    name, version = _get_main_package_name_and_version(
        package_dir=rooted_tmp_path_repo, dependencies=[]
    )

    assert name == "example"
    assert version is None


def test_get_main_package_name_and_version_from_repo_without_origin(
    rooted_tmp_path_repo: RootedPath,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(PackageRejected) as exc_info:
        _get_main_package_name_and_version(package_dir=rooted_tmp_path_repo, dependencies=[])

    assert "Failed to extract package name from origin remote" in exc_info.value.friendly_msg()
