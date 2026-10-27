"""Bouton de puissance « vintage » : bakélite noire cannelée sur jupe chromée,
échelle 0 à 100 W gravée autour (rouge à partir de 80 W), valeur affichée
dessous. Glisser (le repère suit la souris), molette = 1 W, Maj + molette = 10 W."""

import math
import time

from PyQt5 import QtCore, QtGui, QtWidgets

SWEEP = 270                     # degrés de course, de 0 (bas gauche) au maximum (bas droite)
MODE = {"precision": True}      # interrupteur PRÉCISION : double-clic pour accrocher
BASE = 170                      # le dessin est fait pour 170 px, puis mis à l'échelle


class VintageKnob(QtWidgets.QWidget):
    """Bouton bakélite gradué 0…maximum ; caption = nom gravé au-dessus de la valeur."""
    valueChanged = QtCore.pyqtSignal(int)       # seulement quand on le tourne

    def __init__(self, size=170, maximum=100, unit="W", red_from=80, caption="",
                 tooltip=""):
        super().__init__()
        self.setFixedSize(size, size)
        self.maximum = maximum
        self.unit = unit
        self.red_from = red_from
        self.caption = caption
        self.value = 0
        self._dragging = False
        self._wheel = 0
        # fine=True (volumes) : réglage RELATIF et doux — glisser vers le haut ou
        # la droite monte, ~400 px pour toute la course, Ctrl = 4 fois plus fin
        self.fine = False
        self._anchor = None
        self.setCursor(QtCore.Qt.OpenHandCursor)
        if tooltip:
            self.setToolTip(tooltip)

    # --- valeur ----------------------------------------------------------
    def setValue(self, watts):
        """Depuis la radio : pas de signal."""
        watts = int(max(0, min(self.maximum, round(watts))))
        if watts != self.value:
            self.value = watts
            self.update()

    def _user_set(self, watts):
        watts = int(max(0, min(self.maximum, round(watts))))
        if watts != self.value:
            self.value = watts
            self.update()
            self.valueChanged.emit(watts)

    def wheelEvent(self, event):
        if not self.isEnabled():
            return
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            big = event.modifiers() & QtCore.Qt.ShiftModifier
            self._user_set(self.value + steps * (10 if big else 1))
        event.accept()

    def _watts_at(self, pos):
        c = self.rect().center()
        dx, dy = pos.x() - c.x(), c.y() - pos.y()
        if dx * dx + dy * dy < 100:
            return None
        deg = math.degrees(math.atan2(dy, dx))
        travel = (225 - deg) % 360
        if travel > SWEEP:                              # zone morte en bas
            travel = 0.0 if travel - SWEEP > (360 - SWEEP) / 2 else SWEEP
        return travel / SWEEP * self.maximum

    # Souris : un clic simple ne change rien (pas de réglage involontaire).
    # Double-clic : le bouton s'accroche à la souris (anneau lumineux) et suit
    # ses déplacements, sans tenir le bouton ; nouveau double-clic, clic droit
    # ou Échap : il se décroche.
    def mousePressEvent(self, event):
        if not MODE["precision"]:               # mode direct : clic + glisser
            if self.isEnabled() and event.button() == QtCore.Qt.LeftButton:
                self._direct = True
                self._dragging = True
                if self.fine:
                    self._set_anchor(event.globalPos())
                    self.setCursor(QtCore.Qt.SizeVerCursor)
                else:
                    w = self._watts_at(event.pos())
                    if w is not None:
                        self._user_set(w)
            event.accept()
            return
        if self._dragging and not self.rect().contains(event.pos()):
            self._release()                     # accroché : un clic EN DEHORS décroche
            self._unhooked_at = time.monotonic()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if not MODE["precision"]:
            event.accept()
            return
        if time.monotonic() - getattr(self, "_unhooked_at", 0) < 0.6:
            event.accept()                      # 2e clic du double-clic qui a décroché
            return
        if self._dragging:
            self._release()
        elif self.isEnabled():
            self._dragging = True
            if self.fine:
                self._set_anchor(QtGui.QCursor.pos())
            self.setMouseTracking(True)
            self.grabMouse(QtGui.QCursor(QtCore.Qt.ClosedHandCursor))
            self.grabKeyboard()
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if getattr(self, "_direct", False) and self._dragging:
            self._direct = False
            self._dragging = False
            self._anchor = None
            self.setCursor(QtCore.Qt.OpenHandCursor)
            self.update()
        event.accept()

    def _set_anchor(self, gpos):
        self._anchor = (gpos.x(), gpos.y(), float(self.value),
                        bool(QtWidgets.QApplication.keyboardModifiers()
                             & QtCore.Qt.ControlModifier))

    def _fine_value(self, gpos):
        """Valeur d'après le déplacement depuis le point de départ (relatif)."""
        ctrl = bool(QtWidgets.QApplication.keyboardModifiers() & QtCore.Qt.ControlModifier)
        if self._anchor is None or ctrl != self._anchor[3]:
            self._set_anchor(gpos)              # Ctrl appuyé/lâché : repart d'ici, sans saut
        x0, y0, v0, ctrl = self._anchor
        rate = self.maximum / 400 / (4 if ctrl else 1)
        return v0 + ((y0 - gpos.y()) + (gpos.x() - x0)) * rate

    def _release(self):
        if not self._dragging:
            return
        self._anchor = None
        self._dragging = False
        self.setMouseTracking(False)
        self.releaseMouse()
        self.releaseKeyboard()
        self.update()

    def keyPressEvent(self, event):
        if self._dragging and event.key() == QtCore.Qt.Key_Escape:
            self._release()
        else:
            super().keyPressEvent(event)

    def hideEvent(self, event):
        self._release()
        super().hideEvent(event)

    def _too_far(self, pos):
        """La souris s'éloigne du bouton (> 1,5 fois sa taille) : on décroche."""
        c = self.rect().center()
        return max(abs(pos.x() - c.x()), abs(pos.y() - c.y())) > 1.5 * self.width()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        if self.fine:
            self._user_set(self._fine_value(event.globalPos()))
            return
        if not getattr(self, "_direct", False) and self._too_far(event.pos()):
            self._release()
            return
        w = self._watts_at(event.pos())
        if w is not None and abs(w - self.value) <= self.maximum / 2:     # pas de saut 0 ↔ 100
            self._user_set(w)

    # --- dessin ----------------------------------------------------------
    def _dir(self, watts):
        a = math.radians(225 - SWEEP * watts / self.maximum)
        return QtCore.QPointF(math.cos(a), -math.sin(a))

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(self.width() / BASE, self.height() / BASE)
        small = self.width() < 150             # petits boutons : graduations plus lisibles
        m = min(max(130 / self.width(), 1.0), 1.3)   # encore plus gros si très petit
        w = BASE
        c = QtCore.QPointF(w / 2, w / 2)
        R = w / 2 - 2
        on = self.isEnabled()

        # plaque de fond : métal sombre, bord en relief
        g = QtGui.QRadialGradient(c - QtCore.QPointF(R / 3, R / 3), R * 1.8)
        g.setColorAt(0, QtGui.QColor("#3b3f44"))
        g.setColorAt(1, QtGui.QColor("#121416"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.5))
        p.setBrush(g)
        p.drawEllipse(c, R, R)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 1))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawEllipse(c, R - 2, R - 2)

        # échelle gravée : grands traits tous les 10 W, petits tous les 5 W
        font = QtGui.QFont("DejaVu Sans", round((9 if small else 7) * m), QtGui.QFont.Bold)
        p.setFont(font)
        for n in range(21):                     # 20 pas : petits, grands, chiffres
            k = n * self.maximum / 20
            u = self._dir(k)
            big = n % 2 == 0
            red = self.red_from is not None and k >= self.red_from
            col = QtGui.QColor("#ff5a4a" if red else "#e9e4d4")
            if not big:
                col.setAlpha(170)
            p.setPen(QtGui.QPen(col, 1.8 if big else 1.0, cap=QtCore.Qt.RoundCap))
            p.drawLine(c + u * (R - 20), c + u * (R - (27 if big else 24)))
            if n % 4 == 0 or n == 20:
                pos = c + u * (R - 11)
                p.setPen(QtGui.QColor("#ff6b5b" if red else "#f1ecdc"))
                p.drawText(QtCore.QRectF(pos.x() - 16, pos.y() - 8, 32, 16),
                           QtCore.Qt.AlignCenter, f"{k:g}")
        # arc rouge de la zone haute
        if self.red_from is not None:
            arc = R - 29
            rect = QtCore.QRectF(c.x() - arc, c.y() - arc, 2 * arc, 2 * arc)
            start = 225 - SWEEP * self.red_from / self.maximum
            p.setPen(QtGui.QPen(QtGui.QColor(230, 60, 45, 200), 2.2, cap=QtCore.Qt.FlatCap))
            p.drawArc(rect, int((225 - SWEEP) * 16), int((start - (225 - SWEEP)) * 16))

        # ombre portée du bouton
        kr = R - 36                             # rayon de la jupe moletée
        p.setPen(QtCore.Qt.NoPen)
        for i, alpha in enumerate((60, 40, 22)):
            p.setBrush(QtGui.QColor(0, 0, 0, alpha))
            p.drawEllipse(c + QtCore.QPointF(3 + i, 5 + i), kr + 1 + i, kr + 1 + i)

        u = self._dir(self.value)
        # jupe chromée évasée (disque poli, reflets en cône)
        g = QtGui.QConicalGradient(c, 135)
        for pos, col in ((0, "#ffffff"), (0.1, "#8f949a"), (0.27, "#eceef0"),
                         (0.45, "#5f646a"), (0.62, "#dfe2e5"), (0.82, "#7d8288"),
                         (1, "#ffffff")):
            g.setColorAt(pos, QtGui.QColor(col))
        p.setPen(QtGui.QPen(QtGui.QColor("#202224"), 1))
        p.setBrush(g)
        p.drawEllipse(c, kr, kr)
        # biseau de la jupe : anneau plus sombre vers le corps
        g = QtGui.QRadialGradient(c, kr)
        g.setColorAt(0.70, QtGui.QColor(0, 0, 0, 120))
        g.setColorAt(0.80, QtGui.QColor(0, 0, 0, 0))
        g.setColorAt(1.0, QtGui.QColor(255, 255, 255, 40))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, kr, kr)
        # repère blanc gravé sur la jupe
        p.setPen(QtGui.QPen(QtGui.QColor("#fbfbf5"), 2.6, cap=QtCore.Qt.RoundCap))
        p.drawLine(c + u * (kr - 9), c + u * (kr - 1.5))

        # corps en bakélite noire cannelé (prise en main)
        br = kr - 9
        p.setBrush(QtGui.QColor(0, 0, 0, 110))
        p.drawEllipse(c + QtCore.QPointF(1.5, 2.5), br + 1, br + 1)     # ombre sur la jupe
        flutes = 18
        path = QtGui.QPainterPath()
        for k in range(flutes * 8 + 1):
            a = 2 * math.pi * k / (flutes * 8)
            rr = br - 2.2 * (0.5 - 0.5 * math.cos(flutes * a))         # cannelures arrondies
            pt = c + QtCore.QPointF(math.cos(a), math.sin(a)) * rr
            path.lineTo(pt) if k else path.moveTo(pt)
        g = QtGui.QRadialGradient(c - QtCore.QPointF(br / 2.5, br / 2.5), br * 1.6)
        g.setColorAt(0, QtGui.QColor("#4a4643"))
        g.setColorAt(0.5, QtGui.QColor("#171513"))
        g.setColorAt(1, QtGui.QColor("#020202"))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.setBrush(g)
        p.drawPath(path)
        # reflets sur les cannelures (côté lumière, en haut à gauche)
        for k in range(flutes):
            a = 2 * math.pi * (k + 0.5) / flutes
            light = max(0.0, math.cos(a - math.radians(225)))
            if light < 0.05:
                continue
            d = QtCore.QPointF(math.cos(a), math.sin(a))
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, int(70 * light)), 1.6,
                                cap=QtCore.Qt.RoundCap))
            p.drawLine(c + d * (br - 9), c + d * (br - 2.5))

        # dessus bombé brillant
        tr = br - 9
        g = QtGui.QRadialGradient(c - QtCore.QPointF(tr / 3, tr / 3), tr * 1.5)
        g.setColorAt(0, QtGui.QColor("#5a5550"))
        g.setColorAt(0.35, QtGui.QColor("#1e1b19"))
        g.setColorAt(1, QtGui.QColor("#050505"))
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 30), 1))
        p.setBrush(g)
        p.drawEllipse(c, tr, tr)
        # reflet spéculaire (fenêtre de lumière) en haut à gauche
        hl = QtCore.QRectF(c.x() - tr * 0.72, c.y() - tr * 0.78, tr * 0.95, tr * 0.6)
        g = QtGui.QLinearGradient(hl.topLeft(), hl.bottomLeft())
        g.setColorAt(0, QtGui.QColor(255, 255, 255, 120))
        g.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.save()
        p.translate(hl.center())
        p.rotate(-35)
        p.translate(-hl.center())
        p.drawEllipse(hl)
        p.restore()
        # point blanc incrusté sur le dessus, aligné sur le repère
        p.setBrush(QtGui.QColor("#f5f2e8" if on else "#8a8780"))
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 150), 0.8))
        p.drawEllipse(c + u * (tr * 0.68), 2.6, 2.6)

        # valeur dans la zone morte du bas
        if self.caption:
            p.setFont(QtGui.QFont("DejaVu Sans", round((8 if small else 6) * min(m, 1.15)), QtGui.QFont.Bold))
            p.setPen(QtGui.QColor("#e9e4d4"))
            p.drawText(QtCore.QRectF(c.x() - 45, w - 41, 90, 15), QtCore.Qt.AlignCenter,
                       self.caption)
        p.setFont(QtGui.QFont("DejaVu Sans Mono", round((11 if small else 9) * m), QtGui.QFont.Bold))
        p.setPen(QtGui.QColor("#ffb300" if on else "#777"))
        p.drawText(QtCore.QRectF(c.x() - 40, w - 26, 80, 20), QtCore.Qt.AlignCenter,
                   self.text())
        if self._dragging:                      # accroché à la souris : anneau lumineux
            for k, a in ((0, 230), (2, 120), (4, 50)):
                p.setPen(QtGui.QPen(QtGui.QColor(255, 190, 60, a), 2.2))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawEllipse(c, R - 1 - k, R - 1 - k)
        p.end()


    def text(self):
        """Valeur affichée sous le bouton."""
        return f"{self.value} {self.unit}"


