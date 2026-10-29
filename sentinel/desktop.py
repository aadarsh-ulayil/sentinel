"""Native Qt control window and tray, shared by macOS and Windows."""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
import httpx
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QPolygon
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QFileDialog,
    QPlainTextEdit, QMessageBox, QSystemTrayIcon, QMenu, QHeaderView,
    QLineEdit, QComboBox, QCheckBox, QSplitter)
from .paths import DATA
from dotenv import load_dotenv


class Bridge(QObject):
    done = Signal(object, object)


def shield_icon():
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor('#68dca9'))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawPolygon(QPolygon([QPoint(32, 4), QPoint(56, 14), QPoint(52, 40),
                                  QPoint(32, 60), QPoint(12, 40), QPoint(8, 14)]))
    painter.end()
    return QIcon(pix)


TOOL_NAMES = {'list_files': 'Look at files', 'read_file': 'Read a file',
              'write_file': 'Save a file', 'delete_file': 'Delete a file',
              'run_command': 'Run a command', 'fetch_url': 'Visit a website',
              'send_message': 'Send a message', 'spend_money': 'Make a payment'}
STATUS_NAMES = {'executed': 'Completed', 'blocked': 'Blocked by a rule',
                'denied': 'Not approved', 'failed': 'Could not complete',
                'waiting_for_human': 'Needs your approval', 'checking': 'Checking safety',
                'executing': 'In progress'}


def action_text(action):
    return TOOL_NAMES.get(action['tool'], action['tool'].replace('_', ' ').capitalize())


def readable_details(action):
    try:
        args = json.loads(action.get('args_json', '{}'))
    except (ValueError, TypeError):
        args = {'Details': action.get('args_json', '')}
    labels = {'path': 'File or folder', 'url': 'Website', 'command': 'Command',
              'recipient': 'Recipient', 'message': 'Message', 'content': 'File contents',
              'amount_inr': 'Amount (INR)', 'payee': 'Payee'}
    lines = [action_text(action), STATUS_NAMES.get(action['status'], action['status']), '']
    lines += [f'{labels.get(k, k.replace("_", " ").capitalize())}: {v}' for k, v in args.items()]
    decisions = action.get('decisions', [])
    if decisions:
        lines += ['', 'Why this happened', decisions[-1].get('reason', 'No explanation available.')]
    if action['status'] == 'waiting_for_human':
        lines += ['', 'Your decision is needed', 'This action is paused. Deny it if you are unsure. No reply within 60 seconds means it is denied.']
    else:
        lines += ['', 'No decision is needed for this action.']
    lines += ['', 'File contents and messages above are untrusted agent data.']
    return '\n'.join(lines)


