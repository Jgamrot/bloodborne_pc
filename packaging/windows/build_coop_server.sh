#!/usr/bin/env bash
# Builds out/coop-server/: the shadNet server seamless co-op hosts run (launcher/bbport_coop.py),
# with the DLLs and Qt plugins it needs. Run from an MSYS2 CLANG64 shell; needs the packages
# mingw-w64-clang-x86_64-{qt6-base,qt6-httpserver,qt6-websockets,protobuf}.
#
# It is Wozzardman's shadnet-p2p (GPL-2.0-or-later, the server BBSC ships) at the commit below,
# plus packaging/windows/shadnet-p2p/*.patch: its STUN server also answers the PS4 P2P framing
# that shadPS4 0.20's network code (this port since 1.9.5) sends, which BBSC's build drops.
set -euo pipefail
cd -- "$(dirname -- "$0")/../.."
REPO=https://github.com/Wozzardman/shadnet-p2p.git
COMMIT=5a849a192fd4450593c57b10697316ac324c856e
src=out/shadnet-p2p
dest=out/coop-server

if [[ ! -d $src/.git ]]; then
    git clone --quiet "$REPO" "$src"
fi
git -C "$src" fetch --quiet origin "$COMMIT" 2>/dev/null || true
git -C "$src" checkout --quiet --force "$COMMIT"
git -C "$src" clean -fdq
for patch in packaging/windows/shadnet-p2p/*.patch; do
    git -C "$src" apply --whitespace=nowarn "$PWD/$patch"
done

cmake -S "$src" -B "$src/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DSHADNET_SYSTEM_PROTOBUF=ON \
    -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ >/dev/null
ninja -C "$src/build" shadnet >/dev/null

rm -rf -- "$dest"
mkdir -p "$dest/sqldrivers" "$dest/networkinformation"
cp "$src/build/shadnet.exe" "$dest/"
cp /clang64/share/qt6/plugins/sqldrivers/qsqlite.dll "$dest/sqldrivers/"
cp /clang64/share/qt6/plugins/networkinformation/qnetworklistmanager.dll "$dest/networkinformation/"
# Every CLANG64 DLL the server and its plugins load.
ldd "$dest/shadnet.exe" "$dest/sqldrivers/qsqlite.dll" "$dest/networkinformation/qnetworklistmanager.dll" |
    awk '/\/clang64\/bin\// {print $3}' | sort -u | while read -r dll; do
        cp -u "$dll" "$dest/"
    done
cp "$src/LICENSES/GPL-2.0-or-later.txt" "$dest/LICENSE.txt"
cat > "$dest/SOURCE.txt" <<EOF
shadnet.exe: shadnet-p2p by Wozzardman (GPL-2.0-or-later)
  $REPO at $COMMIT
with this port's patches from packaging/windows/shadnet-p2p/ in
  https://github.com/Jgamrot/yharnam-pc
built by packaging/windows/build_coop_server.sh. The DLLs are MSYS2 CLANG64's (Qt 6, protobuf,
Abseil, ICU and others), each under its own licence.
EOF
echo "Built $dest ($(du -sh "$dest" | cut -f1))"
