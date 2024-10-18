import re
from pathlib import Path
from unittest import mock

import pytest
from pyarn.lockfile import Package as PYarnPackage

from cachi2.core.errors import PackageRejected, UnexpectedFormat
from cachi2.core.package_managers.yarn_classic.resolver import (
    FilePackage,
    GitPackage,
    LinkPackage,
    RegistryPackage,
    UrlPackage,
    YarnClassicPackage,
    _get_packages_from_lockfile,
    _is_from_npm_registry,
    _is_git_url,
    _is_tarball_url,
    _YarnClassicPackageFactory,
    resolve_packages,
)
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath

VALID_GIT_URLS = [
    "git://git.host.com/some/path",
    "ssh://git.host.com/some/path",
    "git+http://git.host.com/some/path",
    "git+https://git.host.com/some/path",
    "git+ssh://git.host.com/some/path",
    "git+file://git.host.com/some/path",
    "git+file://git.host.com/some/path",
    "http://git.host.com/some/path.git",
    "https://git.host.com/some/path.git",
    "http://git.host.com/some/path.git#fffffff",
    "https://github.com/some/path",
    "https://gitlab.com/some/path",
    "https://bitbucket.com/some/path",
    "https://bitbucket.org/some/path",
]
VALID_TARBALL_URLS = [
    "https://foo.com/bar.tar.gz",
    "https://foo.com/bar.tgz",
    "https://foo.com/bar.tar",
    "http://foo.com/bar.tar.gz",
    "http://foo.com/bar.tgz",
    "http://foo.com/bar.tar",
    "https://codeload.github.com/org/foo/tar.gz/fffffff",
]
INVALID_GIT_URLS = [
    "https://github.com/some/path/file",
    "ftp://foo.com/bar.tar",
    "https://foo.com/bar",
    "https://foo.com/bar.txt",
    *VALID_TARBALL_URLS,
]
INVALID_TARBALL_URLS = [
    "ftp://foo.com/bar.tar",
    "git+https://git.host.com/some/path",
    "https://foo.com/bar",
    "https://foo.com/bar.txt",
    *VALID_GIT_URLS,
]


@pytest.mark.parametrize("url", VALID_TARBALL_URLS)
def test__is_tarball_url_can_parse_correct_tarball_urls(url: str) -> None:
    assert _is_tarball_url(url)


@pytest.mark.parametrize("url", INVALID_TARBALL_URLS)
def test__is_tarball_url_rejects_incorrect_tarball_urls(url: str) -> None:
    assert not _is_tarball_url(url)


@pytest.mark.parametrize("url", VALID_GIT_URLS)
def test__is_git_url_can_parse_correct_git_urls(url: str) -> None:
    assert _is_git_url(url)


@pytest.mark.parametrize("url", INVALID_GIT_URLS)
def test__is_git_url_rejects_incorrect_git_urls(url: str) -> None:
    assert not _is_git_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://registry.npmjs.org/chai/-/chai-4.2.0.tgz",
        "https://registry.yarnpkg.com/chai/-/chai-4.2.0.tgz",
    ],
)
def test__is_from_npm_registry_can_parse_correct_registry_urls(url: str) -> None:
    assert _is_from_npm_registry(url)


def test__is_from_npm_registry_can_parse_incorrect_registry_urls() -> None:
    assert not _is_from_npm_registry("https://example.org/fecha.tar.gz")


@pytest.mark.parametrize(
    "pyarn_package, expected_package",
    [
        (
            PYarnPackage(
                name="foo",
                version="1.0.0",
                url="https://registry.yarnpkg.com/foo/-/foo-1.0.0.tgz#fffffff",
                checksum="sha512-fffffff",
            ),
            RegistryPackage(
                name="foo",
                version="1.0.0",
                url="https://registry.yarnpkg.com/foo/-/foo-1.0.0.tgz#fffffff",
                dev=False,
                integrity="sha512-fffffff",
            ),
        ),
        (
            PYarnPackage(
                name="foo",
                version="1.0.0",
                url="./path/foo-1.0.0.tgz#fffffff",
                path="path/foo-1.0.0.tgz",
            ),
            FilePackage(
                name="foo",
                version="1.0.0",
                dev=False,
                relpath=Path("path/foo-1.0.0.tgz"),
            ),
        ),
        (
            PYarnPackage(
                name="foo",
                version="0.0.0",
                path="link",
            ),
            LinkPackage(
                name="foo",
                version="0.0.0",
                dev=False,
                relpath=Path("link"),
            ),
        ),
        (
            PYarnPackage(
                name="foo",
                version="1.0.0",
                url="https://github.com/org/foo.git#fffffff",
            ),
            GitPackage(
                name="foo",
                version="1.0.0",
                dev=False,
                url="https://github.com/org/foo.git#fffffff",
            ),
        ),
        (
            PYarnPackage(
                name="foo",
                version="1.0.0",
                url="https://example.com/foo-1.0.0.tgz",
            ),
            UrlPackage(
                name="foo",
                version="1.0.0",
                dev=False,
                url="https://example.com/foo-1.0.0.tgz",
            ),
        ),
    ],
)
def test_create_package_from_pyarn_package(
    pyarn_package: PYarnPackage, expected_package: YarnClassicPackage, rooted_tmp_path: RootedPath
) -> None:
    package_factory = _YarnClassicPackageFactory(rooted_tmp_path)
    assert package_factory.create_package_from_pyarn_package(pyarn_package) == expected_package


