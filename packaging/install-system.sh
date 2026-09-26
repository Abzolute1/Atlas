#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mkdir -p /opt/atlas
if [[ ! -x /opt/atlas/venv/bin/python ]]; then uv venv /opt/atlas/venv --python /usr/bin/python3.14; fi
uv pip install --python /opt/atlas/venv/bin/python --require-hashes -r dist/requirements.txt
atlas_version="$(/opt/atlas/venv/bin/python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
uv pip install --python /opt/atlas/venv/bin/python --no-deps --reinstall-package atlas-catalog "dist/atlas_catalog-${atlas_version}-py3-none-any.whl"
install -d /usr/local/bin /usr/share/applications /usr/share/icons/hicolor/scalable/apps /usr/share/pixmaps /usr/share/doc/atlas
ln -sfn /opt/atlas/venv/bin/atlas /usr/local/bin/atlas
ln -sfn /opt/atlas/venv/bin/atlas-desktop /usr/local/bin/atlas-desktop
install -m644 packaging/atlas.desktop /usr/share/applications/atlas.desktop
install -m644 scanatlas/assets/scanatlas.svg /usr/share/icons/hicolor/scalable/apps/atlas.svg
install -m644 scanatlas/assets/atlas-icon-v1.png /usr/share/pixmaps/atlas.png
/opt/atlas/venv/bin/python packaging/install-icons.py
install -m644 scanatlas/AGENT_GUIDE.md README.md LICENSE /usr/share/doc/atlas/
chmod -R a+rX /opt/atlas
if command -v update-desktop-database >/dev/null; then update-desktop-database /usr/share/applications; fi
if command -v gtk-update-icon-cache >/dev/null; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi
