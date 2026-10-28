"""Ensemble VFO façon Collins KWM-2 (d'après la photo du poste) : plaque
noire vissée, fenêtre en arc rétroéclairée avec l'échelle des kHz qui défile
sous un fil rouge, plaquette d'indicatif, et gros bouton d'accord : jupe en
bakélite festonnée, disque d'aluminium poli, manivelle à boule.
Dessin prévu pour 380 × 470 (le widget peut être agrandi ou réduit)."""

import math

from PyQt5 import QtCore, QtGui

W, H = 380, 470
KNOB_C = QtCore.QPointF(190, 342)       # centre du bouton
KNOB_R = 118
ARC_C = QtCore.QPointF(190, 402)        # centre de l'arc de l'échelle
ARC_OUT, ARC_IN = 318, 226
ARC_SPAN = 31                           # demi-ouverture de la fenêtre (degrés)
DEG_PER_KHZ = 1.55


def _plate_path():
    """Plaque noire : large en haut (fenêtre), plus étroite autour du bouton."""
    top = QtGui.QPainterPath()
    top.addRoundedRect(QtCore.QRectF(6, 34, W - 12, 230), 26, 26)
    low = QtGui.QPainterPath()
    low.addRoundedRect(QtCore.QRectF(46, 150, W - 92, H - 156), 30, 30)
    mid = QtGui.QPainterPath()
    mid.moveTo(6, 230)
    mid.lineTo(W - 6, 230)
    mid.lineTo(W - 46, 300)
    mid.lineTo(46, 300)
    mid.closeSubpath()
    return top.united(low).united(mid).simplified()


def _window_path():
    path = QtGui.QPainterPath()
    a0, a1 = 90 - ARC_SPAN, 90 + ARC_SPAN       # angles Qt (0° à droite, sens trigo)
    out = QtCore.QRectF(ARC_C.x() - ARC_OUT, ARC_C.y() - ARC_OUT, 2 * ARC_OUT, 2 * ARC_OUT)
    inn = QtCore.QRectF(ARC_C.x() - ARC_IN, ARC_C.y() - ARC_IN, 2 * ARC_IN, 2 * ARC_IN)
    path.arcMoveTo(out, a0)
    path.arcTo(out, a0, a1 - a0)
    path.arcTo(inn, a1, -(a1 - a0))
    path.closeSubpath()
    return path


def _polar(c, r, deg_from_top):
    a = math.radians(deg_from_top)
    return c + QtCore.QPointF(math.sin(a) * r, -math.cos(a) * r)


def _screw(p, c, r=7):
    g = QtGui.QRadialGradient(c - QtCore.QPointF(2, 2), r * 1.4)
    g.setColorAt(0, QtGui.QColor("#5a5a5a"))
    g.setColorAt(1, QtGui.QColor("#0c0c0c"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
    p.drawEllipse(c, r, r)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.8))           # tête cruciforme
    p.drawLine(c + QtCore.QPointF(-r * 0.6, 0), c + QtCore.QPointF(r * 0.6, 0))
    p.drawLine(c + QtCore.QPointF(0, -r * 0.6), c + QtCore.QPointF(0, r * 0.6))
    p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 60), 0.8))
    p.drawArc(QtCore.QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 60 * 16, 90 * 16)


