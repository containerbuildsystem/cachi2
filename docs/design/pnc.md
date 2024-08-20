**# Design document for PNC package manager

Contents:

1. [PNC](#PNC)
2. [Current implementation overview (OSBS)](#overview-of-the-current-implementation-in-osbs)
3. [Design for the Cachi2 implementation](#design-for-the-implementation-in-cachi2)

## PNC
Also known as Project NewCastle - [open-source project](https://github.com/project-ncl/pnc) for managing, executing, 
and tracking cross-platform builds. The part that is important for cachi2 integration is the exposed API that provides
information about builds and their artifacts, as well as the means to download those artifacts. The API does not require
authentication.

### Relevant endpoints and their payloads
#### /artifacts/{id}
This endpoint takes an `id` of an artifact from the `fetch-artifacts-pnc.yaml` file. It will respond with
various information about the specified artifact. The API response is [documented here](https://github.com/project-ncl/pnc-api/blob/5b35ad6fe22769510f60b0025752dc6c954c9734/src/main/java/org/jboss/pnc/api/repositorydriver/dto/RepositoryArtifact.java).
Below is an example response, some irrelevant fields left out:
```json
{
  "id": "1234",
  "identifier": "org.example:package:zip:1.2.3.org-1",
  "purl": "pkg:maven/org.example/package@1.2.3.org-1?type=zip",
  "artifactQuality": "NEW",
  "buildCategory": "STANDARD",
  "md5": "<md5 hash>",
  "sha1": "<sha1 hash>",
  "sha256": "<sha256 hash>",
  "filename": "package-1.2.3.org-1.zip",
  "deployPath": "<path>",
  "importDate": null,
  "originUrl": null,
  "size": 12345,
  "deployUrl": "<local url>",
  "publicUrl": "<public url>",
  "creationTime": null,
  "modificationTime": "2023-08-14T15:04:44.388Z",
  "qualityLevelReason": null,
  "targetRepository": {
    "id": "456",
    "temporaryRepo": false,
    "identifier": "indy-maven",
    "repositoryType": "MAVEN",
    "repositoryPath": "/api/content/maven/hosted/pnc-builds/"
  },
  "build": {
    "id": "ABCD123",
    "submitTime": "2023-08-14T14:43:16.097Z",
    "startTime": "2023-08-14T14:43:16.179Z",
    "endTime": "2023-08-14T15:04:44.494Z",
    "progress": "FINISHED",
    "status": "SUCCESS",
    "buildContentId": "build-ABCD123",
    "temporaryBuild": false,
    "alignmentPreference": null,
    "scmUrl": "<source repo>",
    "scmRevision": "<hash>",
    "scmTag": "1.2.3.org-1-ABCD123",
    "buildOutputChecksum": "<hash>",
    "lastUpdateTime": "2023-08-14T15:05:02.382Z",
    "scmBuildConfigRevision": null,
    "scmBuildConfigRevisionInternal": null,
    "project": {
      "id": "5",
      "name": "package-parent",
      "description": null,
      "issueTrackerUrl": null,
      "projectUrl": null,
      "engineeringTeam": null,
      "technicalLeader": null
    },
    "attributes": {
      "BREW_BUILD_VERSION": "1.2.3.org-1",
      "BUILD_OUTPUT_OK": "false",
      "BREW_BUILD_NAME": "org.example:package-parent"
    },
    "noRebuildCause": null
  },
  "creationUser": null
}
```

#### /builds/{id}/scm-archive
This endpoint will return the source build archive as a tarball (.tar.gz). Build `id` can be located in
the  `fetch-artifacts-pnc.yaml` file.


## Overview of the current implementation in OSBS

### Repository configuration 
Projects that currently use OSBS to fetch sources from PNC do so through a file named `fetch-artifacts-pnc.yaml`
([docs](https://osbs.readthedocs.io/en/osbs_ocp3/users.html?highlight=fetch#fetch-artifacts-pnc-yaml)).
Example of a `fetch-artifacts-pnc.yaml` file:

```yaml
metadata:
  # this object allows additional parameters, you can put any metadata here
  author: shadowman
builds:
  # all artifacts are grouped by builds to keep track of their sources
  - build_id: '1234' # build id must be string
    artifacts:
      # list of artifacts to fetch, artifacts are fetched from PNC using their IDs
      - id : '12345' # artifact id must be string
        # the target can just be a filename or path+filename
        target: test/rhba-common-7.10.0.redhat-00004.pom
      - id: '12346'
        target: prod/rhba-common-7.10.0.redhat-00004-dist.zip
  - build_id: '1235'
    artifacts:
      - id: '12354'
        target: test/client-patcher-7.10.0.redhat-00004.jar
      - id: '12355'
        target: prod/rhdm-7.10.0.redhat-00004-update.zip
```

These artifacts are fetched to `artifacts/<target>` path at the root of the repository.

### PNC instance configuration
Currently, the url of the PNC instance is configured as a part of OSBS config. 



[atomic_reactor/plugins/fetch_maven_artifacts.py](https://github.com/containerbuildsystem/atomic-reactor/blob/master/atomic_reactor/plugins/fetch_maven_artifacts.py)
1) OSBS loads the `fetch-artifacts-pnc.yaml`
2) Information about individual artifacts is fetched from PNC API at `/artifacts/{id}` endpoint ([docs](https://github.com/project-ncl/pnc-api/blob/5b35ad6fe22769510f60b0025752dc6c954c9734/src/main/java/org/jboss/pnc/api/repositorydriver/dto/RepositoryArtifact.java))
   - `publicUrl` key is used to get download url
   - supported checksums are saved
   - build ids are saved
3) Download queue is formed containing above info for each artifact
4) SBOM component info for each artifact is fetched from PNC @ `/artifacts/{id}`, `purl` key
5) Queue is executed and each artifact is downloaded, checksum verified
6) SBOM is compiled, including PNC components from step 4)


### Missing features

PNC SBOM components don't have the most complete purl, e.g.:
`pkg:maven/org.kie.trustyai/explainability-service@999.0.0.managedsvc-redhat-00001?type=zip`

According to [purl spec](https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#maven), `classfier` and
`type` parameters should be also defined, method is currently pending depending on if the artifacts are single components,
or products that contain other components. Purl should also specify a `repository_url` parameter.



## Design for the implementation in Cachi2

### PNC config
Existing `fetch-artifacts-pnc.yaml` file ([docs](https://osbs.readthedocs.io/en/osbs_ocp3/users.html?highlight=fetch#fetch-artifacts-pnc-yaml))
will be used as configuration. It needs to be extended to also include PNC instance url.

### Pre-fetch PNC dependencies
Cachi2 will use the `artifacts` key specified in the `fetch-artifacts-pnc.yaml` file to fetch info about given artifacts
from PNC (`/artifacts/{id}` endpoint), including url to download the artifact, checksums to verify integrity, and the purl.
The artifacts should be fetched into a separate subdirectory in cachi2 output folder, and into the target path.

#### Fetching sources
Cachi2 will use the `build_id` keys to fetch build sources from PNC (`/builds/{id}/scm-archive` endpoint). These sources
should be fetched into a separate subdirectory in cachi2 output folder, different from the artifacts.

### Generating the SBOM
As mentioned in [missing features](#missing-features), the purl needs to specify more parameters
- `repository_url` - obtainable by using host part of `publicUrl` and the path in `targetRepository.repositoryPath`
  from PNC `/artifacts/{id}` endpoint response.
- `type` & `classifier` - solution pending

Here's an example purl that should be generated:
```
pkg:maven/org.example/package@1.2.3.org-1?type=zip&classifier=dist&repository_url=https://repo.maven.apache.org/maven2
```

#### Relevant configuration for the build
No environment variables need to be set.

#### Expected location of artifacts
The current implementation expects artifacts in the `artifacts/` path in the root of repository.
Due to cachi2's usual design patterns, the artifacts will remain in cachi2's default output directory
(`./cachi2-output`), and users will be required to act accordingly.


### Summary
- define models for PNC as the new package manager
- design high-level code structure into multiple modules
- parse `fetch-artifacts-pnc.yaml` 
- fetch artifact info from PNC and download artifacts
- validate checksums when downloading artifacts
- download build source tarballs
- generate PURLs for all dependencies
- add integration and e2e tests
- add documentation
