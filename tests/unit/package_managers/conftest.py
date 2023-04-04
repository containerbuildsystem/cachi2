import copy
import os
import tempfile
from pathlib import Path

import git
import pytest

from cachi2.core.rooted_path import RootedPath


@pytest.fixture()
def sample_deps():
    return [
        {
            "name": "github.com/Masterminds/semver",
            "type": "gomod",
            "replaces": None,
            "version": "v1.4.2",
        },
        {
            "name": "github.com/kr/pretty",
            "type": "gomod",
            "replaces": None,
            "version": "v0.1.0",
        },
        {
            "name": "github.com/kr/pty",
            "type": "gomod",
            "replaces": None,
            "version": "v1.1.1",
        },
        {
            "name": "github.com/kr/text",
            "type": "gomod",
            "replaces": None,
            "version": "v0.1.0",
        },
        {
            "name": "github.com/op/go-logging",
            "type": "gomod",
            "replaces": None,
            "version": "v0.0.0-20160315200505-970db520ece7",
        },
        {
            "name": "github.com/pkg/errors",
            "type": "gomod",
            "version": "v1.0.0",
            "replaces": None,
        },
        {
            "name": "golang.org/x/crypto",
            "type": "gomod",
            "replaces": None,
            "version": "v0.0.0-20190308221718-c2843e01d9a2",
        },
        {
            "name": "golang.org/x/net",
            "type": "gomod",
            "replaces": None,
            "version": "v0.0.0-20190311183353-d8887717615a",
        },
        {
            "name": "golang.org/x/sys",
            "type": "gomod",
            "replaces": None,
            "version": "v0.0.0-20190215142949-d0b11bdaac8a",
        },
        {
            "name": "golang.org/x/text",
            "type": "gomod",
            "replaces": None,
            "version": "v0.3.0",
        },
        {
            "name": "golang.org/x/tools",
            "type": "gomod",
            "replaces": None,
            "version": "v0.0.0-20190325161752-5a8dccf5b48a",
        },
        {
            "name": "gopkg.in/check.v1",
            "type": "gomod",
            "replaces": None,
            "version": "v1.0.0-20180628173108-788fd7840127",
        },
        {
            "name": "gopkg.in/yaml.v2",
            "type": "gomod",
            "replaces": None,
            "version": "v2.2.2",
        },
        {
            "name": "k8s.io/metrics",
            "type": "gomod",
            "replaces": None,
            "version": "./staging/src/k8s.io/metrics",
        },
    ]


@pytest.fixture()
def sample_deps_replace(sample_deps):
    # Use a copy in case a test uses both this fixture and the sample_deps fixture
    sample_deps_with_replace = copy.deepcopy(sample_deps)
    sample_deps_with_replace[5]["replaces"] = {
        "name": "github.com/pkg/errors",
        "type": "gomod",
        "version": "v0.9.0",
    }
    return sample_deps_with_replace


@pytest.fixture()
def sample_deps_replace_new_name(sample_deps):
    # Use a copy in case a test uses both this fixture and the sample_deps fixture
    sample_deps_with_replace = copy.deepcopy(sample_deps)
    sample_deps_with_replace[5] = {
        "name": "github.com/pkg/new_errors",
        "type": "gomod",
        "replaces": {
            "name": "github.com/pkg/errors",
            "type": "gomod",
            "version": "v0.9.0",
        },
        "version": "v1.0.0",
    }
    return sample_deps_with_replace


@pytest.fixture()
def sample_package():
    return {
        "name": "github.com/release-engineering/retrodep/v2",
        "type": "gomod",
        "version": "v2.1.1",
    }


@pytest.fixture()
def sample_pkg_deps_without_replace():
    return [
        {"name": "fmt", "type": "go-package", "version": None},
        {
            "name": "github.com/Masterminds/semver",
            "type": "go-package",
            "version": "v1.4.2",
        },
        {
            "name": "github.com/op/go-logging",
            "type": "go-package",
            "version": "v0.0.0-20160315200505-970db520ece7",
        },
        {"name": "github.com/pkg/errors", "type": "go-package", "version": "v0.8.1"},
        {
            "name": "github.com/release-engineering/retrodep/v2/retrodep",
            "type": "go-package",
            "version": "v2.1.1",
        },
        {
            "name": "github.com/release-engineering/retrodep/v2/retrodep/glide",
            "type": "go-package",
            "version": "v2.1.1",
        },
        {
            "name": "golang.org/x/tools/go/vcs",
            "type": "go-package",
            "version": "v0.0.0-20190325161752-5a8dccf5b48a",
        },
        {"name": "gopkg.in/yaml.v2", "type": "go-package", "version": "v2.2.2"},
    ]


@pytest.fixture()
def sample_pkg_lvl_pkg():
    return {
        "name": "github.com/release-engineering/retrodep/v2",
        "type": "go-package",
        "version": "v2.1.1",
    }


@pytest.fixture()
def fake_repo():
    """
    Create a fake git repository representing a remote resource to be fetched.

    This fixture yields a tuple containing two data. The first one is the
    absolute path to the repository, and the other one is the namespaced
    repository name. Because of the repository is created as a temporary
    directory, the repository name looks like tmp/test-tasks-xxxxx.
    """
    with tempfile.TemporaryDirectory(prefix="test-tasks-") as repo_dir:
        r = git.Repo.init(repo_dir)
        r.git.config("user.name", "tester")
        r.git.config("user.email", "tester@localhost")
        open(os.path.join(repo_dir, "readme.rst"), "w").close()
        r.index.add(["readme.rst"])
        r.index.commit("first commit", skip_hooks=True)
        open(os.path.join(repo_dir, "main.py"), "w").close()
        r.index.add(["main.py"])
        r.index.commit("add main source", skip_hooks=True)
        yield repo_dir, repo_dir.lstrip("/")


@pytest.fixture()
def env_variables():
    return [
        {"name": "GOCACHE", "value": "deps/gomod", "kind": "path"},
        {"name": "GOMODCACHE", "value": "deps/gomod/pkg/mod", "kind": "path"},
        {"name": "GOPATH", "value": "deps/gomod", "kind": "path"},
        {"name": "GOSUMDB", "value": "off", "kind": "literal"},
    ]


@pytest.fixture
def rooted_tmp_path(tmp_path: Path) -> RootedPath:
    return RootedPath(tmp_path)
