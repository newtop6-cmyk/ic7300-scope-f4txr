"""Poussoir vintage en relief (écran MOBILE) : lunette chromée, gorge noire,
capuchon bombé ivoire façon bakélite, inscription gravée. Allumé (lamp) :
le capuchon devient un voyant coloré qui luit. Enfoncé : il descend."""

from PyQt5 import QtCore, QtGui, QtWidgets


class VintagePush(QtWidgets.QPushButton):
    def __init__(self, text, width, height):
        super().__init__(text)
        self.setFixedSize(width, height)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.lamp = None                # QColor : capuchon allumé de cette couleur

    def set_lamp(self, color):
        color = QtGui.QColor(color) if color else None
        if (color.name() if color else None) != (self.lamp.name() if self.lamp else None):
            self.lamp = color
            self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QtCore.QRectF(1, 1, w - 2, h - 3)
        rad = min(w, h) * 0.22
        # ombre portée sur la façade
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.drawRoundedRect(r.translated(1.2, 2), rad, rad)
        # lunette chromée
        g = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
        for stop, col in ((0, "#ffffff"), (0.2, "#c9ccc7"), (0.5, "#7c807a"),
                          (0.8, "#d9dcd7"), (1, "#4c4f4a")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1d1f1c"), 0.8))
        p.drawRoundedRect(r, rad, rad)
        # gorge noire
        gap = r.adjusted(3.5, 3.5, -3.5, -3.5)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#0c0d0b"))
        p.drawRoundedRect(gap, rad * 0.8, rad * 0.8)
        # capuchon : bombé, descend quand on appuie
        down = self.isDown()
        cap = gap.adjusted(2.2, 1.6 + (1.4 if down else 0), -2.2, -3.2 + (1.4 if down else 0))
        lit = self.lamp is not None
        if lit:
            base = self.lamp
            top, mid, bot = base.lighter(170), base, base.darker(190)
        else:
            top, mid, bot = QtGui.QColor("#fffaea"), QtGui.QColor("#e9dcb8"), QtGui.QColor("#9c8a5e")
        if down:
            top, mid, bot = top.darker(115), mid.darker(115), bot.darker(115)
        g = QtGui.QLinearGradient(0, cap.top(), 0, cap.bottom())
        g.setColorAt(0, top)
        g.setColorAt(0.45, mid)
        g.setColorAt(1, bot)
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 160), 0.8))
        crad = rad * 0.65
        p.drawRoundedRect(cap, crad, crad)
        if lit:                                     # lueur intérieure du voyant
            glow = QtGui.QRadialGradient(cap.center(), max(cap.width(), cap.height()) * 0.6)
            c = QtGui.QColor(self.lamp.lighter(190))
            c.setAlpha(150)
            glow.setColorAt(0, c)
            glow.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(glow)
            p.drawRoundedRect(cap, crad, crad)
        # reflet bombé en haut du capuchon
        shine = cap.adjusted(cap.width() * 0.08, 1.2, -cap.width() * 0.08, -cap.height() * 0.52)
        g = QtGui.QLinearGradient(0, shine.top(), 0, shine.bottom())
        g.setColorAt(0, QtGui.QColor(255, 255, 255, 150 if not down else 80))
        g.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(shine, crad * 0.8, crad * 0.8)
        # inscription gravée
        f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Bold)
        lines = self.text().count("\n") + 1
        longest = max(len(line) for line in self.text().split("\n")) or 1
        f.setPixelSize(max(7, int(min(cap.height() / (lines * 1.45),
                                      cap.width() / (longest * 0.72)))))
        p.setFont(f)
        if lit:
            p.setPen(QtGui.QColor(0, 0, 0, 120))
            p.drawText(cap.translated(0, 0.8), QtCore.Qt.AlignCenter, self.text())
            p.setPen(QtGui.QColor("#ffffff"))
        else:
            p.setPen(QtGui.QColor(255, 255, 255, 170))       # bord clair de la gravure
            p.drawText(cap.translated(0, 0.8), QtCore.Qt.AlignCenter, self.text())
            p.setPen(QtGui.QColor("#2a2114"))
        p.drawText(cap, QtCore.Qt.AlignCenter, self.text())
        p.end()


