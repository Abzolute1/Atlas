"""Install raster launcher sizes from the original Atlas artwork."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

source = Path(__file__).resolve().parents[1] / 'scanatlas/assets/atlas-icon-v1.png'
image = QImage(str(source))
if image.isNull():
    raise SystemExit('Cannot read Atlas icon: ' + str(source))
for size in (16, 24, 32, 48, 64, 128, 256, 512):
    destination = Path('/usr/share/icons/hicolor') / f'{size}x{size}/apps/atlas.png'
    destination.parent.mkdir(parents=True, exist_ok=True)
    scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if not scaled.save(str(destination)):
        raise SystemExit('Cannot save Atlas icon: ' + str(destination))
    destination.chmod(0o644)
