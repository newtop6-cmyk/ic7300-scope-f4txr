"""VFO façon Drake (TR-4 / R-4) pour l'écran MOBILE : façade gris anthracite
brossée, fenêtre de cadran rectangulaire rétroéclairée où l'échelle des kHz
défile sous un fil rouge, et gros bouton noir à jupe chromée moletée et
graduée 0–100, avec creux pour le doigt. Même géométrie que kwm2_vfo
(W × H, centre du bouton KNOB_C) : seul le dessin change."""

import math

from PyQt5 import QtCore, QtGui

from kwm2_vfo import H, KNOB_C, W, _screw

KNOB_R = 124
WIN = QtCore.QRectF(34, 38, W - 68, 118)       # fenêtre du cadran
PX_PER_KHZ = 9.0                                # défilement de l'échelle


def _panel(p):
    r = QtCore.QRectF(4, 4, W - 8, H - 8)
    for i in range(10, 0, -1):                  # ombre portée sur la façade
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 15))
        p.drawRoundedRect(r.translated(i * 0.5, i * 0.9), 22, 22)
    g = QtGui.QLinearGradient(0, 0, 0, H)
    g.setColorAt(0, QtGui.QColor("#55595d"))
    g.setColorAt(0.5, QtGui.QColor("#3b3e42"))
    g.setColorAt(1, QtGui.QColor("#2a2c2f"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#121314"), 1.6))
    p.drawRoundedRect(r, 22, 22)
    p.save()                                    # métal brossé horizontal
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(r, 22, 22)
    p.setClipPath(clip)
    for y in range(6, H - 6, 2):
        a = 10 + (y * 37 % 11)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, a // 2), 0.6))
        p.drawLine(QtCore.QPointF(6, y), QtCore.QPointF(W - 6, y))
    p.restore()
    p.setBrush(QtCore.Qt.NoBrush)               # arête de lumière en haut
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 70), 1.2))
    p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 20, 20)
    for c in ((24, 24), (W - 24, 24), (24, H - 24), (W - 24, H - 24)):
        _screw(p, QtCore.QPointF(*c), 6)


