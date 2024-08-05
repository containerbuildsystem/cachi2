# Cargo overview

## Main files

```
├── .cargo
│   └── config.toml
├── Cargo.toml
├── Cargo.lock
└── src
    └── main.rs (or lib.rs)
```

- Cargo.toml: dependency listing and project configuration.
- Cargo.lock: lockfile that contains the latest resolved dependencies.
- .cargo/config.toml: package manager specific configuration.

### Glossary

- crate: smallest amount of code that the Rust compiler considers at a time.
- package: a bundle of one or more crates that provides a set of functionality; defined by a `Cargo.toml`
file.

## [Specifying dependencies](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html)

The examples below show what types of dependencies Cargo supports, and how they can be specified in the
`Cargo.toml` file.

<details>
  <summary>default registry (crates.io)</summary>

  ```toml
  [dependencies]
  # pinned version
  heck = "0.4.1"

  # pinned version, same as above
  heck = "^0.4.1"

  # greater than
  heck = "~0.4.1"

  # wildcard
  heck = "0.4.*"
  ```
</details>

<details>
  <summary>git</summary>

  ```toml
  [dependencies]
  # will fetch latest commit from default branch
  rand = { git = "https://github.com/rust-random/rand" }

  # fetch specific branch
  rand = { git = "https://github.com/rust-random/rand", branch = "main" }

  # fetch specific tag
  rand = { git = "https://github.com/rust-random/rand", tag = "alpha" }

  # fetch specific commit
  rand = { git = "https://github.com/rust-random/rand", rev = "8792268dfe57e49bb4518190bf4fe66176759a44" }

  # fetch the dependency and validate if the version matches what was pinned
  # can be used alongside any of the variations above
  rand = { git = "https://github.com/rust-random/rand", rev = "8792268dfe57e49bb4518190bf4fe66176759a44", version = "0.8.4"}
  ```
</details>

<details>
  <summary>path</summary>

  ```toml
  [dependencies]
  heck = { path = "./heck" }
  ```
</details>


<details>
  <summary>platform specific</summary>

  TODO
  - note: in cargo docs, "platform" refers interchangeably to both architecture and OS
  - cargo has support for specifying dependencies under a certain platform, like 
      ```
      [target.'cfg(windows)'.dependencies]
      winhttp = "0.4.0"

      [target.'cfg(unix)'.dependencies]
      openssl = "1.0.1"
      ```
      or
      ```
      [target.x86_64-pc-windows-gnu.dependencies]
      winhttp = "0.4.0"

      [target.i686-unknown-linux-gnu.dependencies]
      openssl = "1.0.1"
      ``
  - Regardless, as far as we could tell from experimenting, cargo build requires ALL dependencies to be present - even if they won't be used.
  - as a potential optimization, [cargo-vendor-filterer](https://github.com/coreos/cargo-vendor-filterer/) can vendor cargo dependencies
    - if we adopt this approach, it might be limited to pure-rust builds
</details>

<details>
  <summary>multiple locations</summary>

  A package can't be published to crates.io if it has a git or a path dependency without a version number.
  This is because when building the package locally, it will use the git or path dependency, but when it's
  published to crates.io, it'll use the registry version of the dependency.

  ```toml
  [dependencies]
  # the version also needs to be specified in case the crate will be published to crates.io
  rand = { git = "https://github.com/rust-random/rand", rev = "8792268dfe57e49bb4518190bf4fe66176759a44", version = "0.8.4"}
  heck = { path = "./heck", version = "0.4.1" }
  ```
</details>

<details>
  <summary>platform specific</summary>

  TODO
</details>

<details>
  <summary>alternative registry</summary>

  Once an alternative registry is configured in `.cargo/config.toml`, it can be used to specify a
  dependency.

  ```toml
  [dependencies]
  some-crate = { version = "1.0", registry = "my-registry" }
  ```
</details>

### Cargo.lock

The `Cargo.lock` file follows the toml format. Here are some examples of how dependencies are
represented in it.

<details>
  <summary>main or local package</summary>

  ```toml
  [[package]]
  name = "rustic"
  version = "0.1.0"
  dependencies = [
  "adler",
  "bombadil",
  "clap",
  "heck",
  "indicatif",
  "rand 0.8.4",
  "textwrap",
  "utils",
  ]
  ```
</details>

<details>
  <summary>crates.io package</summary>

  ```toml
  [[package]]
  name = "rand_hc"
  version = "0.2.0"
  source = "registry+https://github.com/rust-lang/crates.io-index"
  checksum = "ca3129af7b92a17112d59ad498c6f81eaf463253766b90396d39ea7a39d6613c"
  dependencies = [
  "rand_core 0.5.1",
  ]
  ```
</details>

<details>
  <summary>git package</summary>

  ```toml
  [[package]]
  name = "rand_core"
  version = "0.6.3"
  source = "git+https://github.com/rust-random/rand?rev=8792268dfe57e49bb4518190bf4fe66176759a44#8792268dfe57e49bb4518190bf4fe66176759a44"
  dependencies = [
  "getrandom 0.2.11",
  ]
  ```
</details>


## Other dependency types

Besides regular dependencies, cargo also supports 
[dev](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#build-dependencies)
and [build](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#build-dependencies)
dependencies. Here's how they're defined in `Cargo.toml`:

```toml
[dev-dependencies]
textwrap = "0.15.2"

