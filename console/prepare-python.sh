#!/usr/bin/env bash
# prepare-python.sh — prepares console/python-embedded on macOS, the
# interpreter the app bundle ships as "python" in Contents/Resources.
# The Windows counterpart is prepare-python.ps1.
#
# Run ONCE before `npm run dist:mac`. The folder weighs ~250 MB and is in
# .gitignore: it is regenerated, never versioned.
#
#   bash console/prepare-python.sh            # the machine's own arch
#   bash console/prepare-python.sh x86_64     # or aarch64, for the other one
#
# python.org has no relocatable build for macOS: the installer writes into
# /Library. python-build-standalone (Astral) ships an "install_only" tarball
# that runs from wherever it is unpacked, which is what an app bundle needs.
set -euo pipefail

PBS_TAG="20261003"
PY_VER="3.12.15"
ARCH="${1:-$(uname -m)}"
case "$ARCH" in
  arm64|aarch64) ARCH="aarch64" ;;
  x86_64|amd64)  ARCH="x86_64" ;;
  *) echo "unknown arch: $ARCH (aarch64 or x86_64)" >&2; exit 1 ;;
esac

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/python-embedded"
REPO="$(cd "$HERE/.." && pwd)"
TARBALL="cpython-${PY_VER}+${PBS_TAG}-${ARCH}-apple-darwin-install_only.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${TARBALL}"
PY="$OUT/bin/python3"

# Never the user's site-packages: pip would see them, call the
# dependencies satisfied and leave the bundle without them.
export PYTHONNOUSERSITE=1

if [ -x "$PY" ] && [ "$(cat "$OUT/.arch" 2>/dev/null)" = "$ARCH" ]; then
  echo "[1/3] python-build-standalone $PY_VER ($ARCH) already present"
else
  echo "[1/3] downloading $TARBALL ..."
  rm -rf "$OUT"
  mkdir -p "$OUT"
  curl -fsSL "$URL" -o "$OUT/py.tar.gz"
  # the tarball unpacks as python/{bin,lib,...}: flatten into $OUT
  tar -xzf "$OUT/py.tar.gz" -C "$OUT" --strip-components=1
  rm "$OUT/py.tar.gz"
  echo "$ARCH" > "$OUT/.arch"
fi

# From the repo's source, not PyPI: the bundle carries the code and the
# dependencies OF THIS COMMIT, and the version metadata must match
# pyproject.toml. hatchling by hand and --no-build-isolation, as on Windows.
echo "[2/3] installing gigamail[all] from $REPO ..."
"$PY" -m pip install --quiet --upgrade pip hatchling
"$PY" -m pip install --quiet --no-build-isolation "$REPO[all]"

# Apple Silicon refuses native code without a signature, even an ad-hoc
# one. Wheels from PyPI are usually signed by their build tools, but not
# all of them: sign every shared object here so that the import check and
# the app do not die with "Killed: 9" on a library nobody signed.
# With a Developer ID in the keychain (CSC_NAME, set by the release
# workflow) the same files are signed with it, hardened runtime and
# timestamp included: notarization rejects any binary in the bundle that
# is not signed by the same Developer ID.
# macOS ships bash 3.2: with `set -u`, expanding an empty array is an
# error there, so the options are a plain string, split on purpose.
SIGN_ID="${CSC_NAME:--}"
SIGN_OPTS=""
if [ "$SIGN_ID" != "-" ]; then SIGN_OPTS="--timestamp --options runtime"; fi
echo "[3/3] signing native modules with identity '$SIGN_ID' ..."
# shellcheck disable=SC2086
find "$OUT" \( -name "*.so" -o -name "*.dylib" \) -type f -print0 \
  | xargs -0 -n 50 codesign --force --sign "$SIGN_ID" $SIGN_OPTS 2>/dev/null || true
for exe in "$OUT"/bin/python3.12 "$OUT"/bin/python3 "$OUT"/bin/python; do
  # shellcheck disable=SC2086
  [ -f "$exe" ] && [ ! -L "$exe" ] && codesign --force --sign "$SIGN_ID" $SIGN_OPTS "$exe" 2>/dev/null || true
done

"$PY" -c "import gigamail, fastapi, uvicorn, mcp; import importlib.metadata as m; print('  gigamail', m.version('gigamail'), '| mcp', m.version('mcp'), '| import OK')"
echo "Ready: now \"npm run dist:mac\" (add --x64 or --arm64 to match $ARCH)"
