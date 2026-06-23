# -*- coding: utf-8 -*-
"""
generate_kai.py
Module de génération de tickets KAI (7 boules) — Ticket Bingo (TUKEA)

Grille 3×3, colonnes 1-10 / 11-20 / 21-30.
2 cases barrées (X) : haut-droite et bas-gauche.
  - col0 (1-10)  : 2 numéros (rangées haut & milieu)   ; X en bas
  - col1 (11-20) : 3 numéros (toutes les rangées)
  - col2 (21-30) : 2 numéros (rangées milieu & bas)     ; X en haut
7 numéros au total. 1 page = 1 ticket. Tickets uniques.
Chiffres NOIRS, encadrement COULEUR (arc-en-ciel par ticket), coins arrondis.

Usage:
    from generate_kai import generate_pdf
    path = generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/KAI.pdf")
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

CELL = 36 * mm
HEAD_H = 13 * mm
FOOT_H = 10 * mm
MARGIN = 6 * mm
CARD_W = 3 * CELL
CARD_H = HEAD_H + 3 * CELL + FOOT_H
PAGE_W = CARD_W + 2 * MARGIN
PAGE_H = CARD_H + 2 * MARGIN


def _gen_nums(rng):
    """Retourne la grille 3×3 (None = case barrée X)."""
    c0 = sorted(rng.sample(range(1, 11), 2))    # rangées haut, milieu
    c1 = sorted(rng.sample(range(11, 21), 3))   # 3 rangées
    c2 = sorted(rng.sample(range(21, 31), 2))   # rangées milieu, bas
    # grille[row][col] ; X = None
    grille = [
        [c0[0], c1[0], None],   # haut : X en col2
        [c0[1], c1[1], c2[0]],  # milieu
        [None,  c1[2], c2[1]],  # bas : X en col0
    ]
    return grille


def _signature(grille):
    return tuple(tuple(("X" if v is None else v) for v in row) for row in grille)


def _draw_ticket(cv, serial, grille, accent, couleur=True):
    bord = accent if couleur else GRIS_CLAIR
    x0, y0 = MARGIN, MARGIN + FOOT_H
    grid_top = y0 + 3 * CELL

    def cx(col):
        return x0 + (col + 0.5) * CELL

    def cy(row):
        return grid_top - (row + 0.5) * CELL

    # cadre extérieur arrondi (couleur)
    cv.setStrokeColor(bord)
    cv.setLineWidth(2.2)
    cv.roundRect(MARGIN, MARGIN, CARD_W, HEAD_H + 3 * CELL + FOOT_H, 5 * mm, stroke=1, fill=0)

    # grille interne (3×3, lignes claires)
    cv.setStrokeColor(GRIS_CLAIR)
    cv.setLineWidth(0.5)
    for i in range(1, 3):
        cv.line(x0 + i * CELL, y0 + 2 * mm, x0 + i * CELL, grid_top - 2 * mm)
    for j in range(1, 3):
        yy = grid_top - j * CELL
        cv.line(x0 + 2 * mm, yy, x0 + CARD_W - 2 * mm, yy)
    # ligne sous l'en-tête et au-dessus du pied
    cv.line(MARGIN + 3 * mm, grid_top, MARGIN + CARD_W - 3 * mm, grid_top)
    cv.line(MARGIN + 3 * mm, y0, MARGIN + CARD_W - 3 * mm, y0)

    # en-tête
    cv.setFillColor(bord)
    cv.setFont(POLICE, 9.5)
    cv.drawCentredString(MARGIN + CARD_W / 2, grid_top + (HEAD_H - 9) / 2,
                         "Le jeux KAI pour 7 boules by TUKEA 89 22 23 05")

    # numéros (noir) ou X (gris clair)
    for r in range(3):
        for c in range(3):
            v = grille[r][c]
            if v is None:
                # case barrée X
                cv.setStrokeColor(GRIS_CLAIR)
                cv.setLineWidth(1.0)
                m = 9 * mm
                xa, ya = x0 + c * CELL + m, grid_top - r * CELL - m
                xb, yb = x0 + (c + 1) * CELL - m, grid_top - (r + 1) * CELL + m
                cv.line(xa, ya, xb, yb)
                cv.line(xa, yb, xb, ya)
            else:
                cv.setFillColor(colors.black)
                cv.setFont(POLICE, 46)
                cv.drawCentredString(cx(c), cy(r) - 16, str(v))

    # pied : N° SERIE + numéro
    cv.setFillColor(GRIS_CLAIR)
    cv.setFont(POLICE, 8)
    cv.drawString(MARGIN + 5 * mm, MARGIN + FOOT_H / 2 - 3, "N° SERIE")
    cv.setFillColor(bord)
    cv.setFont(POLICE, 12)
    cv.drawRightString(MARGIN + CARD_W - 5 * mm, MARGIN + FOOT_H / 2 - 4, "%06d" % serial)


def generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/KAI.pdf", couleur=True):
    """Génère nb_tickets tickets KAI uniques. couleur=False => Noir & Blanc."""
    nb_tickets = max(1, min(int(nb_tickets), 1000))
    serie_start = max(1, int(serie_start))
    rng = random.Random(754000 + serie_start)
    vus = set()
    cv = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))
    produits = 0
    while produits < nb_tickets:
        grille = _gen_nums(rng)
        sig = _signature(grille)
        if sig in vus:
            continue
        vus.add(sig)
        serial = serie_start + produits
        _draw_ticket(cv, serial, grille, RAINBOW[(serial - 1) % len(RAINBOW)], couleur)
        cv.showPage()
        produits += 1
    cv.save()
    return output_path


def generate_pdf_nb(nb_tickets=500, serie_start=1, output_path="/data/KAI_NB.pdf"):
    """Version Noir & Blanc (économe en encre)."""
    return generate_pdf(nb_tickets, serie_start, output_path, couleur=False)


if __name__ == "__main__":
    generate_pdf(nb_tickets=4, serie_start=1, output_path="kai_test.pdf")
    print("KAI généré")
