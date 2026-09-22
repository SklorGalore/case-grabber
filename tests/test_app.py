import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from case_viewer.app import EquipmentDiagram, MainWindow
from case_viewer.raw import Record, parse_text


def test_equipment_diagram_normalizes_psse_status_values():
    app = QApplication.instance() or QApplication([])
    diagram = EquipmentDiagram()
    online = Record("GENERATOR", 1, [], [["1", "1", "0", "0", "0", "0", "0", "1.00000"]],
                    [["I", "ID", "PG", "QG", "QT", "QB", "VS", "STAT"]])
    offline = Record("LOAD", 1, [], [["1", "1", "0.00000"]], [["I", "ID", "STAT"]])

    assert diagram._status(online) == ("IN SERVICE", True)
    assert diagram._status(offline) == ("OUT OF SERVICE", False)
    diagram.close()


def test_equipment_diagram_distinguishes_reactors_and_vector_connections():
    app = QApplication.instance() or QApplication([])
    diagram = EquipmentDiagram()
    reactor = Record("FIXED SHUNT", 1, [], [["1", "1", "0", "-25.0"]], [["I", "ID", "GL", "BL"]])
    capacitor = Record("FIXED SHUNT", 1, [], [["1", "1", "0", "25.0"]], [["I", "ID", "GL", "BL"]])
    transformer = Record(
        "TRANSFORMER", 1, [], [["1", "2", "0", "1", "Dyn1"]], [["I", "J", "K", "CKT", "VECGRP"]]
    )
    three_winding = Record(
        "TRANSFORMER", 1, [], [["1", "2", "3", "1", "YNyn0d11"]], [["I", "J", "K", "CKT", "VECGRP"]]
    )
    unspecified = Record(
        "TRANSFORMER", 1, [], [["1", "2", "0", "1", ""]], [["I", "J", "K", "CKT", "VECGRP"]]
    )

    assert diagram._is_shunt_reactor(reactor)
    assert not diagram._is_shunt_reactor(capacitor)
    assert diagram._vector_connections(transformer) == ([("D", False), ("Y", True)], 1)
    assert diagram._vector_connections(three_winding) == ([("Y", True), ("Y", True), ("D", False)], 11)
    assert diagram._vector_connections(unspecified) == ([], None)
    diagram.close()


def test_desktop_navigation_and_filter(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    case = parse_text("""0,100,35,0,0,60
0 / END OF SYSTEM-WIDE DATA, BEGIN BUS DATA
@!I,NAME,BASKV
1,'North',115
2,'South',230
0 / END OF BUS DATA, BEGIN BRANCH DATA
@!I,J,CKT,R,X,RATE1,STAT
1,2,'1',0.01,0.1,300,1
0 / END OF BRANCH DATA
Q
""")
    window = MainWindow()
    window._loaded(case)
    window.sections.setCurrentRow(2)
    assert window.section == "BUS"
    window.search.setText("South")
    assert window.proxy.rowCount() == 1
    export_path = tmp_path / "buses.csv"
    monkeypatch.setattr("case_viewer.app.QFileDialog.getSaveFileName", lambda *args: (str(export_path), "CSV files (*.csv)"))
    window.export_csv()
    assert "South" in export_path.read_text(encoding="utf-8-sig")
    assert "North" not in export_path.read_text(encoding="utf-8-sig")
    window.search.clear()
    window.sections.setCurrentRow(3)
    assert window.diagram.record.section == "BRANCH"
    window.go_to_bus("2")
    assert window.section == "BUS"
    assert window.diagram.record.identity == "2"
    window.copy_selection()
    assert "2" in app.clipboard().text()
    window.close()
