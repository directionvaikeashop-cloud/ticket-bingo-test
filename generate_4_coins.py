import random, os
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm

GREY = colors.Color(0.42, 0.42, 0.42)
LIGHT = colors.Color(0.80, 0.80, 0.80)
RAINBOW = ['#E53935','#FF7043','#FB8C00','#F9A825','#43A047','#00ACC1','#1E88E5','#3949AB','#8E24AA','#D81B60','#6D4C41','#546E7A']

PAGE_W = 110 * mm
PAGE_H = 110 * mm
MARGIN = 5 * mm
CARD_W = PAGE_W - 2*MARGIN
CARD_H = PAGE_H - 2*MARGIN
CARD_X = MARGIN
CARD_Y = MARGIN

# 5 colonnes "4 C O I N" : la colonne du milieu (O) est VIDE.
# Chaque colonne remplie tire 4 numeros dans sa plage BINGO (le milieu 31-45 est saute).
ENTETES = ["4", "C", "O", "I", "N"]
PLAGES = [(1, 15), (16, 30), None, (46, 60), (61, 75)]


def _gen_grille(rng):
    cols = []
    for p in PLAGES:
        if p is None:
            cols.append(None)
        else:
            cols.append(sorted(rng.sample(range(p[0], p[1] + 1), 4)))
    return cols


def _draw_ticket(c, serie, color_hex, rng):
    col = colors.HexColor(color_hex)
    c.setFillColor(colors.white)
    c.setStrokeColor(col)
    c.setLineWidth(1.6)
    c.roundRect(CARD_X, CARD_Y, CARD_W, CARD_H, 2.5*mm, stroke=1, fill=1)

    cols = _gen_grille(rng)
    head_h = 9 * mm
    grid_top = CARD_Y + CARD_H - head_h
    grid_bot = CARD_Y + 2 * mm
    gw = CARD_W / 5.0
    gh = (grid_top - grid_bot) / 5.0

    c.setFillColor(col)
    c.setFont('Helvetica-Bold', 15)
    for ci, lettre in enumerate(ENTETES):
        cx = CARD_X + ci * gw + gw / 2
        c.drawCentredString(cx, grid_top + 2.5*mm, lettre)

    c.setStrokeColor(LIGHT)
    c.setLineWidth(0.6)
    for k in range(6):
        x = CARD_X + k * gw
        c.line(x, grid_bot, x, grid_top)
        y = grid_bot + k * gh
        c.line(CARD_X, y, CARD_X + CARD_W, y)

    rangees = [0, 1, 3, 4]
    for ci in range(5):
        if cols[ci] is None:
            continue
        for k, ri in enumerate(rangees):
            n = cols[ci][k]
            cx = CARD_X + ci * gw + gw / 2
            cy = grid_top - (ri + 0.5) * gh
            c.setFillColor(GREY)
            c.setFont('Helvetica', 26)
            c.drawCentredString(cx, cy - 9, str(n))

    cx = CARD_X + 2 * gw + gw / 2
    cy = grid_top - 2.5 * gh
    c.setFillColor(col)
    c.circle(cx, cy, gh * 0.42, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont('Helvetica', 6)
    c.drawCentredString(cx, cy + 2.6*mm, "TK")
    c.drawCentredString(cx, cy + 0.6*mm, "creation")
    c.setFont('Helvetica-Bold', 9)
    c.drawCentredString(cx, cy - 2.2*mm, f"{serie:05d}")


def generate_pdf(nb_tickets=500, serie_start=1, output_path=None, game_name="4COINS"):
    if output_path is None:
        os.makedirs('/data', exist_ok=True)
        output_path = f'/data/{game_name}_{serie_start:05d}.pdf'
    c = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))
    rng = random.Random(820000 + int(serie_start))
    for i in range(nb_tickets):
        _draw_ticket(c, serie_start + i, RAINBOW[i % len(RAINBOW)], rng)
        c.showPage()
    c.save()
    return output_path


if __name__ == '__main__':
    print(generate_pdf(nb_tickets=4, serie_start=1, output_path='/tmp/4coin_test.pdf'))