class Window(QMainWindow):
    def __init__(self, token):
        super().__init__()
        self.setWindowTitle('SENTINEL')
        self.resize(1180, 800)
        self.setMinimumSize(900, 650)
        self.token = token
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.bridge = Bridge()
        self.bridge.done.connect(self.completed)
        self.busy = False
        self.state = {'runs': [], 'actions': []}
        self.seen = set()
        self.first = True
        self.quitting = False
        self.gateway = None
        self.connected = False
        self.visible_actions = []
        layout = QVBoxLayout()
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        heading = QLabel('Overview')
        heading.setObjectName('heading')
        layout.addWidget(heading)
        intro = QLabel('See what your AI is doing. Stop risky actions. Decide when it needs permission.')
        intro.setObjectName('muted')
        layout.addWidget(intro)
        self.status = QLabel('Connecting to your safety service…')
        self.status.setObjectName('banner')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        cards = QHBoxLayout()
        self.counts = []
        for title in ['NEEDS YOUR APPROVAL', 'BLOCKED OR DENIED', 'COMPLETED']:
            card = QLabel('0\n' + title)
            card.setObjectName('card')
            card.setProperty('tone', ['lavender', 'cream', 'mint'][len(self.counts)])
            card.setMinimumHeight(80)
            cards.addWidget(card)
            self.counts.append(card)
        layout.addLayout(cards)
        controls = QHBoxLayout()
        self.start_button = QPushButton('Connect protection')
        self.start_button.setToolTip('Start the local safety service if it is not already running.')
        self.start_button.clicked.connect(self.start_gateway)
        self.stop_button = QPushButton('Stop all AI tasks')
        self.stop_button.setObjectName('danger')
        self.stop_button.setToolTip('Prevent further actions in all currently running tasks. Completed actions cannot be undone.')
        self.stop_button.clicked.connect(self.kill_runs)
        review = QPushButton('Review waiting actions')
        review.setObjectName('primary')
        review.clicked.connect(self.review_waiting)
        controls.addWidget(review)
        controls.addWidget(self.start_button)
        controls.addStretch()
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search actions, files, websites, or reasons…')
        self.search.textChanged.connect(self.render_actions)
        self.filter = QComboBox()
        self.filter.addItems(['All activity', 'Needs approval', 'Blocked / denied', 'Completed'])
        self.filter.currentIndexChanged.connect(self.render_actions)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.filter)
        layout.addLayout(filters)
        self.empty = QLabel('No activity yet. Connect an AI agent to SENTINEL; its actions will appear here.')
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['#', 'AI wants to…', 'Result', 'Explanation'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        splitter.addWidget(self.table)
        detail_panel = QWidget()
        detail_panel.setObjectName('detailPanel')
        detail_layout = QVBoxLayout(detail_panel)
        detail_title = QLabel('Action details')
        detail_title.setObjectName('detailTitle')
        detail_layout.addWidget(detail_title)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('Click an action on the left to see what it affects, why it was stopped, and whether you need to decide.')
        detail_layout.addWidget(self.details)
        self.technical = QCheckBox('Show technical record')
        self.technical.toggled.connect(self.show_details)
        detail_layout.addWidget(self.technical)
        answers = QHBoxLayout()
        self.deny = QPushButton('Deny action')
        self.approve = QPushButton('Approve once…')
        self.deny.clicked.connect(lambda: self.answer(False))
        self.approve.clicked.connect(lambda: self.answer(True))
        answers.addWidget(self.deny)
        answers.addWidget(self.approve)
        self.deny.setObjectName('danger')
        self.approve.setObjectName('primary')
        detail_layout.addLayout(answers)
        splitter.addWidget(detail_panel)
        splitter.setSizes([680, 380])
        layout.addWidget(splitter, 1)
        footer = QHBoxLayout()
        scope = QLabel('Protects connected agents only · Closing this window keeps the tray icon available.')
        scope.setObjectName('muted')
        scope.setWordWrap(True)
        footer.addWidget(scope, 1)
        hide_button = QPushButton('Keep in background')
        hide_button.clicked.connect(self.hide)
        footer.addWidget(hide_button)
        layout.addLayout(footer)
        body = QWidget()
        body.setLayout(layout)
        body.setObjectName('workspace')
        shell = QWidget()
        shell.setObjectName('shell')
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(12, 12, 12, 12)
        shell_layout.setSpacing(12)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(112)
        rail = QVBoxLayout(sidebar)
        rail.setContentsMargins(0, 12, 0, 12)
        rail.setSpacing(14)
        brand = QLabel('S')
        brand.setObjectName('brand')
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setFixedSize(54, 54)
        rail.addWidget(brand, 0, Qt.AlignmentFlag.AlignHCenter)
        name = QLabel('SENTINEL')
        name.setObjectName('railName')
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rail.addWidget(name)
        rail.addSpacing(24)
        self.nav_buttons = []
        for title, index in [('Overview', 0), ('Approvals', 1), ('Blocked', 2), ('Completed', 3)]:
            button = QPushButton(title)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, i=index: self.navigate(i))
            rail.addWidget(button)
            self.nav_buttons.append(button)
        rail.addStretch()
        quit_button = QPushButton('Quit app')
        quit_button.setObjectName('nav')
        quit_button.clicked.connect(self.quit)
        rail.addWidget(quit_button)
        self.filter.currentIndexChanged.connect(self.sync_navigation)
        shell_layout.addWidget(sidebar)
        shell_layout.addWidget(body, 1)
        self.setCentralWidget(shell)
        self.setStyleSheet("""
            QWidget { background: transparent; color: #202322; font-size: 14px; }
            QWidget#shell, QWidget#sidebar { background: #232423; }
            QWidget#workspace { background: #ffffff; border-radius: 24px; }
            QLabel#heading { font-size: 28px; font-weight: 700; color: #171918; }
            QLabel#muted { color: #626c70; font-size: 12px; }
            QLabel#brand { background: #f5f0d8; color: #242724; border-radius: 16px; font-size: 28px; font-weight: 800; }
            QLabel#railName { color: #e4e5df; font-size: 11px; font-weight: 700; }
            QPushButton#nav { background: transparent; color: #c4cbc6; border: none; padding: 12px 4px; font-size: 12px; }
            QPushButton#nav:hover { background: #363a36; color: #ffffff; }
            QPushButton#nav:checked { background: #f3efd9; color: #222622; font-weight: 600; }
            QLabel#banner { background: #e4f1fc; color: #264960; padding: 16px; border-radius: 14px; font-size: 15px; }
            QLabel#card { border: none; border-radius: 16px; padding: 20px; font-size: 16px; font-weight: 600; }
            QLabel#card[tone="lavender"] { background: #e7dff1; }
            QLabel#card[tone="cream"] { background: #f6f0d9; }
            QLabel#card[tone="mint"] { background: #dceedd; }
            QPushButton { padding: 11px 14px; background: #f6f7f6; color: #303933; border: 1px solid #e0e5e1; border-radius: 12px; }
            QPushButton:hover { background: #e8efeb; border-color: #b5c6bc; }
            QPushButton#primary { background: #222623; color: #ffffff; border-color: #222623; font-weight: 600; }
            QPushButton#primary:hover { background: #404b44; }
            QPushButton#danger { color: #8e3d40; border-color: #e5cdd0; background: #fff9f9; }
            QPushButton:disabled, QPushButton#primary:disabled, QPushButton#danger:disabled { background: #f0f2f0; color: #7b837e; border-color: #e4e7e4; }
            QLineEdit, QComboBox { padding: 11px; border: 1px solid #e0e5e1; border-radius: 12px; background: #fafbfa; color: #252c28; }
            QLineEdit:focus, QComboBox:focus { border-color: #88abbf; }
            QComboBox QAbstractItemView { background: #ffffff; color: #252c28; selection-background-color: #e4f1fc; selection-color: #202322; }
            QTableWidget { background: #ffffff; alternate-background-color: #fafcfb; border: none; selection-background-color: #e4f1fc; selection-color: #202322; }
            QTableWidget::item { padding: 8px; border-bottom: 1px solid #edf0ee; }
            QHeaderView::section { padding: 12px 6px; background: #ffffff; color: #697573; border: none; font-weight: 500; }
            QWidget#detailPanel { background: #252725; border-radius: 18px; }
            QLabel#detailTitle { color: #ffffff; font-size: 20px; font-weight: 600; padding: 12px; }
            QPlainTextEdit { background: #252725; color: #edf2ee; border: none; padding: 12px; font-size: 15px; selection-background-color: #4b6256; }
            QSplitter::handle { background: #ffffff; width: 16px; }
            QCheckBox { color: #d9e2db; padding: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #a5b3a9; border-radius: 4px; background: #ffffff; }
            QCheckBox::indicator:checked { background: #9bc7ac; }
            QScrollBar:vertical { background: #f0f3f1; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #b9c5be; min-height: 24px; border-radius: 4px; }
            QMenu { background: #ffffff; color: #202322; }
            QMenu::item:selected { background: #e4f1fc; }
            QMessageBox { background: #ffffff; }
        """)
        icon = shield_icon()
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip('SENTINEL')
        menu = QMenu()
        for title, callback in [('Open SENTINEL', self.reveal), ('Stop active runs', self.kill_runs), ('Quit SENTINEL', self.quit)]:
            action = QAction(title, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.reveal() if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.messageClicked.connect(self.reveal)
        self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1500)
        self.show_details()
        self.poll()

    def navigate(self, index):
        self.search.clear()
        self.filter.setCurrentIndex(index)
        if index == 1 and self.table.rowCount():
            self.table.selectRow(0)

    def sync_navigation(self, index):
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def request(self, path, body=None):
        with httpx.Client(base_url='http://127.0.0.1:8000', timeout=5,
                          headers={'Authorization': 'Bearer ' + self.token}) as client:
            response = client.get(path) if body is None else client.post(path, json=body)
            response.raise_for_status()
            return response.json()

    def submit(self, label, fn):
        def work():
            try:
                result = fn()
            except Exception as error:
                result = error
            self.bridge.done.emit(label, result)
        self.pool.submit(work)

    def poll(self):
        if not self.busy:
            self.busy = True
            self.submit('state', lambda: self.request('/api/state'))

    def completed(self, label, result):
        if label == 'state':
            self.busy = False
        if isinstance(result, Exception):
            if label == 'state':
                self.connected = False
                self.status.setText('Not connected · SENTINEL cannot check actions right now. Click Connect protection to start.')
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.approve.setEnabled(False)
                self.deny.setEnabled(False)
            else:
                QMessageBox.warning(self, 'Request failed', 'The request could not be completed. The action may have expired or the gateway is unavailable.')
            return
        if label != 'state':
            self.poll()
            return
        self.connected = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(any(r['status'] == 'running' for r in result['runs']))
        selected = self.selected()
        selected_id = selected.get('id') if selected else None
        self.state = result
        actions = result['actions']
        waiting = sum(a['status'] == 'waiting_for_human' for a in actions)
        self.status.setText(f'Connected · {waiting} action(s) need your decision.' if waiting else 'Connected · No decisions needed. SENTINEL is ready to check connected AI actions.')
        for card, count, title in zip(self.counts,
                [waiting, sum(a['status'] in ('blocked', 'denied', 'failed') for a in actions), sum(a['status'] == 'executed' for a in actions)],
                ['NEEDS YOUR APPROVAL', 'BLOCKED OR DENIED', 'COMPLETED']):
            card.setText(f'{count}\n{title} · recent activity')
        for action in actions:
            key = (action['id'], action['status'])
            if key not in self.seen and (action['status'] == 'waiting_for_human' or
                    (not self.first and action['status'] in ('blocked', 'failed'))):
                self.tray.showMessage('SENTINEL', f'{action_text(action)}: {STATUS_NAMES.get(action["status"], action["status"])}. Open SENTINEL to review.')
            self.seen.add(key)
        self.first = False
        self.render_actions(selected_id=selected_id)

    def review_waiting(self):
        self.search.clear()
        self.filter.setCurrentIndex(1)
        if self.table.rowCount():
            self.table.selectRow(0)

    def render_actions(self, *_args, selected_id=None):
        if selected_id is None:
            current = self.selected()
            selected_id = current['id'] if current else None
        groups = [None, {'waiting_for_human'}, {'blocked', 'denied', 'failed'}, {'executed'}]
        statuses = groups[self.filter.currentIndex()]
        query = self.search.text().casefold()
        self.visible_actions = [a for a in self.state['actions']
            if (statuses is None or a['status'] in statuses)
            and query in (action_text(a) + ' ' + json.dumps(a)).casefold()]
        self.table.blockSignals(True)
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(self.visible_actions))
        self.empty.setVisible(not self.visible_actions)
        self.empty.setText('No actions match this view. Try All activity or clear your search.' if self.state['actions'] else
                           'No activity yet. Connect an AI agent to SENTINEL; its actions will appear here.')
        for row, action in enumerate(self.visible_actions):
            decisions = action.get('decisions', [])
            reason = decisions[-1].get('reason', '') if decisions else 'Safety check in progress'
            for col, value in enumerate([action['id'], action_text(action), STATUS_NAMES.get(action['status'], action['status']), reason]):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if col == 2:
                    color = '#8a5b00' if action['status'] == 'waiting_for_human' else '#a3424c' if action['status'] in ('blocked', 'denied', 'failed') else '#287259'
                    item.setForeground(QColor(color))
                self.table.setItem(row, col, item)
            if action['id'] == selected_id:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.show_details()

    def selected(self):
        row = self.table.currentRow()
        actions = self.visible_actions
        return actions[row] if 0 <= row < len(actions) else None

    def show_details(self):
        action = self.selected()
        text = (json.dumps(action, indent=2) if self.technical.isChecked() else readable_details(action)) if action else ''
        if self.details.toPlainText() != text:
            self.details.setPlainText(text)
        waiting = bool(self.connected and action and action['status'] == 'waiting_for_human')
        self.approve.setEnabled(waiting)
        self.deny.setEnabled(waiting)

    def answer(self, approve):
        action = self.selected()
        if not action or action['status'] != 'waiting_for_human':
            return
        if approve:
            dialog = QMessageBox(self)
            dialog.setWindowTitle('Approve this action?')
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(readable_details(action))
            dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            dialog.setDefaultButton(QMessageBox.StandardButton.No)
            if dialog.exec() != QMessageBox.StandardButton.Yes:
                return
        aid = action['id']
        self.submit('answer', lambda: self.request(f'/api/actions/{aid}/answer', {'approve': approve}))

    def kill_runs(self):
        ids = [r['id'] for r in self.state['runs'] if r['status'] == 'running']
        self.submit('kill', lambda: [self.request(f'/api/runs/{rid}/kill', {}) for rid in ids])

    def start_gateway(self):
        if self.gateway is not None and self.gateway.is_alive():
            return
        from .desktop_runtime import Gateway
        self.gateway = Gateway()
        self.gateway.start()

    def closeEvent(self, event):
        if not self.quitting and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
        else:
            self.quit()
            event.accept()

    def quit(self):
        self.timer.stop()
        if self.gateway:
            self.gateway.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.quitting = True
        self.tray.hide()
        QApplication.instance().quit()


def main():
    load_dotenv(DATA / '.env')
    app = QApplication(sys.argv)
    app.setApplicationName('SENTINEL')
    token = os.getenv('SENTINEL_TOKEN', '')
    if len(token) < 24:
        filename, _ = QFileDialog.getOpenFileName(None, 'Choose your existing SENTINEL .env configuration', str(DATA), 'All files (*)')
        if not filename:
            return 1
        from pathlib import Path
        from . import paths
        paths.DATA = Path(filename).resolve().parent
        load_dotenv(filename, override=True)
        token = os.getenv('SENTINEL_TOKEN', '')
        if len(token) < 24:
            QMessageBox.warning(None, 'SENTINEL setup', 'This file needs SENTINEL_TOKEN and a distinct SENTINEL_AGENT_TOKEN.')
            return 1
    window = Window(token)
    app.aboutToQuit.connect(lambda: window.gateway.stop() if window.gateway and window.gateway.is_alive() else None)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