[build-dependencies]
adler = "0.2.3"
```

They are resolved in the exact same way as regular dependencies in the `Cargo.lock` file, which
means they can't be identified just by looking at this file. They can be identified via the
`cargo manifest` command, or by looking at the `Cargo.toml file`.

## [Workspaces](https://doc.rust-lang.org/cargo/reference/workspaces.html)
A workspace is simply a way to manage multiple packages together. This means it'll have a single
`Cargo.lock` file and that common `cargo` commands will affect all packages within the workspace.
Also, all path dependencies are automatically considered a workspace member if they reside in the
workspace.

Since workspaces are also path dependencies, they will be reported as expected in the Cargo.toml
file or via the `cargo metadata` command.

<details>
  <summary>sample project structure</summary>
  ```
  ├── Cargo.toml
  ├── Cargo.lock
  ├── src
  │   └── main.rs
  └── utils
      └── lib.rs
  ```
</details>

<details>
  <summary>sample Cargo.toml</summary>

  ```toml
  [workspace]
  members = ["utils"]

  [package]
  name = "my-pkg"
  version = "0.1.0"

  [dependencies]
  utils = { path = "utils" }
  ```
</details>

## Features

*TODO*

## [Build Scripts](https://doc.rust-lang.org/cargo/reference/build-scripts.html)

Any package that contains a `build.rs` file in it's root will have it executed during build-time.
Note that this does not happen in any other stage, such as during vendoring or dependency fetching.

## [Vendoring](https://doc.rust-lang.org/cargo/commands/cargo-vendor.html)

Cargo offers the option to vendor the dependencies by using `cargo vendor`. All dependencies
(including git dependencies) are downloaded to the `./vendor` folder by default.

The command also prints the required configuration that needs to be added to `.cargo/config.toml`
in order for the offline compilation to work. Here's an example:

```toml
[source.crates-io]
replace-with = "vendored-sources"

