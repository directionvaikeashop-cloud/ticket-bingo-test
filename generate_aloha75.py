# -*- coding: utf-8 -*-
"""
generate_aloha75.py
Module de génération de tickets ALOHA 75 — Ticket Bingo (TUKEA)

Carte horizontale : en-tête A-L-O-H-A, grille 5 colonnes × 2 rangées.
Règle BINGO 75 : exactement 2 numéros par colonne
  A=1-15, L=16-30, O=31-45, H=46-60, A=61-75.
1 page = 1 ticket. Tickets uniques. N° de série.

Usage:
    from generate_aloha75 import generate_pdf
    path = generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/ALOHA_75.pdf")
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
ACCENT = colors.Color(0.30, 0.55, 0.70)   # bleu-gris pour le n° de série

# couleur arc-en-ciel par ticket
RAINBOW = [
    colors.HexColor('#E53935'), colors.HexColor('#FB8C00'), colors.HexColor('#F9A825'),
    colors.HexColor('#43A047'), colors.HexColor('#00ACC1'), colors.HexColor('#1E88E5'),
    colors.HexColor('#3949AB'), colors.HexColor('#8E24AA'), colors.HexColor('#D81B60'),
    colors.HexColor('#6D4C41'),
]

LETTRES = ["A", "L", "O", "H", "A"]
# couleurs douces des lettres d'en-tête (ton "ALOHA")
COUL_LETTRES = ["#5E8B7E", "#D98A3D", "#8A8A8A", "#A0673D", "#7C9A8E"]
PLAGES = [(1, 15), (16, 30), (31, 45), (46, 60), (61, 75)]

# Dimensions ticket horizontal
CARD_W = 178 * mm
CARD_H = 86 * mm
MARGIN = 5 * mm
PAGE_W = CARD_W + 2 * MARGIN
PAGE_H = CARD_H + 2 * MARGIN


def _gen_nums(rng):
    """2 numéros triés par colonne (plage BINGO 75)."""
    return [sorted(rng.sample(range(a, b + 1), 2)) for a, b in PLAGES]


def _signature(cols):
    return tuple(tuple(c) for c in cols)


def _draw_ticket(cv, serial, cols, coul):
    x0, y0 = MARGIN, MARGIN
    cell_w = CARD_W / 5

    # zones verticales : en-tête / 2 rangées / pied
    head_h = 14 * mm
    foot_h = 8 * mm
    body_h = CARD_H - head_h - foot_h
    row_h = body_h / 2
    top = y0 + CARD_H

    # cadre extérieur ARRONDI, en COULEUR (arc-en-ciel par ticket)
    cv.setStrokeColor(coul)
    cv.setLineWidth(2.2)
    cv.roundRect(x0, y0, CARD_W, CARD_H, 6 * mm, stroke=1, fill=0)

    # lignes horizontales : sous l'en-tête, entre les 2 rangées, au-dessus du pied
    y_head = top - head_h
    y_mid = y_head - row_h
    y_foot = y0 + foot_h
    cv.setStrokeColor(GRIS_CLAIR)
    cv.setLineWidth(0.5)
    for yy in (y_head, y_mid, y_foot):
        cv.line(x0 + 5 * mm, yy, x0 + CARD_W - 5 * mm, yy)
    # lignes verticales (5 colonnes)
    for i in range(1, 5):
        cv.line(x0 + i * cell_w, y0 + 5 * mm, x0 + i * cell_w, top - 5 * mm)

    # en-tête A L O H A
    for i, lettre in enumerate(LETTRES):
        cx = x0 + (i + 0.5) * cell_w
        cv.setFillColor(colors.HexColor(COUL_LETTRES[i]))
        cv.setFont(POLICE, 18)
        cv.drawCentredString(cx, y_head + (head_h - 18) / 2 + 1, lettre)

    # numéros (2 rangées × 5 colonnes, GROS, gris)
    cv.setFillColor(GRIS)
    cv.setFont(POLICE, 56)
    for i in range(5):
        cx = x0 + (i + 0.5) * cell_w
        n1, n2 = cols[i]
        # rangée du haut
        cv.drawCentredString(cx, y_head - row_h / 2 - 19, str(n1))
        # rangée du bas
        cv.drawCentredString(cx, y_mid - row_h / 2 - 19, str(n2))

    # pied : N° SÉRIE (gauche) + numéro (droite, en couleur du ticket)
    cv.setFont(POLICE, 8)
    cv.setFillColor(GRIS_CLAIR)
    cv.drawString(x0 + 6 * mm, y0 + foot_h / 2 - 3, "N° SÉRIE")
    cv.setFillColor(coul)
    cv.drawRightString(x0 + CARD_W - 6 * mm, y0 + foot_h / 2 - 3, "%06d" % serial)


def generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/ALOHA_75.pdf"):
    """Génère nb_tickets tickets ALOHA 75 uniques (1 par page)."""
    nb_tickets = max(1, min(int(nb_tickets), 1000))
    serie_start = max(1, int(serie_start))
    rng = random.Random(751000 + serie_start)   # déterministe par série de départ
    vus = set()
    cv = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))
    produits = 0
    while produits < nb_tickets:
        cols = _gen_nums(rng)
        sig = _signature(cols)
        if sig in vus:
            continue
        vus.add(sig)
        serial = serie_start + produits
        _draw_ticket(cv, serial, cols, RAINBOW[(serial - 1) % len(RAINBOW)])
        cv.showPage()
        produits += 1
    cv.save()
    return output_path


if __name__ == "__main__":
    generate_pdf(nb_tickets=6, serie_start=1, output_path="aloha75_test.pdf")
    print("ALOHA 75 généré")