def paint_kwm2(p, khz_shown, angle, hooked=False, callsign="F4TXR"):
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    plate = _plate_path()
    # ombre portée de la plaque sur la façade
    for i in range(10, 0, -1):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 16))
        p.drawPath(plate.translated(i * 0.5, i * 0.9))
    g = QtGui.QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QtGui.QColor("#2c2c2c"))
    g.setColorAt(0.4, QtGui.QColor("#121212"))
    g.setColorAt(1, QtGui.QColor("#050505"))
    p.setBrush(g)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.5))
    p.drawPath(plate)
    p.setBrush(QtCore.Qt.NoBrush)                                  # arête de la plaque
    edge = QtGui.QLinearGradient(0, 30, 0, H)
    edge.setColorAt(0, QtGui.QColor(255, 255, 255, 80))
    edge.setColorAt(0.3, QtGui.QColor(255, 255, 255, 15))
    edge.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.setPen(QtGui.QPen(QtGui.QBrush(edge), 2))
    p.drawPath(plate.translated(1, 1))
    _screw(p, QtCore.QPointF(70, 64))
    _screw(p, QtCore.QPointF(W - 120, 64))
    # petit bouton de blocage en haut à droite (cylindre noir)
    lc = QtCore.QPointF(W - 44, 66)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 120))
    p.drawEllipse(lc + QtCore.QPointF(3, 5), 22, 22)
    cyl = QtGui.QLinearGradient(lc.x() - 22, 0, lc.x() + 22, 0)
    cyl.setColorAt(0, QtGui.QColor("#3a3a3a"))
    cyl.setColorAt(0.35, QtGui.QColor("#161616"))
    cyl.setColorAt(1, QtGui.QColor("#020202"))
    p.setBrush(cyl)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
    p.drawEllipse(lc, 21, 21)
    hl = QtGui.QRadialGradient(lc - QtCore.QPointF(7, 8), 10)
    hl.setColorAt(0, QtGui.QColor(255, 255, 255, 90))
    hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.setBrush(hl)
    p.setPen(QtCore.Qt.NoPen)
    p.drawEllipse(lc - QtCore.QPointF(7, 8), 10, 8)

    # fenêtre en arc : creux, échelle crème rétroéclairée
    win = _window_path()
    p.setBrush(QtGui.QColor("#000"))
    p.setPen(QtCore.Qt.NoPen)
    p.drawPath(win.translated(0, -3))
    p.save()
    p.setClipPath(win)
    light = QtGui.QRadialGradient(QtCore.QPointF(W / 2, 150), 210)
    light.setColorAt(0, QtGui.QColor("#fbf3dc"))
    light.setColorAt(0.6, QtGui.QColor("#eadfbe"))
    light.setColorAt(1, QtGui.QColor("#b8a77c"))
    p.setBrush(light)
    p.drawRect(QtCore.QRectF(0, 0, W, H))
    # échelle : un cran par kHz, chiffres tous les 10 kHz
    first = int(khz_shown - ARC_SPAN / DEG_PER_KHZ) - 2
    last = int(khz_shown + ARC_SPAN / DEG_PER_KHZ) + 2
    fnum = QtGui.QFont("DejaVu Sans", 10)
    fnum.setPixelSize(27)
    p.setFont(fnum)
    for k in range(first, last + 1):
        deg = (k - khz_shown) * DEG_PER_KHZ
        if k % 10 == 0:                               # plage claire sous les chiffres
            p.save()
            p.translate(ARC_C)
            p.rotate(deg)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 250, 140))
            p.drawRect(QtCore.QRectF(-26, -ARC_IN - 52, 52, 40))
            p.restore()
        long = 34 if k % 10 == 0 else 24 if k % 5 == 0 else 15
        width = 2.6 if k % 10 == 0 else 1.6
        p.setPen(QtGui.QPen(QtGui.QColor("#2a2620"), width))
        p.drawLine(_polar(ARC_C, ARC_OUT - 8, deg), _polar(ARC_C, ARC_OUT - 8 - long, deg))
        if k % 10 == 0:
            p.save()
            p.translate(_polar(ARC_C, ARC_IN + 30, deg))
            p.rotate(deg)
            p.setPen(QtGui.QColor("#3a352c"))
            p.drawText(QtCore.QRectF(-40, -16, 80, 32), QtCore.Qt.AlignCenter,
                       f"{k % 1000:03d}")
            p.restore()
    # ombre de la vitre aux bords de la fenêtre
    for k in range(10):
        p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, int(70 * (1 - k / 10))), 1.4))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawPath(win.translated(0, k * 0.6))
    p.restore()
    # fil rouge
    p.setPen(QtGui.QPen(QtGui.QColor(200, 25, 15), 1.6))
    p.drawLine(_polar(ARC_C, ARC_OUT + 2, 0), _polar(ARC_C, ARC_IN - 2, 0))
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 200), 2.2))
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawPath(win)
    # plaquette d'indicatif (noire, lettres blanches en relief)
    tag = QtCore.QRectF(W / 2 - 62, 186, 124, 36)
    p.setBrush(QtGui.QColor("#050505"))
    p.setPen(QtGui.QPen(QtGui.QColor("#4a4a4a"), 1.2))
    p.drawRoundedRect(tag, 4, 4)
    ft = QtGui.QFont("DejaVu Sans", 10, QtGui.QFont.Bold)
    ft.setPixelSize(25)
    p.setFont(ft)
    p.setPen(QtGui.QColor(0, 0, 0))
    p.drawText(tag.translated(1, 1.5), QtCore.Qt.AlignCenter, callsign)
    p.setPen(QtGui.QColor("#f4f4f0"))
    p.drawText(tag, QtCore.Qt.AlignCenter, callsign)

    _knob(p, angle, hooked)
    p.restore()


