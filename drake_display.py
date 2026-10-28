"""Affichage de fréquence et horloges façon Drake TR-7 : chiffres LED rouges à
7 segments derrière une vitre rouge foncé, dans un cadre gris anthracite
brossé à biseau chromé. Même fonctionnement que les tambours (drum_display) :
seul le dessin change. Les segments éteints restent visibles, très sombres."""

from PyQt5 import QtCore, QtGui

from drum_display import DrumClock, DrumDisplay

#        a
#      f   b
#        g
#      e   c
#        d
SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "-": "g", " ": "",
}
LIT = QtGui.QColor("#ff2a12")
OFF = QtGui.QColor(42, 6, 4)


def _seg_polys(r):
    """Les 7 segments (polygones biseautés) dans le rectangle r, légèrement penchés."""
    w, h = r.width(), r.height()
    t = max(2.0, w * 0.17)                      # épaisseur d'un segment
    x0, y0 = r.left(), r.top()
    slant = w * 0.12                            # chiffres penchés comme les LED

    def P(x, y):                                # point en coordonnées 0..1, penché
        return QtCore.QPointF(x0 + x * w + (1 - y) * slant - slant / 2, y0 + y * h)

    def horiz(y):
        a, b = t / w, t / (2 * h)
        return [P(a, y), P(a + b * h / w, y - b), P(1 - a - b * h / w, y - b),
                P(1 - a, y), P(1 - a - b * h / w, y + b), P(a + b * h / w, y + b)]

    def vert(x, y1, y2):
        a, b = t / (2 * w), t / h
        return [P(x, y1 + b * 0.6), P(x + a, y1 + b * 1.1), P(x + a, y2 - b * 1.1),
                P(x, y2 - b * 0.6), P(x - a, y2 - b * 1.1), P(x - a, y1 + b * 1.1)]

    hx = t / (2 * w)
    return {
        "a": horiz(t / (2 * h)), "g": horiz(0.5), "d": horiz(1 - t / (2 * h)),
        "f": vert(hx, 0.0, 0.5), "b": vert(1 - hx, 0.0, 0.5),
        "e": vert(hx, 0.5, 1.0), "c": vert(1 - hx, 0.5, 1.0),
    }


def paint_digit(p, r, ch, bright=1.0):
    polys = _seg_polys(r)
    lit = SEGMENTS.get(ch, "")
    p.setPen(QtCore.Qt.NoPen)
    for name, pts in polys.items():
        poly = QtGui.QPolygonF(pts)
        if name in lit:
            glow = QtGui.QColor(LIT)
            glow.setAlpha(int(70 * bright))
            p.setBrush(glow)                    # halo autour du segment allumé
            for dx, dy in ((-1.2, 0), (1.2, 0), (0, -1.2), (0, 1.2)):
                p.drawPolygon(poly.translated(dx, dy))
            c = QtGui.QColor(LIT)
            c.setAlphaF(min(1.0, 0.55 + 0.45 * bright))
            p.setBrush(c)
        else:
            p.setBrush(OFF)
        p.drawPolygon(poly)


def paint_dot(p, c, rad, on=True):
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(LIT if on else OFF)
    p.drawEllipse(c, rad, rad)


