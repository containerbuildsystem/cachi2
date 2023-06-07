from pathlib import Path

import yaml
from pydantic import BaseModel

from cachi2.core.models.input import parse_user_input

config = None


class Config(BaseModel, extra="forbid"):
    """Singleton that provides default configuration for the Cachi2 process."""

    goproxy_url: str = "https://proxy.golang.org,direct"
    default_environment_variables: dict = {
        "gomod": {"GOSUMDB": {"value": "off", "kind": "literal"}},
    }
    gomod_download_max_tries: int = 5
    gomod_strict_vendor: bool = True
    subprocess_timeout: int = 3600
    requests_timeout: int = 45
    concurrency_limit: int = 5


def get_config() -> Config:
    """Get the configuration singleton."""
    global config

    if not config:
        config = Config()

    return config


def set_config(path: Path) -> None:
    """Set global config variable using input from file."""
    global config

    config = parse_user_input(Config.parse_obj, yaml.safe_load(path.read_text()))
