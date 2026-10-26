"""Bouton EMISSION (remplace le bouton VOX) : poussoir rectangulaire aux bords
arrondis, façon vintage en relief, lentille rouge.
  éteint      : rouge sombre, non éclairé (VOX arrêté)
  armé        : rouge vif qui clignote lentement (VOX en attente de la voix)
  en émission : clignotement rouge vif rapide, cœur éblouissant"""

from PyQt5 import QtCore, QtGui, QtWidgets


class EmissionButton(QtWidgets.QAbstractButton):
    def __init__(self, text="EMISSION", width=100, height=46):
        super().__init__()
        self.setText(text)
        self.setCheckable(True)
        self.M, self.MY = 9, 4              # marges pour le halo rouge
        self.setFixedSize(width + 2 * self.M, height + 2 * self.MY)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.is_tx = lambda: False          # fourni par Scope : émission en cours ?
        self.phase = 0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(60)
        self.toggled.connect(lambda _: self.update())

    def _tick(self):
        self.phase += 1
        if self.isChecked():
            self.update()

    def _lit(self):
        if not self.isChecked():
            return 0.0
        if self.is_tx():
            return 1.0 if (self.phase // 2) % 2 == 0 else 0.45     # ~4 éclats/s
        return 1.0 if (self.phase // 8) % 2 == 0 else 0.15         # ~1 éclat/s

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        down = self.isDown()
        lit = self._lit()
        M, MY = self.M, self.MY
        w, h = self.width() - 2 * M, self.height() - 2 * MY
        if lit >= 0.5:                      # halo rouge qui déborde autour du bouton
            p.setPen(QtCore.Qt.NoPen)
            for i in range(M, 0, -1):
                a = int(200 * lit * (1 - i / (M + 1)) ** 2)
                p.setBrush(QtGui.QColor(255, 0, 0, a))
                p.drawRoundedRect(QtCore.QRectF(M - i, MY - i, w + 2 * i - 3, h + 2 * i - 4),
                                  12 + i, 12 + i)
        p.translate(M, MY)
        # ombre portée
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 120))
        p.drawRoundedRect(QtCore.QRectF(3, 5, w - 5, h - 6), 12, 12)
        # lunette chromée
        chrome = QtGui.QLinearGradient(0, 0, 0, h)
        chrome.setColorAt(0, QtGui.QColor("#f4f4f4"))
        chrome.setColorAt(0.45, QtGui.QColor("#9a9a9a"))
        chrome.setColorAt(0.55, QtGui.QColor("#d0d0d0"))
        chrome.setColorAt(1, QtGui.QColor("#4a4a4a"))
        p.setPen(QtGui.QPen(QtGui.QColor("#202020"), 1))
        p.setBrush(chrome)
        p.drawRoundedRect(QtCore.QRectF(1, 1, w - 4, h - 5), 12, 12)
        # lentille rouge en relief (s'enfonce quand on appuie)
        off = 1.5 if down else 0.0
        lens = QtCore.QRectF(6, 6 + off, w - 14, h - 15)
        # rouge pur saturé, jamais pâle : éteint = rouge sang, allumé = rouge feu
        g = QtGui.QLinearGradient(0, lens.top(), 0, lens.bottom())
        if lit >= 0.5:                      # rouge incandescent, très très lumineux
            g.setColorAt(0, QtGui.QColor(255, 80, 50))
            g.setColorAt(0.3, QtGui.QColor(255, 25, 0))
            g.setColorAt(0.75, QtGui.QColor(255, 0, 0))
            g.setColorAt(1, QtGui.QColor(210, 0, 0))
        elif self.isChecked():              # temps « éteint » du clignotement : noir-rouge
            g.setColorAt(0, QtGui.QColor(90, 0, 0))
            g.setColorAt(0.5, QtGui.QColor(55, 0, 0))
            g.setColorAt(1, QtGui.QColor(20, 0, 0))
        else:
            g.setColorAt(0, QtGui.QColor(200, 0, 0))
            g.setColorAt(0.5, QtGui.QColor(165, 0, 0))
            g.setColorAt(1, QtGui.QColor(70, 0, 0))
        p.setPen(QtGui.QPen(QtGui.QColor("#2a0606"), 1.2))
        p.setBrush(g)
        p.drawRoundedRect(lens, 9, 9)
        if lit > 0.5:                       # cœur incandescent rouge-orangé
            core = QtGui.QRadialGradient(lens.center(), lens.width() * 0.55)
            core.setColorAt(0, QtGui.QColor(255, 95, 55, int(255 * lit)))
            core.setColorAt(0.35, QtGui.QColor(255, 60, 20, int(230 * lit)))
            core.setColorAt(0.7, QtGui.QColor(255, 0, 0, int(160 * lit)))
            core.setColorAt(1, QtGui.QColor(255, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(core)
            p.drawRoundedRect(lens, 9, 9)
        # reflet du verre
        shine = QtGui.QLinearGradient(0, lens.top(), 0, lens.center().y())
        shine.setColorAt(0, QtGui.QColor(255, 255, 255, 85))
        shine.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(shine)
        p.drawRoundedRect(lens.adjusted(4, 2, -4, -lens.height() * 0.5), 6, 6)
        # inscription gravée
        font = QtGui.QFont("DejaVu Sans", 9, QtGui.QFont.Black)
        font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.8)
        p.setFont(font)
        p.setPen(QtGui.QColor(0, 0, 0, 160))
        p.drawText(lens.translated(1, 1), QtCore.Qt.AlignCenter, self.text())
        p.setPen(QtGui.QColor(255, 255, 255) if lit >= 0.5 else QtGui.QColor(255, 225, 0))
        p.drawText(lens, QtCore.Qt.AlignCenter, self.text())