def paint_frame(p, rect):
    """Cadre gris Drake brossé, biseau chromé, vitre rouge foncé creusée.
    Renvoie le rectangle de la vitre."""
    r = QtCore.QRectF(rect).adjusted(1, 1, -2, -2)
    for i in range(4, 0, -1):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 34))
        p.drawRoundedRect(r.translated(i * 0.4, i * 0.6), 9, 9)
    g = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
    g.setColorAt(0, QtGui.QColor("#6a6e72"))
    g.setColorAt(0.5, QtGui.QColor("#45484c"))
    g.setColorAt(1, QtGui.QColor("#2c2e31"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#101112"), 1.2))
    p.drawRoundedRect(r, 9, 9)
    p.save()                                    # brossé horizontal
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(r, 9, 9)
    p.setClipPath(clip)
    for y in range(int(r.top()) + 2, int(r.bottom()) - 1, 2):
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 8 + (y * 7 % 9)), 0.6))
        p.drawLine(QtCore.QPointF(r.left(), y), QtCore.QPointF(r.right(), y))
    p.restore()
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 80), 1))
    p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 8, 8)
    # biseau chromé autour de la vitre
    bez = r.adjusted(6, 6, -6, -6)
    bg = QtGui.QLinearGradient(0, bez.top(), 0, bez.bottom())
    for stop, col in ((0, "#3a3c3a"), (0.5, "#bfc2be"), (1, "#f4f5f3")):
        bg.setColorAt(stop, QtGui.QColor(col))
    p.setBrush(bg)
    p.setPen(QtGui.QPen(QtGui.QColor("#0b0b0b"), 1))
    p.drawRoundedRect(bez, 6, 6)
    glass = bez.adjusted(3, 3, -3, -3)
    gg = QtGui.QLinearGradient(0, glass.top(), 0, glass.bottom())
    gg.setColorAt(0, QtGui.QColor("#070101"))
    gg.setColorAt(0.5, QtGui.QColor("#1c0403"))
    gg.setColorAt(1, QtGui.QColor("#0d0201"))
    p.setBrush(gg)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
    p.drawRoundedRect(glass, 4, 4)
    return glass


def paint_glass_reflection(p, glass):
    p.save()
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(glass, 4, 4)
    p.setClipPath(clip)
    gl = QtGui.QLinearGradient(0, glass.top(), 0, glass.center().y())
    gl.setColorAt(0, QtGui.QColor(255, 255, 255, 38))
    gl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.fillRect(QtCore.QRectF(glass.left(), glass.top(), glass.width(), glass.height() / 2), gl)
    p.restore()


class DrakeDisplay(DrumDisplay):
    """Fréquence en LED rouges (même interface que DrumDisplay)."""

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        glass = paint_frame(p, self.rect())
        bright = 0.75 + 0.25 * min(1.0, self.light)     # pompe en émission
        chars = self.chars
        n_dig = sum(1 for c in chars if c != ".")
        n_dot = len(chars) - n_dig
        pad = 10
        dot_w = glass.height() * 0.16
        dig_w = (glass.width() - 2 * pad - n_dot * dot_w) / max(1, n_dig)
        h = glass.height() * 0.72
        y = glass.top() + (glass.height() - h) / 2
        x = glass.left() + pad
        for c in chars:
            if c == ".":
                paint_dot(p, QtCore.QPointF(x + dot_w * 0.35, y + h * 0.97), h * 0.06)
                x += dot_w
                continue
            r = QtCore.QRectF(x + dig_w * 0.14, y, dig_w * 0.7, h)
            paint_digit(p, r, c if c.isdigit() or c == "-" else " ", bright)
            x += dig_w
        paint_glass_reflection(p, glass)
        p.end()


class DrakeClock(DrumClock):
    """Horloges LOCAL / TU en LED rouges (même interface que DrumClock)."""

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        glass = paint_frame(p, self.rect())
        half = glass.height() / 2
        f = QtGui.QFont("DejaVu Sans Condensed")
        f.setPixelSize(7)
        f.setWeight(QtGui.QFont.Black)
        for i, tag in enumerate(("LOCAL", "TU")):
            row = QtCore.QRectF(glass.left(), glass.top() + i * half, glass.width(), half)
            p.setFont(f)
            p.setPen(QtGui.QColor(255, 90, 60, 150))
            p.drawText(QtCore.QRectF(row.left() + 2, row.top(), 26, row.height()),
                       QtCore.Qt.AlignCenter, tag)
            digits = [str(int(round(v)) % 10) for v in self.row_goals[i]]
            area = row.adjusted(30, half * 0.14, -4, -half * 0.14)
            col_w = area.width() / 6.9
            x = area.left()
            for k, d in enumerate(digits):
                if k in (2, 4):                         # deux points entre HH:MM:SS
                    cx = x + col_w * 0.22
                    paint_dot(p, QtCore.QPointF(cx, area.top() + area.height() * 0.32), 1.2)
                    paint_dot(p, QtCore.QPointF(cx, area.top() + area.height() * 0.72), 1.2)
                    x += col_w * 0.45
                paint_digit(p, QtCore.QRectF(x + col_w * 0.1, area.top(), col_w * 0.78,
                                             area.height()), d)
                x += col_w
        paint_glass_reflection(p, glass)
        p.end()
