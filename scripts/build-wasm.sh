#!/usr/bin/env bash
# Rebuild the same patched parser used by the native application, on a standard runner.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
export RUSTUP_TOOLCHAIN=1.93.1
export CARGO_TARGET_DIR="$root/.work/target-wasm"
export CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
rustup toolchain install "$RUSTUP_TOOLCHAIN" --profile minimal --target wasm32-unknown-unknown
cargo test --manifest-path overlay/namespace-tests/Cargo.toml
node --experimental-strip-types --test tests/composition-final.test.mjs
python scripts/prepare_upstream.py --fetch-only
python e2e/check_namespaces.py .work/hop .work/hop/apps/studio-host/vendor/rhwp-core .work/namespace-red --red
corepack enable
(cd .work/hop && pnpm install --frozen-lockfile)
python scripts/font_test_contract.py .work/hop
python scripts/prepare_upstream.py --patch-only
python scripts/prepare_hwpx.py .work/hop
python scripts/patch_composition.py .work/hop
python scripts/patch_namespaces.py .work/hop/third_party/rhwp
mkdir -p .work/tooling
curl --fail --location --proto '=https' --tlsv1.2 https://github.com/wasm-bindgen/wasm-pack/releases/download/v0.14.0/wasm-pack-v0.14.0-x86_64-unknown-linux-musl.tar.gz -o .work/tooling/wasm-pack.tar.gz
printf '%s  %s\n' '278a8d668085821f4d1a637bd864f1713f872b0ae3a118c77562a308c0abfe8d' '.work/tooling/wasm-pack.tar.gz' | sha256sum --check
tar -xzf .work/tooling/wasm-pack.tar.gz -C .work/tooling
wasmpack="$root/.work/tooling/wasm-pack-v0.14.0-x86_64-unknown-linux-musl/wasm-pack"
"$wasmpack" build .work/hop/third_party/rhwp --target web --release --no-opt --out-dir "$root/.work/rebuilt-wasm" -- --locked
cp .work/hop/third_party/rhwp/LICENSE .work/rebuilt-wasm/LICENSE
python scripts/wasm_artifacts.py capture .work/rebuilt-wasm
python scripts/wasm_artifacts.py install .work/rebuilt-wasm .work/hop
python e2e/check_namespaces.py .work/hop .work/hop/apps/studio-host/vendor/rhwp-core .work/namespace-green
(cd .work/hop && pnpm run test:studio && pnpm run build:studio)
python scripts/buildkit.py frontend .work/hop/apps/studio-host/dist
node e2e/generate-browser-fixtures.mjs .work/hop .work/e2e-fixtures
