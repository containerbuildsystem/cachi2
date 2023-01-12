from pydantic import BaseModel
from typing import Dict, List, Optional

import yaml

config = None


class Config(BaseModel):
    cachito_goproxy_url: Optional[str] = "https://proxy.golang.org,direct"
    cachito_default_environment_variables: Optional[dict] = {}
    cachito_gomod_download_max_tries: Optional[int] = 5
    cachito_gomod_file_deps_allowlist: Optional[Dict[str, List[str]]] = {}     # TODO or dict
    cachito_gomod_strict_vendor: Optional[bool] = True
    cachito_subprocess_timeout: Optional[int] = 3600


def get_worker_config():
    """Get the configuration singleton."""
    global config

    if not config:
        try:
            with open("config.yaml", "r", ) as f:   # TODO default name
                config = Config(**yaml.safe_load(f))
        except FileNotFoundError:
            config = Config()

    return config
