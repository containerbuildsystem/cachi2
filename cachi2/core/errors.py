class Cachi2Error(Exception):
    """Root of the error hierarchy. Don't raise this directly, use more specific error types."""


class PackageRejected(Cachi2Error):
    """Cachi2 refused to process the package the user requested.

    a) The package appears invalid (e.g. missing go.mod for a Go module).
    b) The package does not meet Cachi2's extra requirements (e.g. missing checksums).
    """


class FetchError(Cachi2Error):
    """Cachi2 failed to fetch a dependency or other data needed to process a package."""


class GoModError(Cachi2Error):
    """The 'go' command used while processing a Go module returned an error.

    Maybe the module is invalid, maybe the go tool was unable to fetch a dependency, maybe the
    error is intermittent. We don't really know, but we do at least log the stderr.
    """


class UnsupportedFeature(Cachi2Error):
    """Cachi2 doesn't support a feature the user requested.

    The requested feature might be valid, but Cachi2 doesn't implement it.
    """
