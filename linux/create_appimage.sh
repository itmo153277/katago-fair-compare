#!/bin/bash

set -euxo pipefail

appdir=build/AppDir
cp resources/icon.png build/katago-fair-compare.png

mkdir -p $appdir/usr/bin
cp -R dist/katago-fair-compare $appdir
mv $appdir/katago-fair-compare/_internal $appdir/usr/lib
ln -s ../../katago-fair-compare/katago-fair-compare $appdir/usr/bin
ln -s ../usr/lib $appdir/katago-fair-compare/_internal

DEPLOY_GTK_VERSION=3 \
LDAI_OUTPUT=dist/katago-fair-compare.AppImage \
linuxdeploy --plugin gtk -i build/katago-fair-compare.png -d linux/katago-fair-compare.desktop --output appimage --appdir $appdir
