"""Écran plein cadre des fonctions du sélecteur FONCTION.

Quand une fonction est enclenchée, son contenu passe en plein écran et prend
toute la place ; un bandeau en haut rappelle la fonction, avec un bouton
RETOUR (ou Échap) qui remet le sélecteur sur OFF.

Contenus : un widget quelconque (ex. le waterfall, emprunté à la fenêtre
principale puis rendu), la vue SSTV en direct, ou un écran « en préparation »
pour les fonctions encore à créer.
"""

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from sstv_window import denoise, to_qimage
from title_plate import TitlePlate


class FunctionBar(TitlePlate):
    """Bandeau rouillé du haut, avec le nom de la fonction et RETOUR."""

    def __init__(self, screen):
        super().__init__(screen)
        self.screen = screen
        self.name = ""

    def _buttons(self):
        return [("close", QtCore.QPointF(self.width() - 24, self.height() / 2))]

    def mousePressEvent(self, event):
        if self._button_at(event.pos()) == "close" or event.pos().x() > self.width() - 150:
            self.screen.back.emit()

    def mouseDoubleClickEvent(self, event):
        pass

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = QtGui.QFont("DejaVu Sans Condensed", 12, QtGui.QFont.Black)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 3)
        p.setFont(f)
        p.setPen(QtGui.QColor("#e8e2cf"))
        p.drawText(QtCore.QRectF(60, 0, 300, self.height()),
                   QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, f"FONCTION  {self.name}")
        p.drawText(QtCore.QRectF(self.width() - 150, 0, 110, self.height()),
                   QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, "RETOUR")
        p.end()


class FunctionScreen(QtWidgets.QWidget):
    back = QtCore.pyqtSignal()                  # RETOUR / Échap

    def __init__(self):
        super().__init__(None, QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        self.setWindowTitle("IC-7300 Scope — fonction")
        self.setStyleSheet("background: #0d1014;")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.bar = FunctionBar(self)
        lay.addWidget(self.bar)
        self.holder = QtWidgets.QVBoxLayout()
        self.holder.setContentsMargins(10, 10, 10, 10)
        lay.addLayout(self.holder, stretch=1)
        self.content = None
        QtWidgets.QShortcut(QtGui.QKeySequence("Escape"), self, self.back.emit)

    def show_content(self, name, widget):
        """Affiche widget en plein écran ; renvoie l'ancien contenu (à rendre)."""
        old = self.take_content()
        self.bar.name = name
        self.bar.update()
        self.content = widget
        self.holder.addWidget(widget, stretch=1)
        widget.show()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        return old

    def take_content(self):
        """Retire le contenu actuel (sans le détruire) et le renvoie."""
        old = self.content
        if old is not None:
            self.holder.removeWidget(old)
            old.setParent(None)
        self.content = None
        return old


class PendingView(QtWidgets.QWidget):
    """Fonction pas encore créée."""

    def __init__(self, name):
        super().__init__()
        self.name = name

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtGui.QColor("#d9cfa8"))
        p.setFont(QtGui.QFont("URW Gothic", 28, QtGui.QFont.Bold))
        p.drawText(self.rect().adjusted(0, -40, 0, -40), QtCore.Qt.AlignCenter, self.name)
        p.setFont(QtGui.QFont("URW Gothic", 14))
        p.drawText(self.rect().adjusted(0, 40, 0, 40), QtCore.Qt.AlignCenter,
                   "Fonction en préparation — 73 de F4TXR")
        p.end()


class SstvLiveView(QtWidgets.QWidget):
    """Image SSTV en cours, en très grand (proportions gardées), état dessous.
    Bouton LISIBLE : version débruitée noir et blanc à la place de la couleur."""

    def __init__(self, decoder_of):
        super().__init__()
        self.decoder_of = decoder_of            # fonction : décodeur SSTV actuel
        self.lisible = False
        self.image = None
        self.status = ""
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(300)
        self.button = QtWidgets.QPushButton("LISIBLE (noir et blanc)", self)
        self.button.setCheckable(True)
        self.button.setStyleSheet(
            "QPushButton { font: bold 11pt 'DejaVu Sans'; color: #1e1609; "
            "background: #efe2bb; border: 2px solid #3a2c12; border-radius: 8px; padding: 6px 14px; }"
            "QPushButton:checked { background: #ffcf6a; }")
        self.button.toggled.connect(self._toggle)

    def _toggle(self, on):
        self.lisible = on
        self._refresh()

    def resizeEvent(self, event):
        self.button.adjustSize()
        self.button.move(self.width() - self.button.width() - 10, self.height() - self.button.height() - 6)

    def _refresh(self):
        dec = self.decoder_of()
        if dec is None:
            self.image, self.status = None, "Pas de décodeur SSTV"
        else:
            rgb = dec.image
            if rgb is not None and dec.mode is not None:
                rows = max(1, min(dec.line * dec.mode.rows_per_period, dec.mode.height))
                rgb = rgb[:rows] if self.lisible else rgb
                rgb = denoise(rgb) if self.lisible and rows > 4 else rgb
                self.image = to_qimage(np.ascontiguousarray(rgb))
            self.status = dec.status()
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        area = self.rect().adjusted(0, 0, 0, -50)
        if self.image is not None and not self.image.isNull():
            img = self.image.scaled(area.size(), QtCore.Qt.KeepAspectRatio,
                                    QtCore.Qt.SmoothTransformation)
            x = area.x() + (area.width() - img.width()) // 2
            y = area.y() + (area.height() - img.height()) // 2
            p.fillRect(QtCore.QRect(x - 6, y - 6, img.width() + 12, img.height() + 12),
                       QtGui.QColor("#2a2420"))
            p.drawImage(x, y, img)
        else:
            p.setPen(QtGui.QColor("#d9cfa8"))
            p.setFont(QtGui.QFont("URW Gothic", 20))
            p.drawText(area, QtCore.Qt.AlignCenter, "En attente d'une image SSTV…")
        p.setPen(QtGui.QColor("#ffcf6a"))
        p.setFont(QtGui.QFont("DejaVu Sans Mono", 13, QtGui.QFont.Bold))
        p.drawText(QtCore.QRect(10, self.height() - 44, self.width() - 300, 40),
                   QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self.status)
        p.end()
