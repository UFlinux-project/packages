#!/bin/sh
set -eu

# Some build images omit Rust or leave rustup's shims off PATH.
export PATH="${CARGO_HOME:-$HOME/.cargo}/bin:$PATH"
if ! command -v rustup >/dev/null 2>&1 || ! command -v cargo >/dev/null 2>&1; then
    export CARGO_HOME="$PWD/target/rust-bootstrap/cargo"
    export RUSTUP_HOME="$PWD/target/rust-bootstrap/rustup"
    export PATH="$CARGO_HOME/bin:$PATH"

    if [ ! -x "$CARGO_HOME/bin/rustup" ] || [ ! -x "$CARGO_HOME/bin/cargo" ]; then
        installer=$(mktemp)
        trap 'rm -f "$installer"' EXIT
        curl --proto '=https' --tlsv1.2 -fsSL --retry 3 https://sh.rustup.rs -o "$installer"
        sh "$installer" -y --no-modify-path --profile minimal --default-toolchain none
        rm -f "$installer"
        trap - EXIT
    fi
fi

# Refresh stable even when the build image already has a cached toolchain.
rustup update stable --no-self-update
# Cargo's rustup shim selects the WASM target from rust-toolchain.toml.
cargo --version
exec wasm-pack build --release --target web --no-pack --no-typescript \
    --out-dir dist/assets/wasm --out-name packages --locked
