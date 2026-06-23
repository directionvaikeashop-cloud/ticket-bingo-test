# -*- coding: utf-8 -*-
"""
generate_bingo_ball.py
Module de génération de tickets BINGO BALL — Ticket Bingo (TUKEA)

Carte en CROIX (+) :
  - rangée horizontale = 1 numéro par colonne BINGO 75
      B 1-15, I 16-30, N 31-45 (centre), G 46-60, O 61-75
  - colonne centrale (verticale) = 3 numéros de la plage du milieu 31-45
      (haut, centre, bas) — le centre est partagé avec la rangée.
  - case du haut : titre "BINGO BALL" + numéro + N° de série.
7 numéros au total. 1 page = 1 ticket. Tickets uniques.

Usage:
    from generate_bingo_ball import generate_pdf
    path = generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/BINGO_BALL.pdf")
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
GRIS_CLAIR = colors.Color(0.78, 0.78, 0.78)

# couleur arc-en-ciel par ticket
RAINBOW = [
    colors.HexColor('#E53935'), colors.HexColor('#FB8C00'), colors.HexColor('#F9A825'),
    colors.HexColor('#43A047'), colors.HexColor('#00ACC1'), colors.HexColor('#1E88E5'),
    colors.HexColor('#3949AB'), colors.HexColor('#8E24AA'), colors.HexColor('#D81B60'),
    colors.HexColor('#6D4C41'),
]

PLAGES = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75)]  # B I N G O

CELL = 34 * mm
MARGIN = 6 * mm
PAGE_W = 5 * CELL + 2 * MARGIN
PAGE_H = 3 * CELL + 2 * MARGIN


def _gen_nums(rng):
    """Retourne (ligne[5], centre_vertical[3]).
    centre_vertical = 3 numéros 31-45 triés ; son milieu = case centrale de la ligne."""
    centre = sorted(rng.sample(range(31, 46), 3))   # haut, centre, bas
    ligne = [
        rng.randint(1, 15),
        rng.randint(16, 30),
        centre[1],          # case centrale partagée
        rng.randint(46, 60),
        rng.randint(61, 75),
    ]
    return ligne, centre


def _signature(ligne, centre):
    return (tuple(ligne), tuple(centre))


def _cell_xy(col, row):
    """col 0..4 (gauche→droite), row 0=haut,1=milieu,2=bas. Renvoie (x,y) coin bas-gauche."""
    x = MARGIN + col * CELL
    y = MARGIN + (2 - row) * CELL
    return x, y


def _draw_cell(cv, col, row, coul):
    x, y = _cell_xy(col, row)
    cv.setStrokeColor(coul)
    cv.setLineWidth(1.6)
    cv.roundRect(x, y, CELL, CELL, 4 * mm, stroke=1, fill=0)
    return x, y


def _draw_num(cv, col, row, valeur, coul):
    x, y = _draw_cell(cv, col, row, coul)
    cv.setFillColor(colors.black)
    cv.setFont(POLICE, 52)
    cv.drawCentredString(x + CELL / 2, y + CELL / 2 - 18, str(valeur))


def _draw_ticket(cv, serial, ligne, centre, accent, couleur=True):
    bord = accent if couleur else GRIS_CLAIR
    # rangée horizontale (5 colonnes, row=1)
    for col in range(5):
        if col == 2:
            continue  # la case centrale est dessinée avec la colonne verticale
        _draw_num(cv, col, 1, ligne[col], bord)

    # case centrale (croisement) : numéro du milieu
    _draw_num(cv, 2, 1, centre[1], bord)

    # case du BAS (colonne centrale)
    _draw_num(cv, 2, 2, centre[2], bord)

    # case du HAUT (colonne centrale) : titre + numéro + n° de série
    x, y = _draw_cell(cv, 2, 0, bord)
    cx = x + CELL / 2
    cv.setFillColor(bord)
    cv.setFont(POLICE, 9)
    cv.drawCentredString(cx, y + CELL - 9, "BINGO BALL")
    cv.setFillColor(colors.black)
    cv.setFont(POLICE, 46)
    cv.drawCentredString(cx, y + CELL / 2 - 12, str(centre[0]))
    cv.setFillColor(bord)
    cv.setFont(POLICE, 9)
    cv.drawCentredString(cx, y + 5 * mm, "N° %05d" % serial)


def generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/BINGO_BALL.pdf", couleur=True):
    """Génère nb_tickets tickets BINGO BALL uniques (1 par page). couleur=False => Noir & Blanc."""
    nb_tickets = max(1, min(int(nb_tickets), 1000))
    serie_start = max(1, int(serie_start))
    rng = random.Random(752000 + serie_start)   # déterministe par série de départ
    vus = set()
    cv = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))
    produits = 0
    while produits < nb_tickets:
        ligne, centre = _gen_nums(rng)
        sig = _signature(ligne, centre)
        if sig in vus:
            continue
        vus.add(sig)
        serial = serie_start + produits
        _draw_ticket(cv, serial, ligne, centre, RAINBOW[(serial - 1) % len(RAINBOW)], couleur)
        cv.showPage()
        produits += 1
    cv.save()
    return output_path


def generate_pdf_nb(nb_tickets=500, serie_start=1, output_path="/data/BINGO_BALL_NB.pdf"):
    """Version Noir & Blanc (économe en encre)."""
    return generate_pdf(nb_tickets, serie_start, output_path, couleur=False)


if __name__ == "__main__":
    generate_pdf(nb_tickets=4, serie_start=1, output_path="bingo_ball_test.pdf")
    print("BINGO BALL généré")
