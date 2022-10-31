# Metadata

⚠ UNDER CONSTRUCTION

At the moment, Cachi2 does not provide any user-facing metadata. The only metadata available
is the output.json file in the output directory of a `fetch-deps` command - which is neither
standardized nor considered stable. For what it's worth, the format is similar to Cachito's
original [Request JSON][cachito-request-json] and most of the same ideas apply.

Like the original Cachito, Cachi2 will provide a [Content Manifest][cachito-content-manifest]
in the future.

Cachi2 may gain support for standardized SBOMs, such as [CycloneDX](https://cyclonedx.org/),
in the (further) future.

[cachito-request-json]: https://github.com/containerbuildsystem/cachito/blob/master/docs/metadata.md#request-json
[cachito-content-manifest]: https://github.com/containerbuildsystem/cachito/blob/master/docs/metadata.md#content-manifest
