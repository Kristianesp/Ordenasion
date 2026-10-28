"""Tamaño en disco, hardlinks, extensiones, CSV y reanálisis incremental."""

import csv
import os
from types import SimpleNamespace

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.core import space_usage as engine
from src.gui.v2.pages.space_usage_page import LIST_EXTENSIONS, SpaceUsagePage
from src.utils.app_config import AppConfig

APP = None


def application():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def tree(tmp_path):
    (tmp_path / "fotos").mkdir()
    (tmp_path / "fotos" / "a.JPG").write_bytes(b"a" * 5000)
    (tmp_path / "fotos" / "b.jpg").write_bytes(b"b" * 3000)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "nota.txt").write_bytes(b"n" * 100)
    (tmp_path / "LEEME").write_bytes(b"x" * 10)
    return tmp_path


def test_compact_nodes_reconstruct_paths_and_csr_children(tmp_path):
    result = engine.scan_space(str(tree(tmp_path)))
    fotos = next(node for node in result.nodes if node.name == "fotos")
    assert fotos.path == os.path.join(str(tmp_path), "fotos")
    assert [result.nodes[i].name for i in result.children[fotos.id]] == ["a.JPG", "b.jpg"]
    leeme = result.find(os.path.join(str(tmp_path), "LEEME"))
    assert result.children.get(leeme, ()) == () and result.children.get(10 ** 6, ()) == ()
    assert result.find(os.path.join(str(tmp_path), "docs", "nota.txt")) is not None
    assert result.find(str(tmp_path)) == 0 and result.find("/otra/ruta") is None
    assert not hasattr(result.nodes[1], "__dict__")  # vistas ligeras, sin ruta almacenada


def test_size_on_disk_uses_blocks_and_extension_breakdown(tmp_path):
    result = engine.scan_space(str(tree(tmp_path)))
    root = result.nodes[0]
    assert root.size == 8110
    assert result.measured_disk
    if os.name == "posix":
        expected = sum(os.lstat(os.path.join(dirpath, name)).st_blocks * 512
                       for dirpath, _, names in os.walk(tmp_path) for name in names)
        assert root.disk_size == expected
    extensions = {ext: values for ext, *values in [(e, c, l, d) for e, c, l, d in result.sorted_extensions()]}
    assert extensions[".jpg"][:2] == [2, 8000]
    assert engine.NO_EXTENSION in extensions
    no_disk = engine.scan_space(str(tmp_path), measure_disk=False)
    assert no_disk.nodes[0].disk_size == no_disk.nodes[0].size and not no_disk.measured_disk


@pytest.mark.skipif(not hasattr(os, "link"), reason="sin hardlinks")
def test_hardlinks_counted_once_on_disk(tmp_path):
    # En Windows sólo se buscan hardlinks a partir de 1 MiB (requiere un os.stat extra)
    size = 2 * 1024 * 1024
    (tmp_path / "grande.bin").write_bytes(b"z" * size)
    try:
        os.link(tmp_path / "grande.bin", tmp_path / "copia.bin")
    except OSError:
        pytest.skip("el sistema de archivos no admite hardlinks")
    result = engine.scan_space(str(tmp_path))
    assert result.nodes[0].size == 2 * size  # lógico: por ruta
    assert result.hardlinks_deduped == 1
    files = [node for node in result.nodes if node.kind == "file"]
    assert sorted(node.disk_size == 0 for node in files) == [False, True]
    assert engine.scan_space(str(tmp_path), dedupe_hardlinks=False).hardlinks_deduped == 0


def test_windows_compressed_and_cluster_rounding(monkeypatch, tmp_path):
    monkeypatch.setattr(engine.sys, "platform", "win32")
    monkeypatch.setattr(engine, "_win_cluster_size", lambda root: 4096)
    monkeypatch.setattr(engine, "_win_compressed_size", lambda path: 1234)
    meter = engine._DiskMeter(str(tmp_path), measure=True, dedupe=False)
    plain = SimpleNamespace(st_size=5000, st_file_attributes=0)
    compressed = SimpleNamespace(st_size=5000, st_file_attributes=0x800)
    cloud = SimpleNamespace(st_size=5000, st_file_attributes=0x400000)
    entry = SimpleNamespace(path=str(tmp_path / "x"))
    assert meter.measure_file(entry, plain) == (8192, 0)
    assert meter.measure_file(entry, compressed) == (1234, 0)
    assert meter.measure_file(entry, cloud) == (1234, 0)