class ScaleBakelite(VintageKnob):
    """Même bouton, gradué 0 à 10 au dixième, comme l'ancien ScaleKnob :
    setValue émet valueChanged(float), double-clic = 5, molette 0,1 (Maj = 1).
    text_fn(valeur) donne le texte affiché dessous."""
    valueChanged = QtCore.pyqtSignal(float)

    def __init__(self, value=5.0, size=104, caption="", text_fn=None, tooltip=""):
        super().__init__(size, 10, "", None, caption, tooltip)
        self.value = value
        self.text_fn = text_fn

    def setValue(self, value):
        value = round(max(0.0, min(10.0, value)), 2 if self.fine else 1)
        if value != self.value:
            self.value = value
            self.update()
            self.valueChanged.emit(value)

    _user_set = setValue

    def wheelEvent(self, event):
        self._wheel += event.angleDelta().y()
        steps = int(self._wheel / 120)
        if steps:
            self._wheel -= steps * 120
            big = event.modifiers() & QtCore.Qt.ShiftModifier
            self.setValue(self.value + steps * (1.0 if big else 0.1))
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        if self.fine:
            self.setValue(self._fine_value(event.globalPos()))
            return
        if not getattr(self, "_direct", False) and self._too_far(event.pos()):
            self._release()
            return
        v = self._watts_at(event.pos())
        if v is not None and abs(v - self.value) <= 5:
            self.setValue(v)


    def text(self):
        return self.text_fn(self.value) if self.text_fn else f"{self.value:.1f}"


class PowerKnob(VintageKnob):
    def __init__(self, size=170):
        super().__init__(size, 100, "W", 80, "",
                         "Puissance d'émission (W) : glisser, ou molette (1 W, Maj = 10 W)")


if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    k = PowerKnob()
    k.setValue(60)
    k.show()
    sys.exit(app.exec_())


class NamePlate(QtWidgets.QWidget):
    """Petite plaque d'aluminium brossé à bords arrondis, nom gravé en noir."""

    def __init__(self, text, width, height=15):
        super().__init__()
        self.text = text
        self.setFixedSize(width, height)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(1, 0.5, self.width() - 2, self.height() - 1)
        g = QtGui.QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QtGui.QColor("#f4f5f6"))
        g.setColorAt(0.5, QtGui.QColor("#c9ccd0"))
        g.setColorAt(1, QtGui.QColor("#9ea2a7"))
        p.setPen(QtGui.QPen(QtGui.QColor("#4a4d51"), 0.9))
        p.setBrush(g)
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 40), 0.6))     # brossage
        for x in range(4, self.width() - 3, 2):
            p.drawLine(QtCore.QPointF(x, 2.5), QtCore.QPointF(x, self.height() - 2.5))
        f = QtGui.QFont("DejaVu Sans Condensed", 7, QtGui.QFont.Bold)
        f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.3)
        while QtGui.QFontMetricsF(f).horizontalAdvance(self.text) > self.width() - 8 \
                and f.pointSizeF() > 5:
            f.setPointSizeF(f.pointSizeF() - 0.25)       # le nom tient sur la plaque
        p.setFont(f)
        p.setPen(QtGui.QColor(255, 255, 255, 150))                       # gravure
        p.drawText(r.translated(0, 0.8), QtCore.Qt.AlignCenter, self.text)
        p.setPen(QtGui.QColor("#111111"))
        p.drawText(r, QtCore.Qt.AlignCenter, self.text)
        p.end()
