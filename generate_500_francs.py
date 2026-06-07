import random, os
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm

FONT = 'Helvetica'
def _register_font():
    pass  # Police intégrée ReportLab

GREY = colors.Color(0.42, 0.42, 0.42)
RAINBOW = ['#E53935','#FF7043','#FB8C00','#F9A825','#43A047','#00ACC1','#1E88E5','#3949AB','#8E24AA','#D81B60','#6D4C41','#546E7A']

PAGE_W = 160 * mm
PAGE_H = 80 * mm
MARGIN = 5 * mm
CARD_W = PAGE_W - 2*MARGIN
CARD_H = PAGE_H - 2*MARGIN
CARD_X = MARGIN
CARD_Y = MARGIN

def _gen_grille():
    return sorted(random.sample(range(1, 76), 10))

def _draw_ticket(c, serie, color_hex):
    col = colors.HexColor(color_hex)
    light = colors.Color(0.85, 0.85, 0.85)

    c.setFillColor(colors.white)
    c.setStrokeColor(col)
    c.setLineWidth(1.5)
    c.roundRect(CARD_X, CARD_Y, CARD_W, CARD_H, 2*mm, stroke=1, fill=1)

    cx = CARD_X + CARD_W/2
    HDR_H = 8*mm
    FTR_H = 7*mm
    hdr_y = CARD_Y + CARD_H - HDR_H
    ftr_top = CARD_Y + FTR_H

    # Header coloré
    c.setFillColor(col)
    c.roundRect(CARD_X, hdr_y, CARD_W, HDR_H, 2*mm, stroke=0, fill=1)
    c.rect(CARD_X, hdr_y, CARD_W, HDR_H/2, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont('Helvetica', 9)
    c.drawCentredString(cx, hdr_y + 2.5*mm, "500 FRANCS   BY 2KEA")

    # Footer
    c.setStrokeColor(light)
    c.setLineWidth(0.4)
    c.line(CARD_X, ftr_top, CARD_X + CARD_W, ftr_top)
    c.line(cx, CARD_Y, cx, ftr_top)
    c.setFillColor(GREY)
    c.setFont('Helvetica', 6)
    c.drawCentredString(CARD_X + CARD_W/4, CARD_Y + 2*mm, "N° SÉRIE")
    c.setFont('Helvetica', 8)
    c.drawCentredString(CARD_X + CARD_W*3/4, CARD_Y + 2*mm, f"{serie:06d}")

    # Grille 5×2
    nums = _gen_grille()
    body_y = ftr_top
    body_h = hdr_y - body_y
    row_h = body_h / 2
    col_w = CARD_W / 5

    for i, num in enumerate(nums):
        row = i // 5
        ci = i % 5
        px = CARD_X + ci * col_w + col_w/2
        py = hdr_y - (row + 0.5) * row_h

        c.setStrokeColor(light)
        c.setLineWidth(0.3)
        if ci > 0:
            c.line(CARD_X + ci*col_w, body_y, CARD_X + ci*col_w, hdr_y)
        if row == 1:
            c.line(CARD_X, hdr_y - row_h, CARD_X + CARD_W, hdr_y - row_h)

        fs = 36
        c.setFillColor(GREY)
        c.setFont('Helvetica', fs)
        c.drawCentredString(px, py - fs*0.37, str(num))

def generate_pdf(nb_tickets=500, serie_start=1, output_path=None, game_name="500FRANCS"):
    _register_font()
    if output_path is None:
        os.makedirs('/data', exist_ok=True)
        output_path = f'/data/{game_name}_{serie_start:05d}.pdf'
    c = canvas.Canvas(output_path, pagesize=(PAGE_W, PAGE_H))
    for i in range(nb_tickets):
        _draw_ticket(c, serie_start + i, RAINBOW[i % len(RAINBOW)])
        c.showPage()
    c.save()
    return output_path

if __name__ == '__main__':
    path = generate_pdf(nb_tickets=12, serie_start=1, output_path='/mnt/user-data/outputs/500_FRANCS_TEST.pdf')
    print(f"PDF : {path}")
