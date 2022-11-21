from typing import Dict

config = None


class Config:
    """
    Singleton that provides default configuration for the Cachi2 process.

    All values currently need to be changed in this file.
    """

    cachito_athens_url = None
    cachito_default_environment_variables = {
        "gomod": {"GOSUMDB": {"value": "off", "kind": "literal"}},
    }
    cachito_gomod_download_max_tries = 5
    cachito_gomod_file_deps_allowlist: Dict[str, Dict[str, str]] = {}
    cachito_gomod_strict_vendor = False
    cachito_subprocess_timeout = 3600

    # TODO: purely temporary
    cachito_sources_dir = "/tmp"


# This function is kept to avoid changing the old code too much
# It should be removed with the refactoring of the config object
def get_worker_config():
    """Get the configuration singleton."""
    global config

    if not config:
        config = Config()

    return config
