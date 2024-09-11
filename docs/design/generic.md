# Generic artifact fetching

## Introduction

This document will describe high-level implementation overview for supporting generic artifact fetching in cachi2.
Up until now cachi2 has only supported package managers for various ecosystems and languages.
However, there are a couple of use-cases where language non-specific artifacts need to be pre-fetched in order to satisfy
requirements of a hermetic build.

## Context

For context, generic artifact fetching is a use-case of its own (e.g. [OVAL feeds](https://github.com/CISecurity/OVALRepo),
AI models), it is also necessary precursor for implementing support for fetching maven artifacts, which won't be covered
in this design, but in a followup document.

## Design

In this section, I will try to cover individual parts of the design.

### Source repository

This section will describe the structure of the source repository, that will serve as an input to cachi2. The idea is to
define a cachi2 lockfile that will specify individual artifacts to fetch along with necessary metadata - e.g. checksums.
The format chosen for this lockfile is yaml, and will include [purl](https://github.com/package-url/purl-spec) for each
of the fetched artifacts. This decision was made mainly because it allows for followup implementation of maven support,
with accurate SBOM information. Here's an example of such a lockfile.

```yaml
artifacts:
  - purl: pkg:generic/granite-model?download_url=https://huggingface.co/instructlab/granite-7b-lab/resolve/main/model-00001-of-00003.safetensors?download=true
    target: granite-model.safetensors
    checksums:
      sha256: 07123e1f482356c415f684407a3b8723e10b2cbbc0b8fcd6282c49d37c9c1abc
```

#### Lockfile format and validation

##### purl (required)

At this point, the only purl type allowed would be `pkg:generic`. This is because cachi2 has no good way of verifying
additional properties of the fetched artifact that could be included in the resulting SBOM. This should create a strong
incentive to use this feature in the only truly necessary cases, because it will generate low-quality SBOM components,
as compared to using other package managers provided by cachi2. Additionally, the only allowed qualifier should be `download_url`.

#### target (optional)

This is mainly for the users convenience, so the files end up in expected locations. Target here means a specific subdirectory
inside cachi2's output directory. Special care needs to be taken to ensure there is not a conflict with other downloaded files.
If not specified, filename of the downloaded file will be used.

##### checksums (optional)

I've chosen tho separate checksums from the purl, mostly for better readability of the lockfile, but this can be up for
discussion. If no checksum is provided, cachi2 should still download the artifact, but report this fact in the output
SBOM component.

### SBOM

Letting users specify artifacts as purls begs the question of authenticity of the data provided by the users and how it
should be handled in the resulting SBOM. As described above, the purl is restricted to its basic components, so there is
very little space for the user to provide inaccurate information. Cachi2 should verify that the file downloaded matches
checksums and report the purl as-is, as it contains no extra information. The section below outlines how that information
will be verified at later time.

### Validation of user input

As stated above, cachi2 will perform little to no verification of identity of the downloaded artifacts besides verifying
checksums. However, it will provide enough information in the SBOM so tooling that comes after cachi2 can enforce policies.
An example of this would be the [Enterprise Contract](https://enterprisecontract.dev/) (EC) project, that enforces policies
based on the provided SBOM.

In the context of this feature, EC policy would be supplied with the following information by cachi2:

- checksums were provided and verified
- list of checksum algorithms used
- download urls (as part of the purl)
  Enterprise contract policy would then be able to restrict accepting content without checksums, enforce certain algorithms
- for checksum verification or only allow certain patterns in the download url.

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
