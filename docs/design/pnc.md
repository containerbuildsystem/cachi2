**# Design document for PNC package manager

Contents:

1. [PNC](#PNC)
2. [Current implementation overview (OSBS)](#overview-of-the-current-implementation-in-osbs)
3. [Design for the Cachi2 implementation](#design-for-the-implementation-in-cachi2)

## PNC

### Glossary
- **PNC**: Project NewCastle - [open-source project](https://github.com/project-ncl/pnc) for managing, executing, 
  and tracking cross-platform builds.


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

## Overview of the current implementation in OSBS

[atomic_reactor/plugins/fetch_maven_artifacts.py](https://github.com/containerbuildsystem/atomic-reactor/blob/master/atomic_reactor/plugins/fetch_maven_artifacts.py)
1) OSBS loads the `fetch-artifacts-pnc.yaml`
2) Information about individual artifacts is fetched from PNC api at `/artifacts/{id}` endpoint
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


### Providing the content for the hermetic build

#### PNC config
Existing `fetch-artifacts-pnc.yaml` file ([docs](https://osbs.readthedocs.io/en/osbs_ocp3/users.html?highlight=fetch#fetch-artifacts-pnc-yaml))
will be used as configuration. It needs to be extended to also include PNC instance url.

#### Pre-fetch PNC dependencies
Cachi2 will use the `artifacts` key specified in the `fetch-artifacts-pnc.yaml` file to fetch info about given artifacts
from PNC (`/artifacts/{id}` endpoint), including url to download the artifact, checksums to verify integrity, and the purl.
The artifacts should be fetched into a separate subdirectory in cachi2 output folder, and into the target path.

##### Fetching sources
Cachi2 will use the `build_id` keys to fetch build sources from PNC (`/builds/{id}/scm-archive` endpoint). These sources
should be fetched into a separate subdirectory in cachi2 output folder, different from the artifacts.

### Generating the SBOM
As mentioned in [missing features](#missing-features), the purl needs to specify more parameters
- `repository_url` - obtainable by using host part of `publicUrl` and the path in `targetRepository.repositoryPath`
  from PNC `/artifacts/{id}` endpoint response.
- `type` & `classifier` - solution pending

#### Relevant configuration for the build
No environment variables need to be set.

#### Injecting files to an expected location
The actual artifacts should be injected into `artifacts/` path in the repository. 


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
