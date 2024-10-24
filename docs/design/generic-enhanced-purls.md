# Purl enhancer for the generic artifact fetcher

The generic artifact package manager is being added to Cachi2 as a means for users to introduce files that do not belong to traditional package manager ecosystems (e.g. pip, npm, golang) to their hermetic container builds. Since Cachi2 does not have any extra information about the file that's being fetched, the purls are always reported as [pkg:generic](https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#generic).

There are use cases that would benefit from more accurate purls, though, such as the recent Maven artifacts [proposal](https://github.com/containerbuildsystem/cachi2/pull/663). Considering that the purl specification already identifies several types of packages that don't fit into traditional package manager (e.g. github, docker, huggingface; see the [purl types spec](https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst) for more info), this proposal builds on top of the fundamentals of the generic fetcher to provide an extensible mechanism that would allow Cachi2 to fetch files from specific sources and report them with matching purl types.

## Enhanced purls overview

Implement an `enhancer` for the purl types that exist in the [purl spec](https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst) that we choose to support. The enhancer will receive a `download_url` as input, validate and parse it to construct a purl that matches the type informed by the user. Additional data might be required to generate the purl, in which case they will be added to the lockfile.

Summary of changes needed:

- Extend the generic artifacts lockfile specification to introduce a `type` attribute that allows users to hint at which purl type that artifact should have.
- Allow a strict subset of `options` that match each specific type to provide any additional data that can't be inferred from the `donwload_url`.
- Validate that the `download_url` is in the expected format for a purl type, and that it is resolvable.
- Generate the purl from the attributes resolved during the parsing, use additional options in case where they are needed.
- Any failures to match the hinted `type` will cause the request to fail.

## A practical example

### Input files

**generic_artifacts.yaml**
```yaml
metadata:
    version: '1.0'
artifacts:
  - download_url: https://github.com/containerbuildsystem/cachi2/archive/refs/tags/0.11.0.tar.gz
    target: cachi2_0_11_0.tar.gz
    checksums: 
      sha256: fa0d536389db15fb3dabdb3b3d08354f47f765a653178140bfbe1b3de1a6ee76
  - download_url: https://maven.repository.internal.com/ga/io/quarkus/quarkus-core/3.8.5.internal-00004/quarkus-core-3.8.5.internal-00004.jar
    target: quakus.jar
    type: maven
    options:
        classifier: none
    checksums:
      sha1: e4ca5fadf89e62fb29d0d008046489b2305295bf
  - download_url: https://huggingface.co/nvidia/Llama-3.1-Nemotron-70B-Instruct-HF/blob/b919e5d07ce15f31ea741f2be99a00a33c3b427b/model-00001-of-00030.safetensors
    target: llama_3.1_1_of_30.safetensors
    type: huggingface
```

### Cachi2 CLI usage

```
cachi2 fetch-deps --source /path/to/repo generic
```

### Enhancer high-level definition

- MavenPurlEnhancer:
    - parses the download url and converts it into the expected purl
        ```bash
        # sample url
        https://maven.repository.internal.com/ga/io/quarkus/quarkus-core/3.8.5.internal-00004/quarkus-core-3.8.5.internal-00004.jar

        # how the parsing will be done
        # note that the classifier will be provided as separate option in the lockfile
        https://{repository_url}/{as_dir(group_id)}/{artifactId}/{version}/{artifact_id}-{version}[{-classifier}].{extension}

        # resulting purl
        # note that the type will need to be infered from the extension and potentially additional attributes
        pkg:maven/{groupId}/{artifactId}@{version}?type={type}&repository_url={repositoryUrl}&checksums={algorithm:checksum}
        ```
    - if the parsing can't be done, fail the request


- HuggingFacePurlEnhancer:
    - parsing the download_url and generating the purl
        ```bash
        # sample url
        https://huggingface.co/nvidia/Llama-3.1-Nemotron-70B-Instruct-HF/blob/b919e5d07ce15f31ea741f2be99a00a33c3b427b/model-00001-of-00030.safetensors

        # parsing the url
        https://{repository_url}/{namespace}/{name}/blob/{commit_hash}/model-00001-of-00030.safetensors

        # resulting purl
        pkg:huggingface/{namespace}/{name}@{commit_hash}&download_url={download_url}

        ```
    - if the parsing can't be done, fail the request

### Resulting SBOM
```json
{
    "components": [
        {
            "name": "cachi2-0.11.0.tar.gz",
            "purl": "pkg:generic/cachi2_0_11_0.tar.gz?checksum=sha256:fa0d536389db15fb3dabdb3b3d08354f47f765a653178140bfbe1b3de1a6ee76&download_url=https://github.com/containerbuildsystem/cachi2/archive/refs/tags/0.11.0.tar.gz",
            "properties": [
                {
                    "name": "cachi2:found_by",
                    "value": "cachi2:generic"
                }
            ],
            "externalReferences": [
                {
                    "type": "distribution",
                    "url": "https://github.com/containerbuildsystem/cachi2/archive/refs/tags/0.11.0.tar.gz"
                }
            ],
            "type": "file"
        },
        {
            "name": "quakus-core",
            "version": "3.8.5.internal-00004",
            "purl": "pkg:maven/ga.io.quarkus/quarkus-core@3.8.5.internal-00004?type=jar&repository_url=https://maven.repository.internal.com&checksums=sha1:e4ca5fadf89e62fb29d0d008046489b2305295bf",
            "properties": [
                {
                    "name": "cachi2:found_by",
                    "value": "cachi2:generic"
                }
            ],
            "externalReferences": [
                {
                    "type": "distribution",
                    "url": "https://maven.repository.internal.com/ga/io/quarkus/quarkus-core/3.8.5.internal-00004/quarkus-core-3.8.5.internal-00004.jar"
                }
            ],
            "type": "file"
        },
        {
            "name": "Llama-3.1-Nemotron-70B-Instruct-HF",
            "purl": "pkg:huggingface/nvidia/Llama-3.1-Nemotron-70B-Instruct-HF@043235d6088ecd3dd5fb5ca3592b6913fd516027&download_url=https://huggingface.co/nvidia/Llama-3.1-Nemotron-70B-Instruct-HF/blob/b919e5d07ce15f31ea741f2be99a00a33c3b427b/model-00001-of-00030.safetensors",
            "properties": [
                {
                    "name": "cachi2:found_by",
                    "value": "cachi2:generic"
                }
            ],
            "externalReferences": [
                {
                    "type": "distribution",
                    "url": "https://huggingface.co/nvidia/Llama-3.1-Nemotron-70B-Instruct-HF/blob/b919e5d07ce15f31ea741f2be99a00a33c3b427b/model-00001-of-00030.safetensors"
                }
            ],
            "type": "file"
        },
    ]
}
```