def test_create_package_from_pyarn_package_fail_absolute_path(rooted_tmp_path: RootedPath) -> None:
    pyarn_package = PYarnPackage(
        name="foo",
        version="1.0.0",
        path="/root/some/path",
    )
    error_msg = (
        f"The package {pyarn_package.name}@{pyarn_package.version} has an absolute path "
        f"({pyarn_package.path}), which is not permitted."
    )

    package_factory = _YarnClassicPackageFactory(rooted_tmp_path)
    with pytest.raises(PackageRejected, match=re.escape(error_msg)):
        package_factory.create_package_from_pyarn_package(pyarn_package)


def test_create_package_from_pyarn_package_fail_path_outside_root(
    rooted_tmp_path: RootedPath,
) -> None:
    pyarn_package = PYarnPackage(
        name="foo",
        version="1.0.0",
        path="../path/outside/root",
    )

    package_factory = _YarnClassicPackageFactory(rooted_tmp_path)
    with pytest.raises(PathOutsideRoot):
        package_factory.create_package_from_pyarn_package(pyarn_package)


def test_create_package_from_pyarn_package_fail_unexpected_format(
    rooted_tmp_path: RootedPath,
) -> None:
    pyarn_package = PYarnPackage(
        name="foo",
        version="1.0.0",
        url="ftp://some-tarball.tgz",
    )

    package_factory = _YarnClassicPackageFactory(rooted_tmp_path)
    with pytest.raises(UnexpectedFormat):
        package_factory.create_package_from_pyarn_package(pyarn_package)


@mock.patch(
    "cachi2.core.package_managers.yarn_classic.resolver._YarnClassicPackageFactory.create_package_from_pyarn_package"
)
def test__get_packages_from_lockfile(
    mock_create_package: mock.Mock, rooted_tmp_path: RootedPath
) -> None:

    # Setup lockfile instance
    mock_pyarn_lockfile = mock.Mock()
    mock_yarn_lock = mock.Mock(yarn_lockfile=mock_pyarn_lockfile)
    mock_pyarn_package_1 = mock.Mock()
    mock_pyarn_package_2 = mock.Mock()
    mock_pyarn_lockfile.packages.return_value = [mock_pyarn_package_1, mock_pyarn_package_2]

    # Setup classifier
    mock_package_1 = mock.Mock()
    mock_package_2 = mock.Mock()
    mock_create_package.side_effect = [mock_package_1, mock_package_2]
    create_package_expected_calls = [
        mock.call(mock_pyarn_package_1),
        mock.call(mock_pyarn_package_2),
    ]

    output = _get_packages_from_lockfile(rooted_tmp_path, mock_yarn_lock)

    mock_pyarn_lockfile.packages.assert_called_once()
    mock_create_package.assert_has_calls(create_package_expected_calls)
    assert output == [mock_package_1, mock_package_2]


@mock.patch("cachi2.core.package_managers.yarn_classic.project.YarnLock.from_file")
@mock.patch("cachi2.core.package_managers.yarn_classic.resolver._get_packages_from_lockfile")
def test_resolve_packages(
    mock_get_lockfile_packages: mock.Mock,
    mock_get_yarn_lock: mock.Mock,
    rooted_tmp_path: RootedPath,
) -> None:
    project = mock.Mock(source_dir=rooted_tmp_path)
    yarn_lock_path = rooted_tmp_path.join_within_root("yarn.lock")

    lockfile_packages = [mock.Mock(), mock.Mock()]
    expected_output = [*lockfile_packages]
    mock_get_lockfile_packages.return_value = expected_output

    output = resolve_packages(project)
    mock_get_yarn_lock.assert_called_once_with(yarn_lock_path)
    mock_get_lockfile_packages.assert_called_once_with(
        rooted_tmp_path, mock_get_yarn_lock.return_value
    )
    assert output == expected_output
