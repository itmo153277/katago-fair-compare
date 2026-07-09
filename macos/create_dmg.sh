#!/bin/bash

dmg_dir=build/dmg

mkdir -p $dmg_dir
cp -R dist/*.app $dmg_dir
ln -s /Applications $dmg_dir/Applications
hdiutil create -volname "KataGo Fair Compare" -srcfolder $dmg_dir -ov -format UDZO dist/katago-fair-compare.dmg
