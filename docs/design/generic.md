# Generic artifact fetching

## Introduction

This document will describe high-level implementation overview for supporting generic artifact fetching in cachi2.
Up until now cachi2 has only supported package managers for various ecosystems and languages.
However, there are a couple of use-cases where language non-specific artifacts need to be pre-fetched in order to satisfy
requirements of a hermetic build.

## Context

For context, generic artifact fetching is a use-case of its own (e.g. [OVAL feeds][oval-feeds], AI models), it is also
necessary precursor for implementing support for fetching maven artifacts, which won't be covered in this design, but in
a followup document.

## Design

In this section, I will try to cover individual parts of the design.

### Source repository and cachi2 lockfile

This section will describe the structure of the source repository, that will serve as an input to cachi2. The idea is to
define a cachi2 lockfile that will specify individual artifacts to fetch along with necessary metadata - e.g. checksums.
The format chosen for this lockfile is yaml, and will include [purl] for each
of the fetched artifacts. This decision was made mainly because it allows for followup implementation of maven support,
with accurate SBOM information. Alternatively, for better user experience, the download url and checksums can be specified
separately, always resulting in a `pkg:generic` purl. Here's an example of such a lockfile with both options.

In order to account for possible future breaking changes, the lockfile will contain a `metadata` section with a `version`
field that will indicate the version of the lockfile format.

```yaml
metadata:
  version: 1.0.0
artifacts:
  - purl: pkg:generic/granite-model?download_url=https://huggingface.co/instructlab/granite-7b-lab/resolve/main/model-00001-of-00003.safetensors?download=true
    target: granite-model-1.safetensors
    checksums:
      sha256: 07123e1f482356c415f684407a3b8723e10b2cbbc0b8fcd6282c49d37c9c1abc
  - download_url: https://huggingface.co/instructlab/granite-7b-lab/resolve/main/model-00002-of-00003.safetensors?download=true
    target: granite-model-2.safetensors
    checksums:
        sha256: 90bffe1884b84d5e255f12ff0ecbd70f2edfc877b68d612dc6fb50638b3ac17c
```

#### Specify by purl

This option is provided mostly as a necessary step for the maven support, but can be used for generic artifacts as well.
At this time, the only purl is `pkg:generic` and will result in a `pkg:generic` SBOM component.

##### purl (required)

At this point, the only purl type allowed would be `pkg:generic`. This is because cachi2 has no good way of verifying
additional properties of the fetched artifact that could be included in the resulting SBOM. This should create a strong
incentive to use this feature in the only truly necessary cases, because it will generate low-quality SBOM components,
as compared to using other package managers provided by cachi2. Additionally, the only allowed qualifiers will be
`download_url` and `checksums`.

#### Specify by download_url and checksums

This option is provided for better user experience by specifying the url and checksums separately. This option will always
result in a `pkg:generic` purl.

##### download_url (required)

Specified as a string containing the download url of the artifact.

##### checksums (required)

Specified as a dictionary of checksum algorithms and their values. At least one cachi2-verifiable checksum must be provided.

#### target (optional)

This key is common for both options and providedmainly for the users convenience, so the files end up in expected locations.
Target here means a specific subdirectory inside cachi2's output directory (likely `cachi2-output/deps/generic`).
Special care needs to be taken to ensure there is not a conflict with other downloaded files. If not specified, filename
of the downloaded file will be used.

### SBOM

Letting users specify artifacts as purls begs the question of authenticity of the data provided by the users and how it
should be handled in the resulting SBOM. As described above, the purl is restricted to its basic components, so there is
very little space for the user to provide inaccurate information. Cachi2 should verify that the file downloaded matches
checksums and report the purl as-is, as it contains no extra information. The section below outlines how that information
will be verified at later time.

Additionally, the SBOM component for an artifact fetched this way should contain the [ExternalReferences][external-references]
key with `type` set to `distribution` and `url` set to the download url gathered from the purl.

### Validation of user input

As stated above, cachi2 will perform little to no verification of identity of the downloaded artifacts besides verifying
checksums. However, it will provide enough information in the SBOM so tooling that comes after cachi2 can enforce policies.
An example of this would be the [Enterprise Contract][ec] (EC) project, that enforces policies
based on the provided SBOM.

In the context of this feature, EC would be supplied with the following information by cachi2 in the SBOM:

- checksums were provided and verified
- list of checksum algorithms used
- download urls (in the `ExternalReferences` key)

Enterprise contract policy would then be able to restrict accepting content without checksums, enforce certain algorithms
for checksum verification or only allow certain patterns in the download url (utilizing existing [allow][ec-allow]/
[deny][ec-deny] rule).

### Integration testing

Since this feature is generic, the testing would be done with an example source repository containing the lockfile, with
artifacts pointing to agreed upon urls.

## Outcome

Here's a preliminary work breakdown:

- define models for the new package manager and high-level code structure into multiple modules
- validate & parse generic artifact lockfile
- download artifacts from the lockfile
- add integration tests covering the new package manager
- generate PURLs for all downloaded artifacts
- add documentation

[ec]: https://enterprisecontract.dev/
[ec-allow]: https://enterprisecontract.dev/docs/ec-policies/release_policy.html#sbom_cyclonedx__allowed_package_external_references
[ec-deny]: https://enterprisecontract.dev/docs/ec-policies/release_policy.html#sbom_cyclonedx__disallowed_package_external_references
[external-references]: https://cyclonedx.org/docs/1.4/json/#externalReferences
[oval-feeds]: https://github.com/CISecurity/OVALRepo
[purl]: https://github.com/package-url/purl-spec