def _dial(p, khz_shown):
    # cadre chromé de la fenêtre
    frame = WIN.adjusted(-7, -7, 7, 7)
    g = QtGui.QLinearGradient(0, frame.top(), 0, frame.bottom())
    for stop, col in ((0, "#f4f5f3"), (0.25, "#9c9f9b"), (0.5, "#e2e4e0"),
                      (0.75, "#6f726e"), (1, "#c9cbc7")):
        g.setColorAt(stop, QtGui.QColor(col))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1))
    p.drawRoundedRect(frame, 12, 12)
    # verre rétroéclairé (blanc chaud teinté vert, comme les Drake)
    bg = QtGui.QLinearGradient(0, WIN.top(), 0, WIN.bottom())
    bg.setColorAt(0, QtGui.QColor("#dfe9c8"))
    bg.setColorAt(0.5, QtGui.QColor("#f6f8e6"))
    bg.setColorAt(1, QtGui.QColor("#c7d6a8"))
    p.setBrush(bg)
    p.setPen(QtGui.QPen(QtGui.QColor("#0b0b0b"), 1.4))
    p.drawRoundedRect(WIN, 8, 8)
    p.save()
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(WIN.adjusted(1, 1, -1, -1), 8, 8)
    p.setClipPath(clip)
    cx = WIN.center().x()
    base_y = WIN.top() + 64
    first = int(khz_shown - (WIN.width() / 2) / PX_PER_KHZ) - 1
    last = int(khz_shown + (WIN.width() / 2) / PX_PER_KHZ) + 2
    f_big = QtGui.QFont("DejaVu Sans", 1)
    f_big.setPixelSize(30)
    f_big.setWeight(QtGui.QFont.Bold)
    for k in range(first, last + 1):            # graduations tous les kHz
        x = cx + (k - khz_shown) * PX_PER_KHZ
        if k % 5 == 0:
            p.setPen(QtGui.QPen(QtGui.QColor("#14110c"), 2.2))
            p.drawLine(QtCore.QPointF(x, base_y), QtCore.QPointF(x, base_y + 30))
            if k % 10 == 0:
                p.setFont(f_big)
                txt = f"{k % 1000:03d}"
                rect = QtCore.QRectF(x - 40, WIN.top() + 14, 80, 40)
                p.drawText(rect, QtCore.Qt.AlignCenter, txt)
        else:
            p.setPen(QtGui.QPen(QtGui.QColor("#2b261d"), 1.1))
            p.drawLine(QtCore.QPointF(x, base_y + 10), QtCore.QPointF(x, base_y + 30))
    p.setPen(QtGui.QPen(QtGui.QColor("#2b261d"), 1.4))
    p.drawLine(QtCore.QPointF(WIN.left(), base_y + 30), QtCore.QPointF(WIN.right(), base_y + 30))
    # assombrissement des bords (le verre est éclairé par le centre)
    for side in (0, 1):
        sh = QtGui.QLinearGradient(WIN.left() if side == 0 else WIN.right(), 0, cx, 0)
        sh.setColorAt(0, QtGui.QColor(20, 26, 10, 150))
        sh.setColorAt(0.45, QtGui.QColor(20, 26, 10, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(sh)
        p.drawRect(WIN)
    # fil rouge
    p.setPen(QtGui.QPen(QtGui.QColor("#d01010"), 2.2))
    p.drawLine(QtCore.QPointF(cx, WIN.top() + 4), QtCore.QPointF(cx, WIN.bottom() - 4))
    # reflet du verre
    gl = QtGui.QLinearGradient(0, WIN.top(), 0, WIN.top() + 50)
    gl.setColorAt(0, QtGui.QColor(255, 255, 255, 110))
    gl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.setBrush(gl)
    p.setPen(QtCore.Qt.NoPen)
    p.drawRoundedRect(QtCore.QRectF(WIN.left() + 6, WIN.top() + 3, WIN.width() - 12, 40), 6, 6)
    p.restore()


def _plaque(p, callsign):
    r = QtCore.QRectF(W / 2 - 62, WIN.bottom() + 12, 124, 26)
    g = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
    g.setColorAt(0, QtGui.QColor("#1b1c1e"))
    g.setColorAt(1, QtGui.QColor("#050506"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#8e918d"), 1.2))
    p.drawRoundedRect(r, 5, 5)
    f = QtGui.QFont("DejaVu Sans", 1)
    f.setPixelSize(17)
    f.setWeight(QtGui.QFont.Black)
    f.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 3)
    p.setFont(f)
    p.setPen(QtGui.QColor("#e8e6dc"))
    p.drawText(r, QtCore.Qt.AlignCenter, callsign)


def _knob(p, angle, hooked):
    c, R = KNOB_C, KNOB_R
    for i in range(14, 0, -1):                  # ombre portée
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 18))
        p.drawEllipse(c + QtCore.QPointF(i * 0.7, i * 1.2), R + i * 0.4, R + i * 0.4)
    if hooked:                                  # pris : lueur ambre
        halo = QtGui.QRadialGradient(c, R + 16)
        halo.setColorAt(0.85, QtGui.QColor(255, 170, 40, 120))
        halo.setColorAt(1, QtGui.QColor(255, 170, 40, 0))
        p.setBrush(halo)
        p.drawEllipse(c, R + 16, R + 16)
    # jupe chromée (dégradé conique fixe = la lumière ne tourne pas)
    sk = QtGui.QConicalGradient(c, 120)
    for stop, col in ((0, "#ffffff"), (0.1, "#b4b7b3"), (0.25, "#5c5f5b"),
                      (0.42, "#d9dbd7"), (0.58, "#6a6d69"), (0.75, "#e6e8e4"),
                      (0.9, "#8d908c"), (1, "#ffffff")):
        sk.setColorAt(stop, QtGui.QColor(col))
    p.setBrush(sk)
    p.setPen(QtGui.QPen(QtGui.QColor("#111"), 1.4))
    p.drawEllipse(c, R, R)
    # moletage du bord et graduations 0–100 : tournent avec le bouton
    p.save()
    p.translate(c)
    p.rotate(angle)
    p.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20, 150), 1.0))
    for k in range(120):
        a = math.radians(k * 3)
        u = QtCore.QPointF(math.sin(a), -math.cos(a))
        p.drawLine(u * (R - 5), u * (R - 0.8))
    f = QtGui.QFont("DejaVu Sans Condensed", 1)
    f.setPixelSize(13)
    f.setWeight(QtGui.QFont.Bold)
    p.setFont(f)
    for k in range(100):
        a = math.radians(k * 3.6)
        u = QtCore.QPointF(math.sin(a), -math.cos(a))
        long_ = k % 10 == 0
        p.setPen(QtGui.QPen(QtGui.QColor("#141414"), 1.6 if long_ else 0.9))
        p.drawLine(u * (R - 8), u * (R - (20 if long_ else 13)))
        if long_:
            p.save()
            p.translate(u * (R - 31))
            p.rotate(k * 3.6)
            p.setPen(QtGui.QColor("#101010"))
            p.drawText(QtCore.QRectF(-14, -8, 28, 16), QtCore.Qt.AlignCenter, str(k))
            p.restore()
    p.restore()
    # gorge sombre entre la jupe et le bouton noir
    rk = R * 0.62
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 160))
    p.drawEllipse(c + QtCore.QPointF(1.5, 3), rk + 4, rk + 4)
    # bouton noir bombé
    g = QtGui.QRadialGradient(c - QtCore.QPointF(rk * 0.35, rk * 0.45), rk * 1.5)
    g.setColorAt(0, QtGui.QColor("#4a4b4d"))
    g.setColorAt(0.4, QtGui.QColor("#161718"))
    g.setColorAt(1, QtGui.QColor("#020202"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.2))
    p.drawEllipse(c, rk, rk)
    # cannelures fines sur le flanc du bouton noir (tournent)
    p.save()
    p.translate(c)
    p.rotate(angle)
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 28), 1.0))
    for k in range(48):
        a = math.radians(k * 7.5)
        u = QtCore.QPointF(math.sin(a), -math.cos(a))
        p.drawLine(u * (rk - 9), u * (rk - 1.5))
    # creux pour le doigt, décentré, et index blanc
    d = QtCore.QPointF(0, -rk * 0.48)
    dr = rk * 0.24
    dg = QtGui.QRadialGradient(d + QtCore.QPointF(dr * 0.3, dr * 0.35), dr * 1.2)
    dg.setColorAt(0, QtGui.QColor("#262728"))
    dg.setColorAt(1, QtGui.QColor("#000"))
    p.setBrush(dg)
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 45), 0.8))
    p.drawEllipse(d, dr, dr)
    p.setPen(QtGui.QPen(QtGui.QColor("#f2f0e6"), 3.0, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
    p.drawLine(QtCore.QPointF(0, -rk + 4), QtCore.QPointF(0, -rk + 18))
    p.restore()
    # reflet fixe sur le dôme
    hl = QtGui.QRadialGradient(c - QtCore.QPointF(rk * 0.38, rk * 0.46), rk * 0.5)
    hl.setColorAt(0, QtGui.QColor(255, 255, 255, 90))
    hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(hl)
    p.drawEllipse(c, rk, rk)
    # repère fixe en haut de la jupe (triangle blanc gravé sur la façade)
    tip = c + QtCore.QPointF(0, -R - 3)
    tri = QtGui.QPolygonF([tip, tip + QtCore.QPointF(-7, -12), tip + QtCore.QPointF(7, -12)])
    p.setBrush(QtGui.QColor("#f0eee4"))
    p.setPen(QtGui.QPen(QtGui.QColor("#111"), 0.8))
    p.drawPolygon(tri)


def paint_drake(p, khz_shown, angle, hooked=False, callsign="F4TXR"):
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    _panel(p)
    _dial(p, khz_shown)
    _plaque(p, callsign)
    _knob(p, angle, hooked)
    p.restore()
