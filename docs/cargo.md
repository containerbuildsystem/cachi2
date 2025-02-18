# Cargo

<https://doc.rust-lang.org/cargo/>

## Prerequisites

To use Cachi2 with Cargo locally, ensure you have Cargo installed on your system.
The [recommended](https://www.rust-lang.org/tools/install) way to install Cargo
along with Rust toolchain is to use the `rustup` tool.

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Then, ensure that the **Cargo.toml** and **Cargo.lock** are in your project directory.

## Basic usage

Run the following commands in your terminal to pre-fetch your project's
dependencies specified in the **Cargo.lock**. It must be synchronized with the **Cargo.toml**
file. Otherwise, the command will fail.

```bash
cd path-to-your-rust-project
cachi2 fetch-deps cargo
```

The default output directory is `cachi2-output`. You can change it by passing
the `--output-dir` option for the `fetch-deps` command.

In addition, the command will update the `.cargo/config.toml` to use the vendored
dependencies. (If the file does not exist, it will be created). At this point,
the file contains a placeholder for the path to the vendored dependencies. Replace
the placeholder with the actual path to the vendored dependencies, you want to use
inside the container by running the following command:

```bash
cachi2 inject-files --for-output-dir /tmp/cachi2-output cachi2-output
```

_There are no environment variables that need to be set for the build phase._

## Hermetic build

After using the `fetch-deps`, and `inject-files` commands to set up the directory,
you can build your project hermetically. Here is an example of a Dockerfile with
basic instructions to build a Rust project:

```Dockerfile
FROM docker.io/library/rust:latest

WORKDIR /app

COPY Cargo.toml Cargo.lock .

...

RUN . /tmp/cachi2.env && cargo build --release
```

Assuming `cachi2-output` is in the same directory as the Dockerfile, build the
container image:

```bash
podman build . \
  --volume "$(realpath ./cachi2-output)":/tmp/cachi2-output:Z \
  --network none \
  --tag my-awesome-rust-app
```
