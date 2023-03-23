import json
import shlex
from enum import Enum
from pathlib import Path

from cachi2.core.errors import UnsupportedFeature
from cachi2.core.models.output import BuildConfig


class EnvFormat(str, Enum):
    """Supported environment file formats."""

    json = "json"
    env = "env"
    sh = "env"

    @classmethod
    def based_on_suffix(cls, filepath: Path):
        """Determine the EnvFormat from the filename."""
        suffix = filepath.suffix.removeprefix(".")
        try:
            return cls[suffix]
        except KeyError as e:
            reason = (
                f"file has no suffix: {filepath}" if not suffix else f"unsupported suffix: {suffix}"
            )
            raise UnsupportedFeature(
                f"Cannot determine envfile format, {reason}",
                solution=(
                    f"Please use one of the supported suffixes: {cls._suffixes_repr()}\n"
                    "You can also define the format explicitly instead of letting Cachi2 choose."
                ),
            ) from e

    @classmethod
    def _suffixes_repr(cls) -> str:
        return ", ".join(
            f"{name}[=={member.value}]" if name != member.value else name
            for name, member in cls.__members__.items()
        )


def generate_envfile(build_config: BuildConfig, fmt: EnvFormat, relative_to_path: Path) -> str:
    """Generate an environment file in the specified format.

    Some environment variables need to be resolved relative to a path. Generally, this
    should be the path to the output directory where dependencies were fetched.

    Supported formats:
    - json: [{"name": "GOCACHE", "value": "/path/to/output-dir/deps/gomod"}, ...]
    - env: export GOCACHE=/path/to/output-dir/deps/gomod
           export ...
    """
    env_vars = [
        (env_var.name, env_var.resolve_value(relative_to_path))
        for env_var in build_config.environment_variables
    ]
    if fmt == EnvFormat.json:
        content = json.dumps([{"name": name, "value": value} for name, value in env_vars])
    else:
        content = "\n".join(
            f"export {shlex.quote(name)}={shlex.quote(value)}" for name, value in env_vars
        )
    return content
