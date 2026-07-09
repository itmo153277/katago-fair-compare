#!/bin/bash

set -euxo pipefail

# Assuming ubuntu:jammy

apt-get -y -qq update
apt-get -y -qq full-upgrade
apt-get -y -qq install --no-install-recommends \
  ca-certificates \
  curl \
  git \
  build-essential \
  make \
  cmake \
  file \
  gettext \
  libssl-dev \
  zlib1g-dev \
  libbz2-dev \
  libgtk-3-dev \
  libcanberra-gtk3-module \
  glib-networking \
  gvfs \
  librsvg2-common

export PYENV_ROOT=/opt/pyenv
git clone -q https://github.com/pyenv/pyenv.git $PYENV_ROOT -b v2.7.3 --depth 1
export PATH=$PATH:$PYENV_ROOT/bin:$PYENV_ROOT/shims
pyenv install 3.14
pyenv global 3.14

export LINUXDEPLOY_ROOT=/opt/linuxdeploy
mkdir -p $LINUXDEPLOY_ROOT/bin
curl -fsSL https://github.com/linuxdeploy/linuxdeploy/releases/download/1-alpha-20251107-1/linuxdeploy-x86_64.AppImage > $LINUXDEPLOY_ROOT/bin/linuxdeploy-x86_64.AppImage
chmod +x $LINUXDEPLOY_ROOT/bin/linuxdeploy-x86_64.AppImage
curl -fsSL https://raw.githubusercontent.com/itmo153277/linuxdeploy-plugin-gtk/4d63222943ca8640078f83a547c3dcc03f47c345/linuxdeploy-plugin-gtk.sh > $LINUXDEPLOY_ROOT/bin/linuxdeploy-plugin-gtk.sh
chmod +x $LINUXDEPLOY_ROOT/bin/linuxdeploy-plugin-gtk.sh
cat > $LINUXDEPLOY_ROOT/bin/linuxdeploy << EOF
#!/bin/bash
exec $LINUXDEPLOY_ROOT/bin/linuxdeploy-x86_64.AppImage --appimage-extract-and-run "\$@"
EOF
chmod +x $LINUXDEPLOY_ROOT/bin/linuxdeploy
