#!/usr/bin/env bash
# Build the macOS app and disk image: dist/PDFSoul-By-Billy-<version>-macOS-<arch>.dmg
#
# Needs: uv. Builds for the architecture of the Mac it runs on (Apple silicon → arm64,
# Intel → x86_64); CI builds arm64 (pikepdf has no Intel macOS wheels).
#
# Signing: set SIGN_IDENTITY to a "Developer ID Application: …" certificate to sign properly,
# and NOTARY_PROFILE to a `xcrun notarytool store-credentials` profile to notarize. Without
# them the app is ad-hoc signed and the recipient opens it once with right-click → Open.
#
# Usage:  packaging/build_mac.sh
set -euo pipefail

cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
ARCH=$(uname -m)
APP="dist/PDFSoul By Billy.app"
DMG="dist/PDFSoul-By-Billy-${VERSION}-macOS-${ARCH}.dmg"
echo "Building PDFSoul ${VERSION} for macOS ${ARCH}"

# 1. Freeze.
uv sync --group build
uv run pyinstaller packaging/pdfsoul.spec --noconfirm --clean --distpath dist --workpath build
rm -rf dist/PDFSoul  # the plain folder; the .app holds the same files

# 2. Smoke-test the frozen CLI, including a real conversion, before packaging it.
"$APP/Contents/MacOS/pdfsoul-cli" --version
SMOKE=$(mktemp -d)
printf '# Smoke test\n\nIt works.\n' > "$SMOKE/t.md"
"$APP/Contents/MacOS/pdfsoul-cli" to-pdf "$SMOKE/t.md" -o "$SMOKE/t.pdf"
"$APP/Contents/MacOS/pdfsoul-cli" convert "$SMOKE/t.pdf" --to docx -o "$SMOKE/t.docx"
rm -rf "$SMOKE"

# 3. Sign.
if [[ -n "${SIGN_IDENTITY:-}" ]]; then
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP"
else
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"

# 4. Disk image: the app, a shortcut to Applications, and first-run instructions.
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp packaging/mac_readme.txt "$STAGE/Read me first.txt"
rm -f "$DMG"
hdiutil create -volname "PDFSoul By Billy ${VERSION}" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

if [[ -n "${SIGN_IDENTITY:-}" ]]; then
  codesign --sign "$SIGN_IDENTITY" --timestamp "$DMG"
  if [[ -n "${NOTARY_PROFILE:-}" ]]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  fi
fi

SIZE=$(du -h "$DMG" | cut -f1)
echo "Done: $DMG ($SIZE)"
