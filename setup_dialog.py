# Adapted from PyForestScan for QGIS.
# Copyright (C) 2026 Nicholas Rogers and Joseph Percival.
# GPL-2.0-or-later; this adaptation is distributed under GPL-3.0-only.
"""A small first-use engine installer; all analysis stays in Processing."""

import math
import threading
from pathlib import Path

from qgis.PyQt.QtCore import QThread, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .runtime import manager
from .runtime.client import EngineCanceled


class _SetupThread(QThread):
    progress = pyqtSignal(float, str)
    succeeded = pyqtSignal()
    failed = pyqtSignal(str, bool)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.cancel_event = threading.Event()

    def run(self):
        try:
            self.operation(progress=self.progress.emit, cancel=self.cancel_event.is_set)
        except EngineCanceled as exc:
            self.failed.emit(str(exc), True)
        except Exception as exc:
            self.failed.emit(str(exc), False)
        else:
            self.succeeded.emit()


class SetupDialog(QDialog):
    completed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("OBIA Setup")
        self.setMinimumWidth(500)
        self._thread = None
        self._closing = False
        self._removing = False
        self._failed_message = ""
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Install the OBIA raster analysis engine once, then use the "
            "Processing Toolbox. Setup downloads verified packages without changing "
            "QGIS, your other Python environments, or shell settings."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.location = QLabel()
        self.location.setWordWrap(True)
        layout.addWidget(self.location)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        actions = QHBoxLayout()
        self.install_button = QPushButton("Install engine")
        self.remove_button = QPushButton("Remove engine")
        self.cancel_button = QPushButton("Cancel")
        self.close_button = QPushButton("Close")
        self.help_button = QPushButton("Help")
        for button in (
            self.install_button,
            self.remove_button,
            self.cancel_button,
            self.help_button,
            self.close_button,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.install_button.clicked.connect(self._install)
        self.remove_button.clicked.connect(self._remove)
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button.clicked.connect(self.close)
        self.help_button.clicked.connect(self._help)
        self._refresh()

    def _refresh(self):
        state = manager.status()
        ready = state["installed"]
        megabytes = state["download_bytes"] / 1_000_000
        self.summary.setText(
            (
                "Engine ready. Repair downloads or reuses verified packages and validates a new installation."
                if ready
                else "The OBIA engine is not installed."
            )
            + f"\nPlatform: {state['platform']}. Full download: about {megabytes:.0f} MB. "
            f"Allow at least {math.ceil(max(2_000_000_000, state['download_bytes'] * 12) / 1e8) / 10:.1f} GB free for setup. "
            "Previous engine installations stay until you choose Remove engine."
        )
        self.location.setText("Engine location: " + state["path"])
        self.install_button.setText("Repair engine" if ready else "Install engine")
        self.install_button.setEnabled(not state["error"])
        self.remove_button.setEnabled(state.get("removable", ready))
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(True)
        if state["error"]:
            self.message.setText(state["error"])

    def _help(self):
        url = QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent / "docs" / "index.html")
        )
        url.setFragment("setup")
        QDesktopServices.openUrl(url)

    def _start(self, operation):
        if self._thread is not None:
            return
        self._failed_message = ""
        self._removing = operation is manager.remove_engine
        self.progress_bar.setValue(0)
        self.message.setText("Starting engine setup…")
        self.install_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.cancel_button.setEnabled(not self._removing)
        self.close_button.setEnabled(False)
        self._thread = _SetupThread(operation, self)
        self._thread.progress.connect(self._progress)
        self._thread.succeeded.connect(self._succeeded)
        self._thread.failed.connect(self._failed)
        self._thread.finished.connect(self._finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _install(self):
        self._start(manager.install_engine)

    def _remove(self):
        answer = QMessageBox.question(
            self,
            "Remove OBIA engine?",
            "Remove this plugin's engine installations? Your projects and "
            "rasters are not affected. Verified downloads are kept for a later reinstall.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start(manager.remove_engine)

    def _cancel(self):
        if self._thread is not None:
            if self._removing:
                self.message.setText("Finishing removal…")
                return
            self._thread.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.message.setText(
                "Canceling… The previous working engine remains available."
            )

    def _progress(self, value, message):
        self.progress_bar.setValue(round(value))
        self.message.setText(message)

    def _failed(self, message, canceled):
        self._failed_message = message
        self.message.setText(message)
        if not canceled:
            QMessageBox.warning(self, "OBIA setup", message)

    def _succeeded(self):
        self.progress_bar.setValue(100)
        self.completed.emit()

    def _finished(self):
        self._thread = None
        self._removing = False
        self._refresh()
        if self._failed_message:
            self.message.setText(self._failed_message)
        if self._closing:
            self.close()

    def reject(self):
        if self._thread is not None:
            self._closing = True
            self._cancel()
        else:
            super().reject()

    def closeEvent(self, event):
        if self._thread is not None:
            self._closing = True
            self._cancel()
            event.ignore()
        else:
            event.accept()