[source."git+https://github.com/rust-random/rand?rev=8792268dfe57e49bb4518190bf4fe66176759a44"]
git = "https://github.com/rust-random/rand"
rev = "8792268dfe57e49bb4518190bf4fe66176759a44"
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
```

Note that each git dependency has its own separate configuration in the generated output.
Also, vendoring does not trigger any builds scripts.


# Cargo support in Cachi2

## Approach 1: use cargo commands

### Identifying the dependencies

It can be done by using the `cargo metadata` command, so there's no need to parse the
`Cargo.lock` file. Here's an example:

```
$ cargo metadata --frozen | jq '.packages[] | select(.name == "adler")'
```

<details>
  <summary>json output</summary>

  ```json
  {
    "name": "adler",
    "version": "0.2.3",
    "id": "adler 0.2.3 (registry+https://github.com/rust-lang/crates.io-index)",
    "license": "0BSD OR MIT OR Apache-2.0",
    "license_file": null,
    "description": "A simple clean-room implementation of the Adler-32 checksum",
    "source": "registry+https://github.com/rust-lang/crates.io-index",
    "dependencies": [
      {
        "name": "compiler_builtins",
        "source": "registry+https://github.com/rust-lang/crates.io-index",
        "req": "^0.1.2",
        "kind": null,
        "rename": null,
        "optional": true,
        "uses_default_features": true,
        "features": [],
        "target": null,
        "registry": null
      },
      {
        "name": "rustc-std-workspace-core",
        "source": "registry+https://github.com/rust-lang/crates.io-index",
        "req": "^1.0.0",
        "kind": null,
        "rename": "core",
        "optional": true,
        "uses_default_features": true,
        "features": [],
        "target": null,
        "registry": null
      },
      {
        "name": "criterion",
        "source": "registry+https://github.com/rust-lang/crates.io-index",
        "req": "^0.3.2",
        "kind": "dev",
        "rename": null,
        "optional": false,
        "uses_default_features": true,
        "features": [],
        "target": null,
        "registry": null
      }
    ],
    "targets": [
      {
        "kind": [
          "lib"
        ],
        "crate_types": [
          "lib"
        ],
        "name": "adler",
        "src_path": "/home/bpimente/.cargo/registry/src/index.crates.io-6f17d22bba15001f/adler-0.2.3/src/lib.rs",
        "edition": "2015",
        "doc": true,
        "doctest": true,
        "test": true
      },
      {
        "kind": [
          "bench"
        ],
        "crate_types": [
          "bin"
        ],
        "name": "bench",
        "src_path": "/home/bpimente/.cargo/registry/src/index.crates.io-6f17d22bba15001f/adler-0.2.3/benches/bench.rs",
        "edition": "2015",
        "doc": false,
        "doctest": false,
        "test": false
      }
    ],
    "features": {
      "compiler_builtins": [
        "dep:compiler_builtins"
      ],
      "core": [
        "dep:core"
      ],
      "default": [
        "std"
      ],
      "rustc-dep-of-std": [
        "core",
        "compiler_builtins"
      ],
      "std": []
    },
    "manifest_path": "/home/bpimente/.cargo/registry/src/index.crates.io-6f17d22bba15001f/adler-0.2.3/Cargo.toml",
    "metadata": {
      "docs": {
        "rs": {
          "rustdoc-args": [
            "--cfg docsrs"
          ]
        }
      },
      "release": {
        "no-dev-version": true,
        "pre-release-commit-message": "Release {{version}}",
        "tag-message": "{{version}}",
        "pre-release-replacements": [
          {
            "file": "CHANGELOG.md",
            "replace": "## Unreleased\n\nNo changes.\n\n## [{{version}} - {{date}}](https://github.com/jonas-schievink/adler/releases/tag/v{{version}})\n",
            "search": "## Unreleased\n"
          },
          {
            "file": "README.md",
            "replace": "adler = \"{{version}}\"",
            "search": "adler = \"[a-z0-9\\\\.-]+\""
          },
          {
            "file": "src/lib.rs",
            "replace": "https://docs.rs/adler/{{version}}",
            "search": "https://docs.rs/adler/[a-z0-9\\.-]+"
          }
        ]
      }
    },
    "publish": null,
    "authors": [
      "Jonas Schievink <jonasschievink@gmail.com>"
    ],
    "categories": [
      "algorithms"
    ],
    "keywords": [
      "checksum",
      "integrity",
      "hash",
      "adler32"
    ],
    "readme": "README.md",
    "repository": "https://github.com/jonas-schievink/adler.git",
    "homepage": null,
    "documentation": "https://docs.rs/adler/",
    "edition": "2015",
    "links": null,
    "default_run": null,
    "rust_version": null
  }
  ```
</details>

The `source` key shows where the package was fetched from, and will be `null` for local dependencies.
This way, we can identify path and git dependencies, as well as the main package and dependencies
fetched from non-default registries.

Dev and build dependencies have respective `kind`s when listed in the nested `.dependencies` key.
To indentify them and mark them as such in the SBOM, we'd need only to check all the times a single
package appears as a transitive dependency in this output.

### Prefetching

Prefetching the packages can be done by simply using the `cargo vendor` command:

```
$ cargo vendor ./cachi2-output/deps/cargo'
```

The command will handle all types of dependencies and allow them to be used during the build stage.

### Building hermetically

When vendoring, the `cargo vendor` command also outputs the necessary configuration to use the
vendored deps to build or run the project (see [Vendoring](#vendoring)). We'd need to simply
wrap this configuration in a project file.

### Summary
Pros:
- Trivial to use and less error-prone, since we're relying on a built-in command
- Repo configuration is generated automatically by the vendoring command

Cons:
- Relying on a built-in command brings it's own disadvantages:
  - We have less control on what will be executed when invoking `cargo` commands
  - We need to account for cargo behavior changes more closely
  - We need install cargo in the Cachi2 image and keep its version up to date
- Might make it harder to build Pip+Rust projects
  - Cargo will refuse to vendor an empty directory with a single `Cargo.toml` file, which
  means we'd need to minimally provide a minimal `src/main.rs` file to it.


## Approach 2: manually fetching the dependencies

### Identifying the dependencies

By parsing the `Cargo.lock` file, we can easily identify all dependencies that were downloaded
the last time the project was built, and where to fetch them from. This file is a `toml` file,
which makes its parsing very trivial (see examples in [Cargo.lock](#cargolock)). 

The only downside we have here is that `Cargo.lock` does not specify which dependencies are
"dev" or "build". We'd need to rely on the info in `Cargo.toml` to identify those.

### Prefetching

The info parsed from `Cargo.lock` contains the location of where each package was fetched from
(in the `source` key), as well as its checksum (for registry dependencies).

With this info, we could simply fetch the packages from the internet (i.e. crates.io
in the majority of cases) using any standard method.

### Building hermetically

To build the project using local files, we'd need to use the same configuration as if the
files were vendored by cargo (check [option 1](#building-hermetically)). There are two
caveats to make this work manually, though:

**1 .cargo-checksum.json file:**

A file that cargo expects to live in the root of every package in a filesystem. It can be
generated by calculating the checksum of every file contained in the package.

<details>
  <summary>Sample file</summary>

  ```json
  {
    "files": {
      "CHANGELOG.md": "042ed3158af7000c88a6617d775f11456bd30f6c7c8b5b586978faa1e11b1e24",
      "Cargo.toml": "107d13689eecfa82a8b5ae35bf835b9d2775337226630e4bdb35f22d0dd52e18",
      "LICENSE-0BSD": "861399f8c21c042b110517e76dc6b63a2b334276c8cf17412fc3c8908ca8dc17",
      "LICENSE-APACHE": "8ada45cd9f843acf64e4722ae262c622a2b3b3007c7310ef36ac1061a30f6adb",
      "LICENSE-MIT": "23f18e03dc49df91622fe2a76176497404e46ced8a715d9d2b67a7446571cca3",
      "README.md": "fa83fd5ee10b61827de382e496bf66296a526e3d2c3b2aa5ad672aa15e8d2d7f",
      "RELEASE_PROCESS.md": "a86cd10fc70f167f8d00e9e4ce0c6b4ebdfa1865058390dffd1e0ad4d3e68d9d",
      "benches/bench.rs": "c07ce370e3680c602e415f8d1ec4e543ea2163ab22a09b6b82d93e8a30adca82",
      "src/algo.rs": "b664b131f724a809591394a10b9023f40ab5963e32a83fa3163c2668e59c8b66",
      "src/lib.rs": "67f3ca5b6333e22745b178b70f472514162cea2890344724f0f66995fcf19806"
    },
    "package": "ee2a4ec343196209d6594e19543ae87a39f96d5534d7174822a3ad825dd6ed7e"
  }
  ```
</details>

<br>

**2. Nested packages:**

If a package contains subpackages (i.e. path dependencies), we will need to unnest them and provide
a flat folder structure, as `cargo vendor` would do.

**Default file structure:**
```
└──package
    ├── Cargo.toml
    ├── src
    │   └── main.rs
    ├── subpackage-1
    │   ├── Cargo.toml
    │   └── src
    │     └── lib.rs
    └── subpackage-2
        ├── Cargo.toml
        └──src
            └── lib.rs
