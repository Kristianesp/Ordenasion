from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication

from src.core.image_similarity import dhash, find_similar_images, group_similar, hamming


_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _gradient(path, width, height, reverse=False, fmt="PNG"):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    for x in range(width):
        v = int(255 * x / max(1, width - 1))
        if reverse:
            v = 255 - v
        painter.setPen(QColor(v, v, v))
        painter.drawLine(x, 0, x, height)
    painter.end()
    assert image.save(str(path), fmt)
    return path


def test_dhash_groups_resized_copies_but_not_different_images(tmp_path):
    _app()
    a = _gradient(tmp_path / "a.png", 400, 300)
    b = _gradient(tmp_path / "b.jpg", 200, 150, fmt="JPG")  # misma imagen, otro tamaño/formato
    c = _gradient(tmp_path / "c.png", 400, 300, reverse=True)
    ha, hb, hc = dhash(a), dhash(b), dhash(c)
    assert hamming(ha, hb) <= 10
    assert hamming(ha, hc) > 10
    groups = group_similar([(a, ha), (b, hb), (c, hc)], threshold=10)
    assert len(groups) == 1 and set(groups[0]) == {a, b}


def test_find_similar_images_reports_meta(tmp_path):
    _app()
    _gradient(tmp_path / "x.png", 300, 200)
    _gradient(tmp_path / "y.png", 150, 100)
    (tmp_path / "rota.jpg").write_bytes(b"no es una imagen")
    groups, info, meta, errors = find_similar_images(str(tmp_path), threshold=8)
    assert len(groups) == 1
    key = next(iter(groups))
    assert meta[key].method == "similar" and not meta[key].confirmed
    assert any("rota.jpg" in path for path, _ in errors)
