"""Native controls handle stale selections and failed connections safely."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from sentinel.desktop import Window


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Window, 'poll', lambda self: None)
    win = Window('x' * 32)
    win.timer.stop()
    yield win
    win.quit()
    win.deleteLater()
    app.processEvents()


def state(*ids):
    return {'runs': [], 'actions': [dict(id=i, tool='delete_file', status='waiting_for_human',
             args_json='{"path":"draft.txt"}', decisions=[]) for i in ids]}


def test_selected_action_tracks_id_not_row(window):
    window.completed('state', state(2, 1))
    window.table.selectRow(1)
    window.completed('state', state(3, 2, 1))
    assert window.selected()['id'] == 1
    window.completed('state', state(3, 2))
    assert window.selected() is None
    assert not window.approve.isEnabled()


def test_disconnect_disables_approval(window):
    window.completed('state', state(1))
    window.table.selectRow(0)
    assert window.approve.isEnabled()
    window.completed('state', RuntimeError('offline'))
    assert not window.approve.isEnabled()
    assert not window.deny.isEnabled()


def test_filters_keep_approval_tied_to_visible_action(window):
    data = state(2, 1)
    data['actions'][0]['status'] = 'executed'
    window.completed('state', data)
    window.review_waiting()
    assert window.table.rowCount() == 1
    assert window.selected()['id'] == 1
    assert window.approve.isEnabled()
    window.search.setText('nothing matches')
    assert window.selected() is None
    assert not window.approve.isEnabled()


def test_details_plain_english_by_default(window):
    window.completed('state', state(1))
    window.table.selectRow(0)
    assert 'Delete a file' in window.details.toPlainText()
    assert 'File or folder: draft.txt' in window.details.toPlainText()
    assert 'args_json' not in window.details.toPlainText()
    window.technical.setChecked(True)
    assert 'args_json' in window.details.toPlainText()
