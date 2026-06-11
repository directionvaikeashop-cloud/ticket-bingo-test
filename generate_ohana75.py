import random, os
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4

FONT_BOLD = 'Helvetica-Bold'
FONT = 'Helvetica'
GREY = colors.Color(0.58, 0.58, 0.58)
BLACK = colors.black

RAINBOW = ['#E53935','#FF7043','#FB8C00','#F9A825','#43A047',
           '#00ACC1','#1E88E5','#3949AB','#8E24AA','#D81B60',
           '#6D4C41','#546E7A']

PAGE_W, PAGE_H = A4
MARGIN = 15 * mm
CARD_W = PAGE_W - 2 * MARGIN
CARD_H = PAGE_H - 2 * MARGIN - 10
CARD_X = MARGIN
CARD_Y = MARGIN

COLS = ["B", "I", "N", "G", "O"]
RANGES = {"B":(1,15), "I":(16,30), "N":(31,45), "G":(46,60), "O":(61,75)}

def gen_card():
    card = []
    for col in COLS:
        lo, hi = RANGES[col]
        nums = random.sample(range(lo, hi+1), 5)
        card.append(nums)
    card[2][2] = None
    return card

def draw_ticket(c, card, serie, page_num, nb_tickets, color_hex):
    light = colors.Color(0.80, 0.80, 0.80)
    col_color = colors.HexColor(color_hex)

    # Titre
    c.setFillColor(GREY)
    c.setFont(FONT, 8)
    c.drawCentredString(PAGE_W/2, CARD_Y + CARD_H + 5,
        f"OHANA 75  —  Page {page_num}/{nb_tickets}  —  Carte {serie:05d}")

    # Bordure colorée
    c.setStrokeColor(col_color)
    c.setFillColor(colors.white)
    c.setLineWidth(2.0)
    c.roundRect(CARD_X, CARD_Y, CARD_W, CARD_H, 5*mm, stroke=1, fill=1)

    col_w = CARD_W / 5
    NROWS = 6
    row_h = CARD_H / NROWS

    # Lignes verticales
    c.setStrokeColor(light)
    c.setLineWidth(0.4)
    for i in range(1, 5):
        c.line(CARD_X + i*col_w, CARD_Y, CARD_X + i*col_w, CARD_Y + CARD_H)

    # Lignes horizontales pointillées
    c.setDash(3, 3)
    for j in range(1, NROWS):
        c.line(CARD_X, CARD_Y + j*row_h, CARD_X + CARD_W, CARD_Y + j*row_h)
    c.setDash()

    # HEADER B I N G O
    col_hdr_bottom = CARD_Y + 5 * row_h
    for ci, col_name in enumerate(COLS):
        cx = CARD_X + ci*col_w + col_w/2
        cy = col_hdr_bottom + row_h/2
        if col_name == "G":
            c.setFillColor(col_color)
            c.setFont(FONT_BOLD, 8)
            c.drawCentredString(cx, cy + 12, "MARATHON")
        c.setFillColor(col_color)
        c.setFont(FONT_BOLD, 36)
        c.drawCentredString(cx, cy - 15, col_name)

    # DONNÉES
    for row in range(5):
        row_bottom = CARD_Y + row * row_h
        row_top = row_bottom + row_h
        cy = row_bottom + row_h / 2

        for ci in range(5):
            num = card[ci][row]
            cell_left = CARD_X + ci * col_w
            cell_right = CARD_X + (ci + 1) * col_w
            cx = cell_left + col_w / 2

            if num is None:
                c.setFillColor(col_color)
                c.setFont(FONT_BOLD, 12)
                c.drawCentredString(cx, cy + 8, "FREE")
                c.setFont(FONT, 8)
                c.setFillColor(GREY)
                c.drawCentredString(cx, cy - 1, f"{serie:05d}")
                c.drawCentredString(cx, cy - 11, "SPACE")
            else:
                # Cercle 55% cellule — bien dans la cellule
                r = min(col_w, row_h) * 0.28
                circ_cx = cx - col_w * 0.08
                circ_cy = cy + row_h * 0.06

                c.setStrokeColor(col_color)
                c.setFillColor(colors.white)
                c.setLineWidth(1.2)
                c.circle(circ_cx, circ_cy, r, stroke=1, fill=1)

                # Grand chiffre dans cercle
                fs = int(r * 1.28) if num < 10 else int(r * 1.08)
                c.setFillColor(BLACK)
                c.setFont(FONT_BOLD, fs)
                c.drawCentredString(circ_cx, circ_cy - fs*0.35, str(num))

                # Petit chiffre — aligné dans coin bas-droite de la cellule
                col_nums = [n for n in card[ci] if n is not None]
                idx = col_nums.index(num) if num in col_nums else 0
                small = col_nums[(idx + 1) % len(col_nums)]
                small_fs = int(r * 1.10)
                
                # Calculer largeur du texte pour l'aligner à droite de la cellule
                small_str = str(small)
                # Positionner en bas à droite, avec marge de 4pts depuis bord droit
                small_x = cell_right - 4 - (len(small_str) * small_fs * 0.58)
                small_y = row_bottom + row_h * 0.06

                c.setFont(FONT_BOLD, small_fs)
                c.setFillColor(BLACK)
                c.drawString(small_x, small_y, small_str)

def generate_pdf(nb_tickets=100, serie_start=1, output_path=None):
    if output_path is None:
        os.makedirs('/data', exist_ok=True)
        output_path = f'/data/OHANA75_{serie_start:05d}.pdf'
    c = canvas.Canvas(output_path, pagesize=A4)
    used = set()
    for i in range(nb_tickets):
        while True:
            card = gen_card()
            key = tuple(tuple(col) for col in card)
            if key not in used:
                used.add(key)
                break
        draw_ticket(c, card, serie_start + i, i + 1, nb_tickets,
                    RAINBOW[i % len(RAINBOW)])
        c.showPage()
    c.save()
    print(f"[OK] {nb_tickets} tickets OHANA 75 -> {output_path}")
    return output_path

if __name__ == '__main__':
    generate_pdf(nb_tickets=12, serie_start=1,
                 output_path='/mnt/user-data/outputs/OHANA75_TEST.pdf')

