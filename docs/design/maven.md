# Maven artifact fetching

## Introduction

This document will describe high-level implementation overview for supporting fetching maven artifacts in cachi2. This
proposal depends on generic artifact fetching, which is described in this [design PR][generic-pr].

## Context

[Maven] is a Java ecosystem build system and functions basically as a package manager, among other things. Maven provides a
standardized way to specify dependencies in a `pom.xml` file, which is then used to fetch dependencies from a maven repository.
This feature in cachi2 isn't concerned with pre-fetching entire maven projects, but rather to provide a way to fetch individual
artifacts from maven repository. This is useful for cases where the build only needs specific artifacts from big projects,
saving time and bandwidth.

### Maven artifacts

[Maven artifacts][maven-artifacts] are defined as anything that resides in a maven repository. Maven has a special way of
addressing artifacts in its repositories called coordinates, which are usually represented by a `GAV` tuple (stands for
'Group, Artifact, Version').
This is used to uniquely identify an artifact in a maven repository.

### Maven purls

Purls for `pkg:maven` ([docs][maven-purl]) fully describe the location of an artifact in a maven repository. That is because
all parts of the purl (`namespace`, `name`, `version` and the `classifier` and `type` qualifiers) are used to construct
the download url for the artifact and map directly to tge `GAV` coordinates.[Maven documentation][maven-repo-layout] describes
how to turn these coordinates into an actual download url. Here's an example:

**Purl:**

```
pkg:maven/ga.io.quarkus/quarkus-core@3.8.5.redhat-00004?type=jar&repository_url=https://maven.repository.redhat.com&checksums=sha1:e4ca5fadf89e62fb29d0d008046489b2305295bf
```

**Mapping to GAV:**

```
groupId: ga.io.quarkus
artifactId: quarkus-core
version: 3.8.5.redhat-00004
classifier: null
type: jar
```

Using `classifier` and `type` we can determine the `extension` is `jar` ([docs][maven-extension]).

**Download url**:

Template:

```
${groupId as directory}/${artifactId}/${baseVersion}/${artifactId}-${version}.${extension}
```

Resulting url:

```
https://maven.repository.redhat.com/ga/io/quarkus/quarkus-core/3.8.5.redhat-00004/quarkus-core-3.8.5.redhat-00004.jar
```

## Design

In this section, I will try to cover individual parts of the design.

### Source repository (cachi2 lockfile)

Currently, the cachi2 lockfile only allows `pkg:generic` purl type. This design will introduce a new purl type `pkg:maven`
to support pre-fetching individual maven artifacts. The lockfile currently supports specifying the file to be fetched either
as a purl or as a pair of `download_url` and `checksums`. Maven artifacts should only be specified as a purl in order to
be reported as such in the output SBOM. Here's an example of a lockfile that fetches a maven artifact:

```yaml
metadata:
  version: 1.0.0
artifacts:
  - purl: pkg:maven/ga.io.quarkus/quarkus-core@3.8.5.redhat-00004?type=jar&repository_url=https://maven.repository.redhat.com&checksums=sha1:e4ca5fadf89e62fb29d0d008046489b2305295bf
    target: quarkus.jar
```

### Integration with existing cachi2 features

As mentioned above, the lockfile format is identical to the one used for describing generic artifacts, therefore it makes
sense to extend the existing lockfile with support for maven purls. The only difference would be in the output SBOM where
maven artifacts would be reported as `pkg:maven`, instead of `pkg:generic`.

There is an open question of how the UX should be. I will try to list the available options with some pros and cons.

#### 1) Completely encapsulated in generic package manager

This option would just extend the lockfile with support for maven purls, meaning the user would still be calling just the
generic package manager. The benefit of this approach would be simplicity, as it would one package manager per lockfile.
On the other hand, maven artifacts are not so generic.

Example:
```
cachi2 fetch-deps --source /path/to/sources '[{"type": "generic"}]'
```

#### 2) As a separate package manager

This option would actually add a maven package manager. However, this would mean that the generic package manager would
only process some of the artifacts in the lockfile, and some would not be processed unless maven package manager is
explicitly called. This might create some weird UX for the user as they might expect the lockfile to be processed all at
once, since it is cachi2 specific.

Example:
```
cachi2 fetch-deps --source /path/to/sources '[{"type": "generic"}, {"type": "maven-artifacts"}]'
```

### SBOM

As described in the [Maven purls](#maven-purls) section, every component of the purl is used to calculate the download url.
Therefore, if the purl resolves to a valid url, and the provided checksums match the downloaded content, the purl accurately
describes the downloaded artifact and can be used in the output SBOM. Additionally, the resolved download url should be
embedded into the SBOM under [ExternalReferences][external-references] key with `type` set to `distribution`. This is same
as with generic artifact fetching, and provides a way to possibly gate content in the SBOM based on allowed hosts.

As with the generic artifact fetching, cachi2 would not enforce any sort of further verification on the downloaded content.

### Integration testing

This feature would build on top of the generic fetching, so its integration test would be similar. Since there is a number
of public maven repositories, there should be no problem in using them for testing.

## Outcome

Here's a preliminary work breakdown:

- Implement support for maven purls in the lockfile
- Extend integration tests
- Document fetching of maven artifacts

[external-references]: https://cyclonedx.org/docs/1.4/json/#externalReferences
[generic-pr]: https://github.com/containerbuildsystem/cachi2/pull/652
[maven]: https://maven.apache.org/what-is-maven.html
[maven-artifacts]: https://maven.apache.org/repositories/artifacts.html
[maven-extension]: https://maven.apache.org/repositories/artifacts.html#but-where-do-i-set-artifact-extension
[maven-purl]: https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#maven
[maven-repo-layout]: https://maven.apache.org/repositories/layout.html