def test_csv_export(tmp_path):
    (tmp_path / "src").mkdir()
    source = tree(tmp_path / "src")
    result = engine.scan_space(str(source))
    destination = tmp_path / "out.csv"
    rows = engine.export_csv(result, str(destination))
    with open(destination, encoding="utf-8-sig", newline="") as handle:
        content = list(csv.reader(handle, delimiter=";"))
    assert rows == len(result.nodes) == len(content) - 1
    assert content[0][0] == "Ruta" and content[1][0] == str(source)
    assert any(row[2] == ".jpg" for row in content[1:])
    ext_rows = engine.export_extensions_csv(result, str(tmp_path / "ext.csv"))
    assert ext_rows == len(result.extensions)


def test_incremental_rescan_of_subfolder(tmp_path):
    root = tree(tmp_path)
    result = engine.scan_space(str(root))
    docs = result.find(str(root / "docs"))
    fotos = result.find(str(root / "fotos"))
    (root / "docs" / "nuevo.pdf").write_bytes(b"p" * 900)
    (root / "fotos" / "c.jpg").write_bytes(b"c" * 50)  # fuera del reanálisis: no debe contarse
    updated = engine.rescan_subtree(result, docs)
    assert updated.find(str(root / "docs")) == docs  # el nodo conserva su id
    assert updated.nodes[docs].size == 1000
    assert updated.nodes[0].size == result.nodes[0].size + 900
    assert updated.nodes[updated.find(str(root / "fotos"))].size == result.nodes[fotos].size
    assert updated.file_count == result.file_count + 1
    assert updated.extensions[".pdf"][:2] == (1, 900)
    for node in updated.nodes[1:]:
        assert node.parent_id < node.id
    with pytest.raises(engine.SpaceScanError):
        engine.rescan_subtree(result, result.find(str(root / "LEEME")))


def test_page_extensions_export_rescan_and_organize(tmp_path):
    application()
    (tmp_path / "datos").mkdir()
    root = tree(tmp_path / "datos")
    page = SpaceUsagePage(AppConfig(str(tmp_path / "config.json")))
    page.resize(1100, 900)
    result = engine.scan_space(str(root))
    page._completed(0, result)
    assert "en disco" in page.metric_labels[0].text()
    assert page.model.columnCount() == 5
    folder = result.find(str(root / "fotos"))
    page.select_node(folder)
    assert page.model.row_index[folder] == page.table.currentIndex().row()
    requested = []
    page.organize_requested.connect(requested.append)
    page.organize_button.click()
    assert requested == [str(root / "fotos")]
    page.select_node(result.find(str(root / "LEEME")))
    page.organize_button.click()
    assert requested[-1] == str(root)  # archivo → carpeta actual

    page.list_mode.setCurrentIndex(LIST_EXTENSIONS)
    assert page.model.extension_mode and page.model.rowCount() == len(result.extensions)
    assert page.model.data(page.model.index(0, 0)) == ".jpg"
    assert page.export_csv(str(tmp_path / "ext.csv"))
    for _ in range(100):
        QTest.qWait(10)
        if "Exportadas" in page.status_label.text():
            break
    assert "Exportadas" in page.status_label.text() and (tmp_path / "ext.csv").exists()

    page.list_mode.setCurrentIndex(0)
    page.navigate_to(folder)
    (root / "fotos" / "nueva.png").write_bytes(b"q" * 70)
    assert page.rescan_folder()
    for _ in range(200):
        QTest.qWait(10)
        if page._worker is None:
            break
    assert page._worker is None and page.result is not result
    assert page.current_id == page.result.find(str(root / "fotos"))
    assert page.result.nodes[0].size == result.nodes[0].size + 70
    assert "Carpeta actualizada" in page.status_label.text()
    page.close()
