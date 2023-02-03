config = None


class Config:
    """
    Singleton that provides default configuration for the Cachi2 process.

    All values currently need to be changed in this file.
    """

    goproxy_url = "https://proxy.golang.org,direct"
    default_environment_variables = {
        "gomod": {"GOSUMDB": {"value": "off", "kind": "literal"}},
    }
    gomod_download_max_tries = 5
    gomod_strict_vendor = True
    subprocess_timeout = 3600


# This function is kept to avoid changing the old code too much
# It should be removed with the refactoring of the config object
def get_config():
    """Get the configuration singleton."""
    global config

    if not config:
        config = Config()

    return config
