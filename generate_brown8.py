# -*- coding: utf-8 -*-
"""
generate_brown8.py
Module de génération de tickets BROWN 8 BOULES — Ticket Bingo (TUKEA)

Grille 5 colonnes (B R O W N) × 3 rangées, motif en quinconce :
  - B, O, N : 2 numéros (rangées haut & bas)
  - R, W    : 1 numéro (rangée du milieu)
  - centre (O, milieu) : n° de série
Plages BINGO 75 : B 1-15, R 16-30, O 31-45, W 46-60, N 61-75.
8 numéros au total. 1 page = 1 ticket. Tickets uniques.
Chiffres NOIRS, encadrement COULEUR (arc-en-ciel par ticket), coins arrondis.

Usage:
    from generate_brown8 import generate_pdf
    path = generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/BROWN_8.pdf")
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

GRIS = colors.Color(0.42, 0.42, 0.42)
GRIS_CLAIR = colors.Color(0.80, 0.80, 0.80)

RAINBOW = [
    colors.HexColor('#E53935'), colors.HexColor('#FB8C00'), colors.HexColor('#F9A825'),
    colors.HexColor('#43A047'), colors.HexColor('#00ACC1'), colors.HexColor('#1E88E5'),
    colors.HexColor('#3949AB'), colors.HexColor('#8E24AA'), colors.HexColor('#D81B60'),
    colors.HexColor('#6D4C41'),
]

LETTRES = ["B", "R", "O", "W", "N"]
COUL_LETTRES = ["#5E8B7E", "#D98A3D", "#8A8A8A", "#8A8A8A", "#5E8B7E"]
PLAGES = {"B": (1, 15), "R": (16, 30), "O": (31, 45), "W": (46, 60), "N": (61, 75)}

CELL = 28 * mm
HEAD_H = 12 * mm
MARGIN = 6 * mm
CARD_W = 5 * CELL
CARD_H = HEAD_H + 3 * CELL
PAGE_W = CARD_W + 2 * MARGIN
PAGE_H = CARD_H + 2 * MARGIN


def _gen_nums(rng):
    """B/O/N : 2 numéros triés ; R/W : 1 numéro."""
    return {
        "B": sorted(rng.sample(range(1, 16), 2)),
        "R": [rng.randint(16, 30)],
        "O": sorted(rng.sample(range(31, 46), 2)),
        "W": [rng.randint(46, 60)],
        "N": sorted(rng.sample(range(61, 76), 2)),
    }


def _signature(nums):
    return tuple((l, tuple(nums[l])) for l in LETTRES)


def _draw_ticket(cv, serial, nums, accent, couleur=True):
    bord = accent if couleur else GRIS_CLAIR
    x0, y0 = MARGIN, MARGIN
    grid_top = y0 + 3 * CELL          # haut de la grille (sous l'en-tête)
    # colonne x : col 0..4
    def cx(col):
        return x0 + (col + 0.5) * CELL
    # rangée y centre : row 0=haut,1=milieu,2=bas
    def cy(row):
        return grid_top - (row + 0.5) * CELL

    # cadre extérieur arrondi en couleur
    cv.setStrokeColor(bord)
    cv.setLineWidth(2.2)
    cv.roundRect(x0, y0, CARD_W, 3 * CELL, 5 * mm, stroke=1, fill=0)

    # grille interne (lignes claires)
    cv.setStrokeColor(GRIS_CLAIR)
    cv.setLineWidth(0.5)
    for i in range(1, 5):
        cv.line(x0 + i * CELL, y0 + 4 * mm, x0 + i * CELL, grid_top - 4 * mm)
    for j in range(1, 3):
        yy = grid_top - j * CELL
        cv.line(x0 + 4 * mm, yy, x0 + CARD_W - 4 * mm, yy)

    # en-tête B R O W N
    for i, lettre in enumerate(LETTRES):
        cv.setFillColor(colors.HexColor(COUL_LETTRES[i]) if couleur else GRIS)
        cv.setFont(POLICE, 16)
        cv.drawCentredString(cx(i), grid_top + (HEAD_H - 16) / 2, lettre)

    # numéros en NOIR, motif quinconce
    cv.setFillColor(colors.black)
    cv.setFont(POLICE, 48)
    # B (col0) rangées haut/bas
    cv.drawCentredString(cx(0), cy(0) - 17, str(nums["B"][0]))
    cv.drawCentredString(cx(0), cy(2) - 17, str(nums["B"][1]))
    # O (col2) rangées haut/bas
    cv.drawCentredString(cx(2), cy(0) - 17, str(nums["O"][0]))
    cv.drawCentredString(cx(2), cy(2) - 17, str(nums["O"][1]))
    # N (col4) rangées haut/bas
    cv.drawCentredString(cx(4), cy(0) - 17, str(nums["N"][0]))
    cv.drawCentredString(cx(4), cy(2) - 17, str(nums["N"][1]))
    # R (col1) milieu / W (col3) milieu
    cv.drawCentredString(cx(1), cy(1) - 17, str(nums["R"][0]))
    cv.drawCentredString(cx(3), cy(1) - 17, str(nums["W"][0]))

    # n° de série au centre (O, milieu)
    cv.setFillColor(bord)
    cv.setFont(POLICE, 8)
    cv.drawCentredString(cx(2), cy(1) - 2, "%06d" % serial)


def generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/BROWN_8.pdf", couleur=True):
    """Génère nb_tickets tickets BROWN 8 BOULES uniques. couleur=False => Noir & Blanc."""
    nb_tickets = max(1, min(int(nb_tickets), 1000))
    serie_start = max(1, int(serie_start))
    rng = random.Random(753000 + serie_start)
    vus = set()
    cv = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))
    produits = 0
    while produits < nb_tickets:
        nums = _gen_nums(rng)
        sig = _signature(nums)
        if sig in vus:
            continue
        vus.add(sig)
        serial = serie_start + produits
        _draw_ticket(cv, serial, nums, RAINBOW[(serial - 1) % len(RAINBOW)], couleur)
        cv.showPage()
        produits += 1
    cv.save()
    return output_path


def generate_pdf_nb(nb_tickets=500, serie_start=1, output_path="/data/BROWN_8_NB.pdf"):
    """Version Noir & Blanc (économe en encre)."""
    return generate_pdf(nb_tickets, serie_start, output_path, couleur=False)


if __name__ == "__main__":
    generate_pdf(nb_tickets=4, serie_start=1, output_path="brown8_test.pdf")
    print("BROWN 8 BOULES généré")
