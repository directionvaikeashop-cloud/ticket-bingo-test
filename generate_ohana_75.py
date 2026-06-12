# -*- coding: utf-8 -*-
"""
GENERATEUR OHANA 75 — 10 BOULES (format ticket application)
TUKEA — Ticket Bingo
1 page = 1 ticket vertical (68 x 198 mm), couleurs arc-en-ciel par ticket.
Regle BINGO 75 : exactement 2 numeros par plage (B 1-15, I 16-30, N 31-45, G 46-60, O 61-75).
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


def _gen_nums(rng):
    """2 numeros par plage BINGO, tries dans chaque plage."""
    return {lettre: sorted(rng.sample(range(a, b + 1), 2)) for lettre, a, b in PLAGES}


def _signature(nums):
    return tuple(tuple(nums[l]) for l, _, _ in PLAGES)


def _draw_ticket(cv, serial, nums, coul):
    M = 5 * mm
    cv.setStrokeColor(coul)
    cv.setLineWidth(1.6)
    cv.roundRect(M, M, TW - 2 * M, TH - 2 * M, 4 * mm, fill=0, stroke=1)
    cv.setFont(POLICE, 17)
    cv.setFillColor(coul)
    cv.drawCentredString(TW / 2, TH - M - 9 * mm, "OHANA 75")
    cv.setFont(POLICE, 8.5)
    cv.setFillColor(GRIS)
    cv.drawCentredString(TW / 2, TH - M - 13.5 * mm, "10 BOULES")
    cv.drawCentredString(TW / 2, TH - M - 17.5 * mm, "N° SÉRIE %05d" % serial)
    zone_top = TH - M - 21 * mm
    zone_bot = M + 9 * mm
    gh = (zone_top - zone_bot) / 5
    for idx, (lettre, a, b) in enumerate(PLAGES):
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
        n1, n2 = nums[lettre]
        cx1, cx2 = M + 26 * mm, M + 46 * mm
        cv.setFillColor(NOIR)
        cv.setFont(POLICE, 26)
        t1 = str(n1)
        w1 = cv.stringWidth(t1, POLICE, 26)
        cv.drawString(cx1 - w1 / 2, py - 9, t1)
        cv.setStrokeColor(coul)
        cv.setLineWidth(1.1)
        cv.setDash(2.5, 2.5)
        cv.circle(cx2, py, 8.2 * mm, fill=0, stroke=1)
        cv.setDash()
        cv.setFillColor(NOIR)
        cv.setFont(POLICE, 21)
        t2 = str(n2)
        w2 = cv.stringWidth(t2, POLICE, 21)
        cv.drawString(cx2 - w2 / 2, py - 7.5, t2)
    cv.setFont(POLICE, 7.5)
    cv.setFillColor(GRIS)
    cv.drawCentredString(TW / 2, M + 4 * mm, "TUKEA  89 22 23 05")


def generate_pdf(nb_tickets=500, serie_start=1, output_path="/data/OHANA_75.pdf"):
    """Genere nb_tickets tickets uniques (1 par page), serials a partir de serie_start."""
    nb_tickets = max(1, min(int(nb_tickets), 1000))
    serie_start = max(1, int(serie_start))
    # Graine deterministe par serie de depart : memes series = memes tickets (reimpression possible)
    rng = random.Random(750000 + serie_start)
    vus = set()
    cv = canvas.Canvas(output_path, pagesize=(TW, TH))
    produits = 0
    while produits < nb_tickets:
        nums = _gen_nums(rng)
        sig = _signature(nums)
        if sig in vus:
            continue
        vus.add(sig)
        serial = serie_start + produits
        _draw_ticket(cv, serial, nums, ARCENCIEL[(serial - 1) % len(ARCENCIEL)])
        cv.showPage()
        produits += 1
    cv.save()
    return output_path