```

**Changes needed for offline installs:**

```
├──package
│   ├── .cargo-checksum.json
│   ├── Cargo.toml
│   └── src
│       └── main.rs
├──subpackage-1
│   ├── .cargo-checksum.json
│   ├── Cargo.toml
│   └── src
│       └── main.rs
└──subpackage-1
    ├── .cargo-checksum.json
    ├── Cargo.toml
    └── src
        └── main.rs
```

### Summary

Pros:
- We won't rely on the `cargo` binary, so all the downsides of option 1 are not applicable
- Zero risk of arbitrary code execution

Cons:
- Checksum files need to be manually generated
- Sub-packages in git dependencies need to moved to a flat structure
- The "vendor" configuration needs to be generated manually

# Caveats

## Crates with binaries

Crates are supposed to contain only source code. However, crates.io don't seem to enforce any
rule to prohibit crates being uploaded with binaries. This happened at least once with [serde](https://www.bleepingcomputer.com/news/security/rust-devs-push-back-as-serde-project-ships-precompiled-binaries/),
one of the most popular rust libraries.

# Pip + Cargo support in Cachi2

WIP

## Context

Traditionally, performance bottlenecks in the python ecosystem are addressed with C extensions, which introduce their own complexities and safety concerns.

Rust, with its performance, memory safety, and concurrency capabilities, is emerging as an effective solution. Key Python packages like `cryptography` and `pydantic-core` have incorporated Rust to enhance their performance and reliability​​. Additionally, the Rust-based linter `ruff` is gaining popularity due to its speed and compatibility with tools like `flake8` and `pylint​`.

Tools such as `PyO3`, `Rust-CPython`, `maturin`, and `setuptools-rust` simplify the integration of Rust into Python (and python into rust as well, in the case of `PyO3`)​.

Addressing the integration challenges of Rust in Python projects is crucial to enhancing the performance, safety, and concurrency of Python applications. The "rustification" of Python libraries is here to stay.

## Build dependencies

`maturin` and `setuptools-rust` are PEP517 compliant build backends for python packages with embedded rust code.

Under the hood, `maturin` relies exclusively on `PyO3` while `setuptools-rust` can use either `PyO3` or `Rust-CPython` (but newer projects are likely preferring the former, as the author
of `Rust-CPython` development is halted and its author recommends `PyO3`).

## Detecting python packages with rust dependencies

We could use the presence of either `maturin` or `setuptools-rust` as build dependencies of a python package as a
heuristic to determine if a package is a python+rust library. Alternatively, we could simply brute force searching for `.rs` sources and/or `Cargo.toml/lock`, but looking at build dependency has one advantage on potentially confusing situations.

In a research with popular python packages and github python projects relying on maturin or setuptools rust,
one interesting finding is that some packages contain multiple Cargo.locks. That usually happens when the library
vendored some other rust code for whatever reason. In this case, it would be better to use for downstream vendoring
only the "main" lock file, which presumably would be pointing to the rest of the code.

Packages relying on `maturin` and `setuptools` have a default place to have their main Cargo.toml/lock stored.
Also, parsing the configuration it is possible to know if the path for those manifests were modified.

### maturin
Detecting `maturin` is easier because it only supports python packages that use `pyproject.toml` to configure it. So detecting its presence is only a matter of verifying if `[build-system].requires` contains `maturin`.

example:

```toml
#pyproject.toml
[build-system]
requires = ["maturin"]
```

As for the manifest location, `maturin` looks at two places by default:
- same folder as in `pyproject.toml`
- `rust/`

The manifest path can be customized under `[tool.maturin].manifest-path`.

example:
```toml
#pyproject.toml
[tool.maturin]
# Cargo manifest path
manifest-path = "Cargo.toml"
```
