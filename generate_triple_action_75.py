"""
generate_triple_action_75.py
Module de génération de tickets TRIPLE ACTION 75
À intégrer dans l'application ticket-bingo (Flask)

Usage:
    from generate_triple_action_75 import generate_pdf
    path = generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/TA75_lot1.pdf")
"""

import random
import os
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm

# ── Police ──────────────────────────────────────────────────────────────────
FONT = 'Helvetica'
def _register_font():
    pass  # Police intégrée ReportLab

# ── Couleurs arc-en-ciel (12 couleurs) ──────────────────────────────────────
RAINBOW = [
    '#E53935',  # rouge
    '#FF7043',  # orange-rouge
    '#FB8C00',  # orange
    '#F9A825',  # jaune-or
    '#43A047',  # vert
    '#00ACC1',  # cyan
    '#1E88E5',  # bleu
    '#3949AB',  # indigo
    '#8E24AA',  # violet
    '#D81B60',  # rose foncé
    '#6D4C41',  # brun
    '#546E7A',  # gris-bleu
]

GREY = colors.Color(0.42, 0.42, 0.42)

# ── Dimensions ticket ────────────────────────────────────────────────────────
CARD_W  = 68 * mm
CARD_H  = 198 * mm
PAGE_W  = CARD_W + 8 * mm
PAGE_H  = CARD_H + 8 * mm
MARGIN  = 4 * mm
CARD_X  = MARGIN
CARD_Y  = MARGIN
HDR_H   = 13 * mm
BODY_H  = CARD_H - HDR_H
GROUP_H = BODY_H / 5
BIG_H   = GROUP_H * 0.38
SMALL_H = GROUP_H * 0.24

# ── Plages de numéros ────────────────────────────────────────────────────────
RANGES = [(1,15),(16,30),(31,45),(46,60),(61,75)]


def _gen_grille():
    """Génère une grille unique : 5 groupes × 3 numéros."""
    grille = []
    for (lo, hi) in RANGES:
        nums = sorted(random.sample(range(lo, hi + 1), 3))
        grille.append(nums)
    return grille


def _draw_ticket(c, serie: int, color_hex: str):
    """Dessine 1 ticket sur la page courante du canvas."""
    col = colors.HexColor(color_hex)

    # Fond blanc + bordure colorée
    c.setFillColor(colors.white)
    c.setStrokeColor(col)
    c.setLineWidth(1.5)
    c.roundRect(CARD_X, CARD_Y, CARD_W, CARD_H, 4*mm, stroke=1, fill=1)

    # ── HEADER ──────────────────────────────────────────────────────────────
    hdr_y = CARD_Y + CARD_H - HDR_H
    c.setFillColor(col)
    c.roundRect(CARD_X, hdr_y, CARD_W, HDR_H, 4*mm, stroke=0, fill=1)
    c.rect(CARD_X, hdr_y, CARD_W, HDR_H / 2, stroke=0, fill=1)

    c.setFillColor(colors.white)
    c.setFont('Helvetica', 10)
    c.drawCentredString(CARD_X + CARD_W / 2, hdr_y + HDR_H * 0.6, "T   R   I   P   L   75")
    c.setFont('Helvetica', 7)
    c.drawCentredString(CARD_X + CARD_W / 2, hdr_y + HDR_H * 0.18, f'N° {serie:05d}')

    # ── 5 GROUPES ───────────────────────────────────────────────────────────
    grille = _gen_grille()

    for g_idx, nums in enumerate(grille):
        group_bottom = CARD_Y + CARD_H - HDR_H - (g_idx + 1) * GROUP_H
        group_top    = group_bottom + GROUP_H

        # Séparateur horizontal
        if g_idx > 0:
            c.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
            c.setLineWidth(0.4)
            c.line(CARD_X + 2*mm, group_top, CARD_X + CARD_W - 2*mm, group_top)

        num_cercle, num_grand, num_petit = nums

        # Ligne 1 : cercle + grand numéro
        row1_cy   = group_top - BIG_H / 2
        r         = BIG_H * 0.42
        cx_circle = CARD_X + CARD_W * 0.30
        cx_right  = CARD_X + CARD_W * 0.70

        c.setStrokeColor(GREY)
        c.setLineWidth(0.7)
        c.setFillColor(colors.white)
        c.circle(cx_circle, row1_cy, r, stroke=1, fill=1)

        c.setFillColor(GREY)
        c.setFont('Helvetica', 28)
        c.drawCentredString(cx_circle, row1_cy - 10, str(num_cercle))
        c.drawCentredString(cx_right,  row1_cy - 10, str(num_grand))

        # Ligne 2 : petit numéro (agrandi)
        row2_cy = group_top - BIG_H - SMALL_H / 2
        c.setFillColor(GREY)
        c.setFont('Helvetica', 24)
        c.drawCentredString(CARD_X + CARD_W / 2, row2_cy - 8, str(num_petit))

    # Bordure corps
    c.setStrokeColor(col)
    c.setLineWidth(0.6)
    c.rect(CARD_X, CARD_Y, CARD_W, CARD_H - HDR_H, stroke=1, fill=0)


def generate_pdf(
    nb_tickets: int = 500,
    serie_start: int = 1,
    output_path: str = None,
    game_name: str = "TA75"
) -> str:
    """
    Génère un PDF de tickets TRIPLE ACTION 75.

    Paramètres :
        nb_tickets   : nombre de tickets à générer (ex: 100, 200, 500)
        serie_start  : numéro de série du premier ticket
        output_path  : chemin complet du PDF de sortie
                       (si None → /data/TA75_{serie_start}.pdf)
        game_name    : préfixe pour le nom de fichier auto

    Retourne :
        Le chemin absolu du PDF généré.
    """
    _register_font()

    if output_path is None:
        os.makedirs('/data', exist_ok=True)
        output_path = f'/data/{game_name}_{serie_start:05d}.pdf'

    c = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))

    for i in range(nb_tickets):
        serie      = serie_start + i
        color_hex  = RAINBOW[i % len(RAINBOW)]
        _draw_ticket(c, serie, color_hex)
        c.showPage()

    c.save()
    return output_path


# ── Utilisation standalone (test direct) ────────────────────────────────────
if __name__ == '__main__':
    path = generate_pdf(nb_tickets=12, serie_start=1, output_path='/mnt/user-data/outputs/TA75_MODULE_TEST.pdf')
    print(f"PDF généré : {path}")