def _knob(p, angle, hooked):
    c, R = KNOB_C, KNOB_R
    lobes = 9

    def skirt_path(scale=1.0, grow=0.0):
        path = QtGui.QPainterPath()
        for i in range(361):
            t = math.radians(i)
            bump = 0.5 + 0.5 * math.cos(lobes * (t - math.radians(angle)))
            r = (R * (0.86 + 0.14 * bump ** 0.5) + grow) * scale
            pt = c + QtCore.QPointF(math.cos(t) * r, math.sin(t) * r)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        return path

    # ombre portée du bouton sur la plaque
    for i in range(22, 0, -1):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 22))
        p.drawPath(skirt_path(grow=i * 0.45).translated(i * 0.7, i * 1.2))
    if hooked:                                       # tenu à la souris : lueur ambre
        glow = QtGui.QRadialGradient(c, R + 14)
        glow.setColorAt(0.85, QtGui.QColor(255, 190, 90, 0))
        glow.setColorAt(0.94, QtGui.QColor(255, 190, 90, 130))
        glow.setColorAt(1, QtGui.QColor(255, 190, 90, 0))
        p.setBrush(glow)
        p.drawEllipse(c, R + 14, R + 14)
    # jupe festonnée en bakélite noire
    sk = QtGui.QConicalGradient(c, 125)
    for stop, col in ((0, "#4a4a4a"), (0.1, "#151515"), (0.35, "#0a0a0a"),
                      (0.5, "#030303"), (0.7, "#1a1a1a"), (0.9, "#0b0b0b"), (1, "#4a4a4a")):
        sk.setColorAt(stop, QtGui.QColor(col))
    p.setBrush(sk)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1.2))
    p.drawPath(skirt_path())
    # reflets sur les festons (côté lumière)
    for i in range(lobes):
        t = math.radians(angle + i * 360 / lobes)
        light = 0.5 + 0.5 * math.cos(t - math.radians(-130))
        if light < 0.25:
            continue
        pt = c + QtCore.QPointF(math.cos(t), math.sin(t)) * R * 0.86
        hl = QtGui.QRadialGradient(pt, R * 0.16)
        hl.setColorAt(0, QtGui.QColor(255, 255, 255, int(120 * light ** 2)))
        hl.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(hl)
        p.drawEllipse(pt, R * 0.16, R * 0.12)
    # arête de lumière sur le pourtour de la jupe (haut gauche) + ombre (bas droit)
    rim = QtGui.QConicalGradient(c, 135)
    rim.setColorAt(0, QtGui.QColor(255, 255, 255, 150))
    rim.setColorAt(0.2, QtGui.QColor(255, 255, 255, 0))
    rim.setColorAt(0.45, QtGui.QColor(0, 0, 0, 0))
    rim.setColorAt(0.55, QtGui.QColor(0, 0, 0, 200))
    rim.setColorAt(0.7, QtGui.QColor(0, 0, 0, 0))
    rim.setColorAt(0.8, QtGui.QColor(255, 255, 255, 0))
    rim.setColorAt(1, QtGui.QColor(255, 255, 255, 150))
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(QtGui.QBrush(rim), 2.5))
    p.drawPath(skirt_path(scale=0.985))
    # gorge sombre autour du gradin (profondeur)
    p.setPen(QtCore.Qt.NoPen)
    gorge = QtGui.QRadialGradient(c, R * 0.8)
    gorge.setColorAt(0.85, QtGui.QColor(0, 0, 0, 0))
    gorge.setColorAt(0.93, QtGui.QColor(0, 0, 0, 200))
    gorge.setColorAt(1, QtGui.QColor(0, 0, 0, 0))
    p.setBrush(gorge)
    p.drawEllipse(c, R * 0.8, R * 0.8)
    # gradin bombé entre la jupe et le disque d'aluminium
    step = QtGui.QRadialGradient(c - QtCore.QPointF(R * 0.25, R * 0.3), R * 0.95)
    step.setColorAt(0, QtGui.QColor("#3a3a3a"))
    step.setColorAt(0.6, QtGui.QColor("#121212"))
    step.setColorAt(1, QtGui.QColor("#000"))
    p.setBrush(step)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
    p.drawEllipse(c, R * 0.74, R * 0.74)
    # disque d'aluminium poli (tourné) : reflets en secteurs + trait de lumière
    ar = R * 0.6
    for i in range(6, 0, -1):
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(0, 0, 0, 40))
        p.drawEllipse(c + QtCore.QPointF(i * 0.6, i * 1.0), ar, ar)
    al = QtGui.QConicalGradient(c, 45)
    for stop, col in ((0, "#f2f2f0"), (0.12, "#8c8e8c"), (0.25, "#d6d7d5"),
                      (0.37, "#5e605e"), (0.5, "#e9eae8"), (0.62, "#7d7f7d"),
                      (0.75, "#c8c9c7"), (0.87, "#5a5c5a"), (1, "#f2f2f0")):
        al.setColorAt(stop, QtGui.QColor(col))
    p.setBrush(al)
    p.setPen(QtGui.QPen(QtGui.QColor("#1a1a1a"), 1.2))
    p.drawEllipse(c, ar, ar)
    p.save()
    clip = QtGui.QPainterPath()
    clip.addEllipse(c, ar - 1, ar - 1)
    p.setClipPath(clip)
    p.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0, 22), 0.8))   # stries du tournage
    for k in range(4, int(ar), 3):
        p.drawEllipse(c, k, k)
    streak = QtGui.QLinearGradient(c + QtCore.QPointF(-ar, -ar), c + QtCore.QPointF(ar, ar))
    streak.setColorAt(0.44, QtGui.QColor(255, 255, 255, 0))
    streak.setColorAt(0.5, QtGui.QColor(255, 255, 255, 150))
    streak.setColorAt(0.56, QtGui.QColor(255, 255, 255, 0))
    p.setBrush(streak)
    p.setPen(QtCore.Qt.NoPen)
    p.drawEllipse(c, ar, ar)
    p.restore()
    # manivelle à boule, sur la jupe, tourne avec le bouton
    a = math.radians(angle - 125)
    hc = c + QtCore.QPointF(math.cos(a), math.sin(a)) * R * 0.66
    hr = R * 0.26
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 150))
    for i in range(10, 0, -1):
        p.setBrush(QtGui.QColor(0, 0, 0, 26))
        p.drawEllipse(hc + QtCore.QPointF(i * 0.9, i * 1.5), hr * (1 + i * 0.02), hr * (1 + i * 0.02))
    base = QtGui.QRadialGradient(hc - QtCore.QPointF(hr * 0.3, hr * 0.3), hr * 1.5)
    base.setColorAt(0, QtGui.QColor("#2e2e2e"))
    base.setColorAt(1, QtGui.QColor("#020202"))
    p.setBrush(base)
    p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
    p.drawEllipse(hc, hr, hr)
    ball_c = hc - QtCore.QPointF(hr * 0.12, hr * 0.16)
    br = hr * 0.72
    ball = QtGui.QRadialGradient(ball_c - QtCore.QPointF(br * 0.35, br * 0.4), br * 1.3)
    ball.setColorAt(0, QtGui.QColor("#5a5a5a"))
    ball.setColorAt(0.35, QtGui.QColor("#1b1b1b"))
    ball.setColorAt(1, QtGui.QColor("#000"))
    p.setBrush(ball)
    p.drawEllipse(ball_c, br, br)
    spot = QtGui.QRadialGradient(ball_c - QtCore.QPointF(br * 0.35, br * 0.42), br * 0.3)
    spot.setColorAt(0, QtGui.QColor(255, 255, 255, 220))
    spot.setColorAt(1, QtGui.QColor(255, 255, 255, 0))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(spot)
    p.drawEllipse(ball_c - QtCore.QPointF(br * 0.35, br * 0.42), br * 0.3, br * 0.26)
