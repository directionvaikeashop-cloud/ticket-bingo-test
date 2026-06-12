# -*- coding: utf-8 -*-
"""
GENERATEUR OHANA 75 ORIGINAL (format carte application)
TUKEA — Ticket Bingo
1 page = 1 carte BINGO 5x5 paysage (130 x 92 mm), couleurs arc-en-ciel par carte.
Regle : colonnes B/I/N/G/O avec plages 1-15/16-30/31-45/46-60/61-75.
Chaque case = 1 numero cercle + 1 numero nu (10 numeros par colonne,
8 pour le N autour de la FREE SPACE centrale qui porte le numero de carte).
Mention MARATHON au-dessus du G. Valide par Maeva le 12/06/2026.
"""
import random
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    pdfmetrics.registerFont(TTFont('DJL', '/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf'))
    POLICE = 'DJL'
except Exception:
    POLICE = 'Helvetica'

PW, PH = 130 * mm, 92 * mm
NOIR = colors.black
GRIS = colors.Color(0.42, 0.42, 0.42)
GRISCLAIR = colors.Color(0.80, 0.80, 0.80)
ARCENCIEL = [
    colors.Color(0.85, 0.20, 0.25), colors.Color(0.90, 0.55, 0.10), colors.Color(0.72, 0.60, 0.05),
    colors.Color(0.15, 0.60, 0.35), colors.Color(0.20, 0.45, 0.85), colors.Color(0.45, 0.30, 0.75),
    colors.Color(0.80, 0.25, 0.65),
]
COLS = [("B", 1, 15), ("I", 16, 30), ("N", 31, 45), ("G", 46, 60), ("O", 61, 75)]


def _gen_carte(rng):
    carte = {}
    for lettre, a, b in COLS:
        nb = 8 if lettre == "N" else 10
        nums = rng.sample(range(a, b + 1), nb)
        carte[lettre] = tuple((nums[2 * i], nums[2 * i + 1]) for i in range(nb // 2))
    return carte


def _signature(carte):
    return tuple(carte[l] for l, _, _ in COLS)


def _draw_carte(cv, serial, carte, coul):
    M = 6 * mm
    cv.setFont(POLICE, 7.5)
    cv.setFillColor(GRIS)
    cv.drawCentredString(PW / 2, PH - 4.5 * mm, "OHANA 75  —  Carte %05d  —  TUKEA 89 22 23 05" % serial)
    top = PH - 8 * mm
    bot = M
    gw = (PW - 2 * M) / 5
    header_h = 10 * mm
    grid_top = top - header_h
    rh = (grid_top - bot) / 5
    cv.setStrokeColor(coul)
    cv.setLineWidth(1.4)
    cv.roundRect(M, bot, PW - 2 * M, top - bot, 3 * mm, fill=0, stroke=1)
    cv.setStrokeColor(GRISCLAIR)
    cv.setLineWidth(0.7)
    cv.line(M, grid_top, PW - M, grid_top)
    for ci in range(1, 5):
        x = M + ci * gw
        cv.setStrokeColor(GRISCLAIR)
        cv.setLineWidth(0.7)
        cv.line(x, grid_top, x, top)
        cv.setDash(2, 2)
        cv.setLineWidth(0.5)
        cv.line(x, bot, x, grid_top)
        cv.setDash()
    for ri in range(1, 5):
        y = bot + ri * rh
        cv.setStrokeColor(GRISCLAIR)
        cv.setDash(2, 2)
        cv.setLineWidth(0.5)
        cv.line(M, y, PW - M, y)
        cv.setDash()
    for ci, (lettre, a, b) in enumerate(COLS):
        cx = M + ci * gw + gw / 2
        cv.setFillColor(coul)
        if lettre == "G":
            cv.setFont(POLICE, 5.5)
            cv.setFillColor(GRIS)
            cv.drawCentredString(cx, top - 3.6 * mm, "MARATHON")
            cv.setFillColor(coul)
            cv.setFont(POLICE, 15)
            cv.drawCentredString(cx, top - 8.8 * mm, lettre)
        else:
            cv.setFont(POLICE, 17)
            cv.drawCentredString(cx, top - 8 * mm, lettre)
    for ci, (lettre, a, b) in enumerate(COLS):
        paires = carte[lettre]
        pi = 0
        for ri in range(5):
            cx0 = M + ci * gw
            cy = bot + (4 - ri) * rh + rh / 2
            if lettre == "N" and ri == 2:
                cv.setFillColor(GRIS)
                cv.setFont(POLICE, 7)
                cv.drawCentredString(cx0 + gw / 2, cy + 2.6 * mm, "FREE")
                cv.setFont(POLICE, 6.5)
                cv.drawCentredString(cx0 + gw / 2, cy - 0.4 * mm, "%05d" % serial)
                cv.setFont(POLICE, 7)
                cv.drawCentredString(cx0 + gw / 2, cy - 3.4 * mm, "SPACE")
                continue
            n1, n2 = paires[pi]
            pi += 1
            ccx = cx0 + gw * 0.30
            ccy = cy + rh * 0.12
            r = min(gw, rh) * 0.38
            cv.setStrokeColor(coul)
            cv.setLineWidth(1.0)
            cv.circle(ccx, ccy, r, fill=0, stroke=1)
            cv.setFillColor(NOIR)
            cv.setFont(POLICE, 16)
            t1 = str(n1)
            w1 = cv.stringWidth(t1, POLICE, 16)
            cv.drawString(ccx - w1 / 2, ccy - 5.5, t1)
            nx = cx0 + gw * 0.73
            ny = cy - rh * 0.18
            cv.setFillColor(NOIR)
            cv.setFont(POLICE, 20)
            t2 = str(n2)
            w2 = cv.stringWidth(t2, POLICE, 20)
            cv.drawString(nx - w2 / 2, ny - 7, t2)


def generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/OHANA_75_ORIGINAL.pdf"):
    """Genere nb_tickets cartes uniques (1 par page), serials a partir de serie_start."""
    nb_tickets = max(1, min(int(nb_tickets), 1000))
    serie_start = max(1, int(serie_start))
    rng = random.Random(750100 + serie_start)
    vus = set()
    cv = canvas.Canvas(output_path, pagesize=(PW, PH))
    produits = 0
    while produits < nb_tickets:
        carte = _gen_carte(rng)
        sig = _signature(carte)
        if sig in vus:
            continue
        vus.add(sig)
        serial = serie_start + produits
        _draw_carte(cv, serial, carte, ARCENCIEL[(serial - 1) % len(ARCENCIEL)])
        cv.showPage()
        produits += 1
    cv.save()
    return output_path