class RoundPush(QtWidgets.QPushButton):
    """Micro poussoir ROND vintage en relief 3D : ombre portée, lunette chromée
    moletée, gorge noire, capuchon ivoire bombé avec inscription gravée ;
    enfoncé, le capuchon descend et s'assombrit."""

    def __init__(self, text, size=40):
        super().__init__(text)
        self.setFixedSize(size, size)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s = min(self.width(), self.height())
        c = QtCore.QPointF(s / 2 - 0.8, s / 2 - 1.2)
        R = s / 2 - 3
        down = self.isDown()
        # ombre portée douce, en bas à droite
        for i in range(5, 0, -1):
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, 22))
            p.drawEllipse(c + QtCore.QPointF(1.2 + i * 0.35, 1.8 + i * 0.4), R + i * 0.5, R + i * 0.5)
        # lunette chromée (dégradé conique = reflets du métal tourné)
        g = QtGui.QConicalGradient(c, 135)
        for stop, col in ((0, "#ffffff"), (0.12, "#b9bdb6"), (0.3, "#5d615b"),
                          (0.5, "#e8ebe6"), (0.7, "#6d716b"), (0.88, "#cfd2cc"), (1, "#ffffff")):
            g.setColorAt(stop, QtGui.QColor(col))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#1b1d1a"), 0.9))
        p.drawEllipse(c, R, R)
        # moletage fin sur le bord de la lunette
        p.setPen(QtGui.QPen(QtGui.QColor(30, 30, 30, 110), 0.7))
        import math
        for k in range(36):
            a = math.radians(k * 10)
            u = QtCore.QPointF(math.cos(a), math.sin(a))
            p.drawLine(c + u * (R - 2.2), c + u * (R - 0.6))
        # gorge noire
        rg = R * 0.74
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#0b0c0a"))
        p.drawEllipse(c, rg, rg)
        # capuchon bombé ivoire (descend quand on appuie)
        rc = rg - 1.6
        cc = c + QtCore.QPointF(0, 1.0 if down else -0.4)
        g = QtGui.QRadialGradient(cc + QtCore.QPointF(-rc * 0.35, -rc * 0.4), rc * 1.5)
        top, mid, bot = QtGui.QColor("#fffbee"), QtGui.QColor("#e6d7af"), QtGui.QColor("#8e7a4e")
        if down:
            top, mid, bot = top.darker(118), mid.darker(118), bot.darker(118)
        g.setColorAt(0, top)
        g.setColorAt(0.55, mid)
        g.setColorAt(1, bot)
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor(60, 48, 25, 160), 0.6))
        p.drawEllipse(cc, rc, rc)
        # point de lumière sur le dôme
        if not down:
            hl = QtGui.QRadialGradient(cc + QtCore.QPointF(-rc * 0.38, -rc * 0.45), rc * 0.45)
            hl.setColorAt(0, QtGui.QColor(255, 255, 255, 200))
            hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(hl)
            p.drawEllipse(cc, rc, rc)
        # inscription gravée : creux sombre + liseré clair en dessous
        f = QtGui.QFont("DejaVu Sans Condensed")
        f.setPixelSize(max(6, int(min(rc * 0.62, 2 * rc * 0.78 / (0.6 * max(1, len(self.text())))))))
        f.setWeight(QtGui.QFont.Black)
        p.setFont(f)
        box = QtCore.QRectF(cc.x() - rc, cc.y() - rc, 2 * rc, 2 * rc)
        p.setPen(QtGui.QColor(255, 250, 230, 170))
        p.drawText(box.translated(0, 0.7), QtCore.Qt.AlignCenter, self.text())
        p.setPen(QtGui.QColor("#2a1f0c"))
        p.drawText(box, QtCore.Qt.AlignCenter, self.text())
        p.end()


class ArrowPush(VintagePush):
    """Poussoir vintage en relief portant une flèche gravée (gauche ou droite) :
    flèche bombée noire, arête claire en haut, ombre en bas ; enfoncé, elle
    descend avec le capuchon."""

    def __init__(self, direction, width=38, height=32, label=""):
        super().__init__("", width, height)
        self.direction = direction          # "left" ou "right"
        self.label = label                  # nom gravé à côté de la flèche (UP, DOWN…)

    def paintEvent(self, event):
        super().paintEvent(event)           # lunette, gorge, capuchon (sans texte)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        down = self.isDown()
        cx, cy = w / 2, h / 2 - 0.6 + (1.4 if down else 0)
        aw, ah = w * 0.19, h * 0.17                     # demi-largeur, demi-hauteur
        s = -1 if self.direction == "left" else 1
        if self.label:                      # flèche côté extérieur, nom à côté
            aw, ah = h * 0.24, h * 0.19
            cx = (14 + aw) if s < 0 else (w - 14 - aw)
            f = QtGui.QFont("DejaVu Sans", 8, QtGui.QFont.Bold)
            f.setPixelSize(max(8, int(h * 0.36)))
            p.setFont(f)
            text_r = QtCore.QRectF(0, 0, w, h).adjusted(
                (2 * aw + 16) if s < 0 else 8, 0, -8 if s < 0 else -(2 * aw + 16), 0)
            text_r.translate(0, -0.6 + (1.4 if down else 0))
            p.setPen(QtGui.QColor(255, 255, 255, 170))
            p.drawText(text_r.translated(0, 0.8), QtCore.Qt.AlignCenter, self.label)
            p.setPen(QtGui.QColor("#2a2114"))
            p.drawText(text_r, QtCore.Qt.AlignCenter, self.label)
        tri = QtGui.QPolygonF([QtCore.QPointF(cx + s * aw, cy),
                               QtCore.QPointF(cx - s * aw * 0.7, cy - ah),
                               QtCore.QPointF(cx - s * aw * 0.7, cy + ah)])
        # gravure : bord clair décalé vers le bas, ombre vers le haut
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 255, 255, 150))
        p.drawPolygon(tri.translated(0, 1.0))
        p.setBrush(QtGui.QColor(0, 0, 0, 90))
        p.drawPolygon(tri.translated(0, -0.6))
        # flèche bombée : noir profond en bas, gris acier en haut
        g = QtGui.QLinearGradient(0, cy - ah, 0, cy + ah)
        g.setColorAt(0, QtGui.QColor("#6a6d70" if not down else "#4a4c4e"))
        g.setColorAt(0.5, QtGui.QColor("#1c1d1f"))
        g.setColorAt(1, QtGui.QColor("#050505"))
        p.setBrush(g)
        p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 0.7))
        p.drawPolygon(tri)
        # petit reflet sur l'arête haute
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 110 if not down else 50), 0.9))
        p.drawLine(QtCore.QPointF(cx - s * aw * 0.55, cy - ah * 0.78),
                   QtCore.QPointF(cx + s * aw * 0.7, cy - ah * 0.08))
        p.end()
