"""Écran CW plein écran, ouvert par le bouton de mode CW.

En haut, cadre rouge EMISSION : texte tapé (Entrée = émettre, Échap = stop)
et ce qui a déjà été émis. En bas, cadre vert RECEPTION : morse décodé.
Le Scope s'occupe de la radio (BK-IN, envoi CI-V) ; cet écran ne fait
qu'afficher et transmettre les demandes par signaux.
Essai seul : python3 cw_station.py
"""

import time

import html

from PyQt5 import QtCore, QtGui, QtWidgets

from paddle_clavier import MORSE

CODES = {v: k for k, v in MORSE.items()}

RED = "#ff3b30"
RED_TX = "#ff7a6e"          # cadre plus clair et plus épais pendant l'émission
GREEN = "#3ddc84"


def framed(title, color):
    """Cadre de couleur, son nom écrit dans l'angle en haut à gauche."""
    box = QtWidgets.QFrame()
    box.setObjectName("cadre")
    box.setStyleSheet(frame_style(color))
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(24, 10, 24, 20)
    label = QtWidgets.QLabel(title)
    label.setStyleSheet(f"color: {color}; font: bold 22pt sans-serif; "
                        "background: transparent; border: none;")
    layout.addWidget(label, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
    box.title = label
    return box, layout


def frame_style(color, width=4):
    return (f"QFrame#cadre {{ border: {width}px solid {color}; border-radius: 28px; "
            "background: #05080a; }")


class _Entry(QtWidgets.QLineEdit):
    """Champ d'émission : Échap = stop, flèches haut/bas = messages précédents."""
    escape = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.history = []               # messages envoyés, le plus récent à la fin
        self.pos = 0                    # len(history) = ligne neuve

    def remember(self, text):
        if text and (not self.history or self.history[-1] != text):
            self.history.append(text)
        self.pos = len(self.history)

    def recall(self, step):
        if not self.history:
            return
        self.pos = min(max(self.pos + step, 0), len(self.history))
        self.setText(self.history[self.pos] if self.pos < len(self.history) else "")
        self.end(False)

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.escape.emit()
            return
        if key == QtCore.Qt.Key_Up:
            self.recall(-1)
            return
        if key == QtCore.Qt.Key_Down:
            self.recall(1)
            return
        super().keyPressEvent(event)


class _Log(QtWidgets.QPlainTextEdit):
    """Historique : double-clic sur une ligne = la remettre dans le champ."""
    picked = QtCore.pyqtSignal(str)

    def mouseDoubleClickEvent(self, event):
        line = self.cursorForPosition(event.pos()).block().text()
        if "] " in line:
            line = line.split("] ", 1)[1]
        line = line.replace("  (arrêté)", "").strip()
        if line:
            self.picked.emit(line)


class CwStation(QtWidgets.QWidget):
    send = QtCore.pyqtSignal(str)       # texte à émettre
    stop_tx = QtCore.pyqtSignal()       # Échap : arrêt de l'émission
    leave = QtCore.pyqtSignal()         # bouton QUITTER CW
    back = QtCore.pyqtSignal()          # bouton RETOUR : écran fermé, on reste en CW
    wpm_changed = QtCore.pyqtSignal(int)

    def __init__(self, wpm=20):
        super().__init__()
        self.setWindowTitle("CW — Émission / Réception")
        self.setStyleSheet("CwStation { background: #000000; }")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(14)

        # --- EMISSION (rouge) ---
        self.tx_box, tx = framed("EMISSION", RED)
        self.tx_log = _Log()
        self.tx_log.setReadOnly(True)
        self.tx_log.setMaximumBlockCount(500)
        self.tx_log.setStyleSheet(f"font: bold 20pt monospace; color: #ff9d3a; "
                                  "background: #05080a; border: none;")
        self.tx_log.setToolTip("Double-clic sur une ligne : elle revient dans le champ, prête à envoyer")
        self.tx_log.picked.connect(self._pick)
        tx.addWidget(self.tx_log, stretch=1)
        # texte en cours d'émission, lettre par lettre au rythme du morse
        self.live = QtWidgets.QLabel("")
        self.live.setTextFormat(QtCore.Qt.RichText)
        self.live.setStyleSheet("font: bold 28pt monospace; background: transparent; "
                                "border: none; padding: 2px 6px;")
        self.live.setMinimumHeight(52)
        tx.addWidget(self.live)
        self.live_done = ""             # lettres déjà émises
        self.live_todo = []             # [(lettre, durée en s)] encore à émettre
        self.live_stamp = ""
        self.live_timer = QtCore.QTimer(self)
        self.live_timer.setSingleShot(True)
        self.live_timer.timeout.connect(self._live_step)
        self.live_end = QtCore.QTimer(self)
        self.live_end.setSingleShot(True)
        self.live_end.timeout.connect(self._live_commit)
        row = QtWidgets.QHBoxLayout()
        self.entry = _Entry()
        self.entry.setPlaceholderText("Texte à émettre (Entrée ; Échap = stop ; ↑ = précédent)")
        self.entry.setStyleSheet(
            f"QLineEdit {{ font: bold 20pt monospace; color: #ffd54a; background: #120404; "
            f"border: 2px solid {RED}; border-radius: 6px; padding: 4px 10px; }}")
        self.entry.returnPressed.connect(self._send)
        self.entry.escape.connect(self.stop_tx.emit)
        row.addWidget(self.entry, stretch=1)
        self.wpm = QtWidgets.QSpinBox()
        self.wpm.setRange(10, 35)
        self.wpm.setValue(wpm)
        self.wpm.setSuffix(" mots/min")
        self.wpm.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.wpm.setStyleSheet("font: bold 14pt sans-serif; color: #ffd54a; "
                               "background: #120404; padding: 4px;")
        self.wpm.valueChanged.connect(self.wpm_changed.emit)
        row.addWidget(self.wpm)
        quit_button = QtWidgets.QPushButton("QUITTER CW")
        quit_button.setFocusPolicy(QtCore.Qt.NoFocus)
        quit_button.setStyleSheet("font: bold 14pt sans-serif; color: #ffffff; "
                                  "background: #444; border-radius: 6px; padding: 6px 14px;")
        quit_button.setToolTip("Revient au mode d'avant (BK-IN coupé)")
        quit_button.clicked.connect(self.leave.emit)
        row.addWidget(quit_button)
        tx.addLayout(row)
        layout.addWidget(self.tx_box, stretch=2)

        # --- RECEPTION (vert) ---
        rx_box, rx = framed("RECEPTION", GREEN)
        self.rx_text = QtWidgets.QPlainTextEdit()
        self.rx_text.setReadOnly(True)
        self.rx_text.setMaximumBlockCount(2000)
        self.rx_text.setStyleSheet(f"font: bold 24pt monospace; color: {GREEN}; "
                                   "background: #05080a; border: none;")
        rx.addWidget(self.rx_text, stretch=1)
        self.info = QtWidgets.QLabel("")
        self.info.setStyleSheet("font: bold 13pt monospace; color: #ffd54a;")
        rx.addWidget(self.info)
        layout.addWidget(rx_box, stretch=3)
        # RETOUR, en bas à gauche : ferme cet écran (on reste en CW)
        back = QtWidgets.QPushButton("RETOUR")
        back.setFocusPolicy(QtCore.Qt.NoFocus)
        back.setStyleSheet("QPushButton { font: bold 16pt sans-serif; color: #ffffff; "
                           "background: #3a3a3a; border: 2px solid #888; border-radius: 12px; "
                           "padding: 8px 28px; } QPushButton:hover { background: #555; }")
        back.setToolTip("Ferme cet écran ; la radio reste en CW (rappuyer sur CW pour le rouvrir)")
        back.clicked.connect(self._back)
        layout.addWidget(back, alignment=QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom)
        self.tx_on = False

    def _back(self):
        self.hide()
        self.back.emit()

    def _send(self):
        text = self.entry.text().strip()
        if text:
            self.send.emit(text)

    def sent(self, text):
        """Le texte est parti vers la radio : on vide le champ (↑ le rappelle)."""
        self.entry.remember(text.upper())
        self.entry.clear()

    def _pick(self, text):
        self.entry.setText(text)
        self.entry.setFocus()
        self.entry.end(False)

    # --- émission visible en temps réel -----------------------------------
    def play(self, text, wpm):
        """La radio commence à émettre `text` : les lettres s'allument une à une."""
        unit = 1.2 / max(wpm, 1)
        for ch in text.upper():
            if ch == " ":
                units = 7
            else:
                code = CODES.get(ch, "")
                units = sum(1 if c == "." else 3 for c in code) + len(code) - 1 + 3
            self.live_todo.append((ch, units * unit))
        self.live_end.stop()
        if not self.live_stamp:
            self.live_stamp = time.strftime("%H:%M")
        if not self.live_timer.isActive():
            self._live_step()
        self._live_show()

    def _live_step(self):
        if not self.live_todo:
            self.live_end.start(1500)   # fin : la ligne passe dans l'historique
            self._live_show()
            return
        ch, dur = self.live_todo.pop(0)
        self.live_done += ch
        self._live_show()
        self.live_timer.start(max(int(dur * 1000), 1))

    def _live_show(self):
        todo = "".join(c for c, _ in self.live_todo)
        cursor = "▌" if self.live_todo or self.live_timer.isActive() else ""
        self.live.setText(
            f"<span style='color:{RED}'>▶ </span>"
            f"<span style='color:#ffd54a'>{html.escape(self.live_done)}</span>"
            f"<span style='color:{RED}'>{cursor}</span>"
            f"<span style='color:#5a4a3a'>{html.escape(todo)}</span>"
            if self.live_done or todo else "")

    def _live_commit(self, note=""):
        if self.live_done.strip():
            self.tx_log.appendPlainText(f"[{self.live_stamp}] {self.live_done.strip()}{note}")
        self.live_done, self.live_todo, self.live_stamp = "", [], ""
        self.live_timer.stop()
        self.live_end.stop()
        self._live_show()

    def stop_play(self):
        """Émission arrêtée (Échap) : on garde ce qui est parti."""
        if self.live_done or self.live_todo:
            self._live_commit("  (arrêté)")

    def feed_rx(self, text):
        self.rx_text.moveCursor(QtGui.QTextCursor.End)
        self.rx_text.insertPlainText(text)
        self.rx_text.ensureCursorVisible()

    def set_info(self, text):
        self.info.setText(text)

    def set_tx(self, on):
        """La radio émet : le cadre EMISSION s'allume en rouge vif."""
        if bool(on) != self.tx_on:
            self.tx_on = bool(on)
            color = RED_TX if on else RED
            self.tx_box.setStyleSheet(frame_style(color, 7 if on else 4))
            self.tx_box.title.setStyleSheet(f"color: {color}; font: bold 22pt sans-serif; "
                                            "background: transparent; border: none;")

    def open(self, screen=None):
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.entry.setFocus()


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    w = CwStation()
    w.send.connect(lambda t: (w.sent(t), w.set_tx(True),
                              QtCore.QTimer.singleShot(1500, lambda: w.set_tx(False))))
    w.leave.connect(app.quit)
    w.feed_rx("CQ CQ DE F5ABC F5ABC K ")
    w.set_info("7.02000 MHz — BK-IN allumé")
    w.open()
    app.exec_()
