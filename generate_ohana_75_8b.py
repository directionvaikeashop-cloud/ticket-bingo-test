# -*- coding: utf-8 -*-
"""
GENERATEUR OHANA 75 — 8 BOULES (format ticket application)
TUKEA — Ticket Bingo
1 page = 1 ticket vertical (68 x 198 mm), couleurs arc-en-ciel par ticket.
Regle : 2 numeros par plage BINGO dans 4 plages sur 5 — la plage absente
change a chaque ticket (deduit de la grille d'origine 90001 : B/I/G/O sans N).
Valide par Maeva le 12/06/2026.
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

TW, TH = 68 * mm, 198 * mm
NOIR = colors.black
GRIS = colors.Color(0.42, 0.42, 0.42)
ARCENCIEL = [
    colors.Color(0.85, 0.20, 0.25), colors.Color(0.90, 0.55, 0.10), colors.Color(0.72, 0.60, 0.05),
    colors.Color(0.15, 0.60, 0.35), colors.Color(0.20, 0.45, 0.85), colors.Color(0.45, 0.30, 0.75),
    colors.Color(0.80, 0.25, 0.65),
]
PLAGES = [("B", 1, 15), ("I", 16, 30), ("N", 31, 45), ("G", 46, 60), ("O", 61, 75)]


def _gen_grille(rng):
    """2 numeros par plage dans 4 plages sur 5 — plage absente aleatoire."""
    sautee = rng.randrange(5)
    grille = []
    for idx, (lettre, a, b) in enumerate(PLAGES):
        if idx == sautee:
            continue
        grille.append((lettre, tuple(sorted(rng.sample(range(a, b + 1), 2)))))
    return grille


def _signature(grille):
    return tuple(grille)


def _draw_ticket(cv, serial, grille, coul):
    M = 5 * mm
    cv.setStrokeColor(coul)
    cv.setLineWidth(1.6)
    cv.roundRect(M, M, TW - 2 * M, TH - 2 * M, 4 * mm, fill=0, stroke=1)
    cv.setFont(POLICE, 17)
    cv.setFillColor(coul)
    cv.drawCentredString(TW / 2, TH - M - 9 * mm, "OHANA 75")
    cv.setFont(POLICE, 8.5)
    cv.setFillColor(GRIS)
    cv.drawCentredString(TW / 2, TH - M - 13.5 * mm, "8 BOULES")
    cv.drawCentredString(TW / 2, TH - M - 17.5 * mm, "N° SÉRIE %05d" % serial)
    zone_top = TH - M - 21 * mm
    zone_bot = M + 9 * mm
    gh = (zone_top - zone_bot) / 4
    for idx, (lettre, paire) in enumerate(grille):
        gy = zone_top - (idx + 1) * gh
        if idx > 0:
            cv.setStrokeColor(colors.Color(0.85, 0.85, 0.85))
            cv.setLineWidth(0.5)
            cv.line(M + 5 * mm, gy + gh, TW - M - 5 * mm, gy + gh)
        px, py = M + 9 * mm, gy + gh / 2
        cv.setFillColor(coul)
        cv.circle(px, py, 5.4 * mm, fill=1, stroke=0)
        cv.setFillColor(colors.white)
        cv.setFont(POLICE, 15)
        tw = cv.stringWidth(lettre, POLICE, 15)
        cv.drawString(px - tw / 2, py - 5.2, lettre)
        n1, n2 = paire
        cx1, cx2 = M + 26 * mm, M + 46 * mm
        cv.setFillColor(NOIR)
        cv.setFont(POLICE, 28)
        t1 = str(n1)
        w1 = cv.stringWidth(t1, POLICE, 28)
        cv.drawString(cx1 - w1 / 2, py - 10, t1)
        cv.setStrokeColor(coul)
        cv.setLineWidth(1.1)
        cv.setDash(2.5, 2.5)
        cv.circle(cx2, py, 9 * mm, fill=0, stroke=1)
        cv.setDash()
        cv.setFillColor(NOIR)
        cv.setFont(POLICE, 23)
        t2 = str(n2)
        w2 = cv.stringWidth(t2, POLICE, 23)
        cv.drawString(cx2 - w2 / 2, py - 8, t2)
    cv.setFont(POLICE, 7.5)
    cv.setFillColor(GRIS)
    cv.drawCentredString(TW / 2, M + 4 * mm, "TUKEA  89 22 23 05")


def generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/OHANA_75_8B.pdf"):
    """Genere nb_tickets tickets uniques (1 par page), serials a partir de serie_start."""
    nb_tickets = max(1, min(int(nb_tickets), 1000))
    serie_start = max(1, int(serie_start))
    rng = random.Random(758000 + serie_start)
    vus = set()
    cv = canvas.Canvas(output_path, pagesize=(TW, TH))
    produits = 0
    while produits < nb_tickets:
        grille = _gen_grille(rng)
        sig = _signature(grille)
        if sig in vus:
            continue
        vus.add(sig)
        serial = serie_start + produits
        _draw_ticket(cv, serial, grille, ARCENCIEL[(serial - 1) % len(ARCENCIEL)])
        cv.showPage()
        produits += 1
    cv.save()
    return output_path
