from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.gui.table_models import PaginatedDuplicatesModel


_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _rows(groups, size):
    rows = []
    for g in range(groups):
        for i in range(size):
            rows.append({"path": f"/d/g{g}/f{i}", "name": f"f{i}", "location": f"/d/g{g}",
                         "size": 10 * (g + 1), "date": i, "hash": f"h{g}", "group_key": f"h{g}",
                         "is_original": i == 0})
    return rows


def test_pages_never_split_groups():
    _app()
    model = PaginatedDuplicatesModel(page_size=4)
    model.load_full_data(_rows(5, 3))  # 15 filas, grupos de 3
    seen = []
    while True:
        page = [model.get_row_data(r)["group_key"] for r in range(model.rowCount())]
        for key in set(page):
            assert page.count(key) == 3
        seen.extend(page)
        if not model.next_page():
            break
    assert len(seen) == 15
    assert model.get_page_info()["total_pages"] == 3


def test_checked_state_survives_pagination():
    _app()
    model = PaginatedDuplicatesModel(page_size=3)
    model.load_full_data(_rows(3, 3))
    model.setData(model.index(1, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    model.next_page()
    model.setData(model.index(2, 0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    model.previous_page()
    assert model.data(model.index(1, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.get_checked_paths() == ["/d/g0/f1", "/d/g1/f2"]
    model.check_all_duplicates()
    assert len(model.get_checked_paths()) == 6  # todas las copias, no los originales


def test_sort_keeps_groups_and_remove_paths():
    _app()
    model = PaginatedDuplicatesModel(page_size=100)
    model.load_full_data(_rows(3, 2))
    model.sort(3, Qt.SortOrder.DescendingOrder)
    keys = [model.get_row_data(r)["group_key"] for r in range(model.rowCount())]
    assert keys == ["h2", "h2", "h1", "h1", "h0", "h0"]
    model.remove_paths(["/d/g1/f1"])
    keys = [model.get_row_data(r)["group_key"] for r in range(model.rowCount())]
    assert "h1" not in keys
