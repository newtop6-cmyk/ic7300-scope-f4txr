"""Bouton poussoir en forme de boule bleue (dégradé, reflet, ombre : effet 3D)."""

from PyQt5 import QtCore, QtGui, QtWidgets


class BallButton(QtWidgets.QAbstractButton):
    def __init__(self, text, diameter=96, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.diameter = diameter
        self.setFixedSize(diameter + 16, diameter + 16)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        d = self.diameter
        down = self.isDown()
        off = 3 if down else 0                      # enfoncée : la boule descend
        ball = QtCore.QRectF(8, 6 + off, d, d)
        c = ball.center()
        # ombre portée au sol
        shadow = QtGui.QRadialGradient(QtCore.QPointF(c.x() + 3, ball.bottom() + 3 - off), d * 0.5)
        shadow.setColorAt(0, QtGui.QColor(0, 0, 0, 120 if not down else 80))
        shadow.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(shadow)
        p.drawEllipse(QtCore.QRectF(c.x() - d * 0.45 + 3, ball.bottom() - d * 0.12 - off,
                                    d * 0.9, d * 0.24))
        # corps de la boule : dégradé bleu, lumière en haut à gauche
        body = QtGui.QRadialGradient(QtCore.QPointF(c.x() - d * 0.18, c.y() - d * 0.22),
                                     d * 0.75)
        light = "#7fc4ff" if self._hover else "#5fb0ff"
        body.setColorAt(0.0, QtGui.QColor(light))
        body.setColorAt(0.35, QtGui.QColor("#1e6fe0" if not down else "#1a5fc4"))
        body.setColorAt(0.8, QtGui.QColor("#0a2f86"))
        body.setColorAt(1.0, QtGui.QColor("#04143d"))
        p.setBrush(body)
        p.setPen(QtGui.QPen(QtGui.QColor(2, 10, 35, 200), 1.2))
        p.drawEllipse(ball)
        # reflet brillant
        gloss = QtGui.QLinearGradient(c.x(), ball.top(), c.x(), c.y())
        gloss.setColorAt(0, QtGui.QColor(255, 255, 255, 190))
        gloss.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(gloss)
        p.drawEllipse(QtCore.QRectF(c.x() - d * 0.32, ball.top() + d * 0.05, d * 0.64, d * 0.42))
        # liseré lumineux en bas (lumière renvoyée)
        rim = QtGui.QRadialGradient(QtCore.QPointF(c.x(), ball.bottom()), d * 0.5)
        rim.setColorAt(0, QtGui.QColor(120, 200, 255, 90))
        rim.setColorAt(1, QtGui.QColor(120, 200, 255, 0))
        p.setBrush(rim)
        p.drawEllipse(ball)
        # texte gravé
        font = QtGui.QFont("DejaVu Sans", max(8, int(d / 9)), QtGui.QFont.Bold)
        p.setFont(font)
        p.setPen(QtGui.QColor(0, 10, 40, 170))
        p.drawText(ball.translated(1, 1.5), QtCore.Qt.AlignCenter, self.text())
        p.setPen(QtGui.QColor("#ffffff"))
        p.drawText(ball, QtCore.Qt.AlignCenter, self.text())
        p.end()


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    b = BallButton("FERMER\nFT8")
    if "--shot" in sys.argv:
        w = QtWidgets.QWidget()
        w.setStyleSheet("background:#0e2150")
        w.resize(140, 140)
        b.setParent(w)
        b.move(10, 10)
        w.grab().save(sys.argv[-1])
        sys.exit()
    b.show()
    app.exec_()
