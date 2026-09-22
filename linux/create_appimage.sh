#!/bin/bash

set -euxo pipefail

appdir=build/AppDir
cp resources/icon.png build/katago-fair-compare.png

mkdir -p $appdir/usr/bin
cp -R dist/katago-fair-compare $appdir
mv $appdir/katago-fair-compare/_internal $appdir/usr/lib
mv $appdir/katago-fair-compare/katago-fair-compare $appdir/usr/bin
rm -rf $appdir/katago-fair-compare
find $appdir/usr/lib -type f -exec chmod 0644 {} \;
ln -s ../lib $appdir/usr/bin/_internal
mv $appdir/usr/lib/wx/libwx* $appdir/usr/lib
for file in $appdir/usr/lib/*.so* ; do
patchelf --set-rpath '$ORIGIN' $file
done
for file in $appdir/usr/lib/wx/*.so* ; do
patchelf --set-rpath '$ORIGIN/..' $file
done
for file in $appdir/usr/lib/python3*/lib-dynload/*.so* ; do
patchelf --set-rpath '$ORIGIN/../..' $file
done

DEPLOY_GTK_VERSION=3 \
LDAI_OUTPUT=dist/katago-fair-compare.AppImage \
linuxdeploy --plugin gtk -i build/katago-fair-compare.png -d linux/katago-fair-compare.desktop --output appimage --appdir $appdir
