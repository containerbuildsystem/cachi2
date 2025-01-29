import tomlkit

from cachi2.core.package_managers.cargo.main import _use_vendored_sources
from cachi2.core.rooted_path import RootedPath


def test_use_vendored_sources_creates_config_file(rooted_tmp_path: RootedPath) -> None:
    config_path = rooted_tmp_path.join_within_root(".cargo/config.toml")
    config_path.path.parent.mkdir(parents=True)

    project_file = _use_vendored_sources(rooted_tmp_path)

    assert config_path.path.exists()
    assert project_file.abspath == config_path.path

    config_content = tomlkit.parse(config_path.path.read_text())

    assert config_content.get("source") == {
        "crates-io": {"replace-with": "vendored-sources"},
        "vendored-sources": {"directory": "${output_dir}/deps/cargo"},
    }


def test_use_vendored_sources_preserves_existing_config(rooted_tmp_path: RootedPath) -> None:
    config_path = rooted_tmp_path.join_within_root(".cargo/config.toml")
    config_path.path.parent.mkdir(parents=True)

    some_toml = """
    [build]
    rustflags = ["-C", "target-cpu=native"]
    """
    config_path.path.write_text(some_toml)

    _use_vendored_sources(rooted_tmp_path)

    config_content = tomlkit.parse(config_path.path.read_text())

    assert config_content.get("build") == {"rustflags": ["-C", "target-cpu=native"]}
    assert config_content.get("source") == {
        "crates-io": {"replace-with": "vendored-sources"},
        "vendored-sources": {"directory": "${output_dir}/deps/cargo"},
    }
