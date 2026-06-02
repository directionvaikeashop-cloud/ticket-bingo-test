import hashlib, datetime, os, secrets, string, json, base64
import urllib.request, urllib.parse
from flask import Flask, request, jsonify, send_from_directory, Response
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__, static_folder=".")

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "directionvaikeashop@gmail.com")
FROM_NAME = "Ticket Bingo"

CLOUDINARY_CLOUD = os.environ.get("CLOUDINARY_CLOUD", "dz556b0ee")
CLOUDINARY_PRESET = "alerte_upload"
CLOUDINARY_PRESET_PDF = "bingo_pdf"

# Essayer /data (volume persistant) sinon /tmp
import tempfile
_data_paths = ["/data/ticketbingo_data.json", "/tmp/ticketbingo_data.json"]

def get_data_file():
    for path in _data_paths:
        try:
            dir_path = os.path.dirname(path)
            if os.path.exists(dir_path):
                # Tester ecriture
                test = path + ".test"
                with open(test, "w") as f: f.write("ok")
                os.remove(test)
                print(f"[STORAGE] Utilisation de {path}")
                return path
        except: pass
    return "/tmp/ticketbingo_data.json"

DATA_FILE = get_data_file()

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            for k in ["tickets_acheteurs", "acces_docs", "pdfs", "alertes_bingo", "tirage"]:
                if k not in data: data[k] = [] if k in ["alertes_bingo", "tirage"] else {}
            return data
    except: pass
    return {
        "ventes": [], "tickets": [],
        "jeux": ["P6", "OHANA 75", "QUINES 90", "OHANA 75 4 SERIE"],
        "tournois": [],
        "codes": {"ADMIN2024": {"duree": 36500, "nom": "Administrateur", "actif": True, "admin": True}},
        "sessions": {}, "acces_docs": {}, "tickets_acheteurs": {},
        "pdfs": {}, "alertes_bingo": [], "tirage": []
    }

def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(DB, f, ensure_ascii=False, default=str)
        print(f"[SAVE OK] {DATA_FILE}")
    except Exception as e:
        print(f"[SAVE ERR] {e}")

DB = load_data()

@app.before_request
def reload_db():
    global DB
    DB = load_data()

def gen_code(n=8):
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))

def verif_session(token):
    s = DB["sessions"].get(token)
    if not s: return None
    if datetime.datetime.now() > datetime.datetime.fromisoformat(s["expire"]):
        del DB["sessions"][token]
        return None
    return s

def upload_cloudinary_image(image_b64):
    try:
        data = urllib.parse.urlencode({
            "file": f"data:image/jpeg;base64,{image_b64}",
            "upload_preset": CLOUDINARY_PRESET
        }).encode('utf-8')
        url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD}/image/upload"
        req = urllib.request.Request(url, data=data, method='POST')
        req.add_header('Content-Type', 'application/x-www-form-urlencoded')
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode())
        return result.get("secure_url")
    except Exception as e:
        print(f"[CLOUDINARY ERR] {e}")
        return None

@app.route("/")
def index():
    response = send_from_directory(".", "index.html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route("/api/login", methods=["POST"])
def login():
    code = request.json.get("code", "").strip().upper()
    info = DB["codes"].get(code)
    if not info or not info["actif"]:
        return jsonify({"ok": False, "msg": "Code invalide ou expiré"}), 401
    expire = datetime.datetime.now() + datetime.timedelta(days=30)
    token = secrets.token_hex(16)
    DB["sessions"][token] = {"code": code, "nom": info["nom"], "expire": expire.isoformat(), "admin": info.get("admin", False)}
    save_data()
    return jsonify({"ok": True, "token": token, "nom": info["nom"], "admin": info.get("admin", False), "code_org": code})

@app.route("/api/jeux")
def get_jeux():
    return jsonify(DB["jeux"])

@app.route("/api/jeux", methods=["POST"])
def add_jeu():
    nom = request.json.get("nom", "").strip()
    if nom and nom not in DB["jeux"]:
        DB["jeux"].append(nom)
        save_data()
    return jsonify(DB["jeux"])

@app.route("/api/jeux/<nom>", methods=["DELETE"])
def del_jeu(nom):
    if nom in DB["jeux"]:
        DB["jeux"].remove(nom)
        save_data()
    return jsonify(DB["jeux"])

@app.route("/api/tournoi", methods=["POST"])
def creer_tournoi():
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    tournoi = {"id": gen_code(6), "nom": d.get("nom", ""), "jeu": d.get("jeu", ""),
               "date_tournoi": d.get("date_tournoi", ""), "created": datetime.datetime.now().isoformat()}
    DB["tournois"].insert(0, tournoi)
    save_data()
    return jsonify({"ok": True, "tournoi": tournoi})

@app.route("/api/tournois")
def get_tournois():
    return jsonify(DB["tournois"])

@app.route("/api/upload-pdf", methods=["POST"])
def upload_pdf():
    """Stocke le PDF en base64 dans la DB et retourne un ID d'acces"""
    try:
        d = request.json
        pdf_b64 = d.get("pdf_b64", "")
        if not pdf_b64:
            return jsonify({"ok": False, "msg": "PDF manquant"}), 400

        pdf_id = secrets.token_hex(16)
        if "pdfs" not in DB:
            DB["pdfs"] = {}
        DB["pdfs"][pdf_id] = pdf_b64
        save_data()

        return jsonify({"ok": True, "pdf_url": f"/api/pdf/{pdf_id}"})

    except Exception as e:
        print(f"[PDF UPLOAD ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/pdf/<pdf_id>")
def serve_pdf(pdf_id):
    """Sert un PDF stocke en base64 dans la DB"""
    if not all(c in '0123456789abcdef' for c in pdf_id):
        return jsonify({"ok": False}), 400
    pdf_b64 = DB.get("pdfs", {}).get(pdf_id)
    if not pdf_b64:
        return jsonify({"ok": False, "msg": "PDF introuvable"}), 404
    data = base64.b64decode(pdf_b64)
    return Response(data, content_type="application/pdf", headers={
        "Access-Control-Allow-Origin": "*",
        "Content-Disposition": "inline",
        "Cache-Control": "no-store"
    })

@app.route("/api/vente", methods=["POST"])
def nouvelle_vente():
    d = request.json
    if not d.get("client") or not d.get("jeu") or not d.get("serie"):
        return jsonify({"ok": False, "msg": "Champs manquants"}), 400
    total = int(d.get("qty", 1)) * int(d.get("prix", 0))
    token_doc = secrets.token_hex(16)
    tournoi_id = d.get("tournoi_id", "")
    date_expiration = None
    tournoi = next((t for t in DB["tournois"] if t["id"] == tournoi_id), None)
    if tournoi and tournoi.get("date_tournoi"):
        date_expiration = tournoi["date_tournoi"]
    vente = {
        "id": hashlib.md5(f"{d['client']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "client": d["client"], "email": d.get("email", ""), "jeu": d["jeu"],
        "pack": int(d.get("pack", 25)), "qty": int(d.get("qty", 1)),
        "total_feuilles": int(d.get("qty", 1)) * int(d.get("pack", 25)),
        "serie": d["serie"], "prix": int(d.get("prix", 0)), "total": total,
        "photo_url": d.get("photo_url", None),
        "pdf_url": d.get("pdf_url", None),
        "token_doc": token_doc, "tournoi_id": tournoi_id,
        "date_expiration": date_expiration,
        "date": datetime.datetime.now().isoformat()
    }
    DB["ventes"].insert(0, vente)
    DB["acces_docs"][token_doc] = {"vente_id": vente["id"], "client": vente["client"],
                                    "jeu": vente["jeu"], "date_expiration": date_expiration, "acces_count": 0}
    save_data()

    # Envoyer email au client si email fourni
    if vente["email"] and SENDGRID_API_KEY:
        try:
            expire_str = date_expiration if date_expiration else "illimitée"
            html = f"""
            <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
              <div style='text-align:center;margin-bottom:24px'>
                <div style='font-size:48px'>🎱</div>
                <h1 style='font-family:sans-serif;font-size:24px;color:#818cf8;margin:8px 0'>Ticket Bingo</h1>
              </div>
              <p style='font-size:15px'>Bonjour <strong>{vente["client"]}</strong>,</p>
              <p style='font-size:14px;color:#9ca3af'>Votre achat de tickets Bingo a bien été enregistré !</p>
              <div style='background:#111218;border:1px solid rgba(255,255,255,0.1);border-radius:10px;padding:16px;margin:20px 0'>
                <p style='margin:4px 0;font-size:13px'>🎮 <strong>Jeu :</strong> {vente["jeu"]}</p>
                <p style='margin:4px 0;font-size:13px'>🔢 <strong>Série :</strong> {vente["serie"]}</p>
                <p style='margin:4px 0;font-size:13px'>📦 <strong>Quantité :</strong> {vente["qty"]}x{vente["pack"]} feuilles</p>
                <p style='margin:4px 0;font-size:13px'>💰 <strong>Total :</strong> {vente["total"]:,} XPF</p>
              </div>
              <div style='text-align:center;margin:24px 0'>
                <a href='https://ticketbingo.space' style='display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#6366f1,#818cf8);color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à mes tickets</a>
              </div>
              <p style='font-size:12px;color:#6b7280;text-align:center'>Accès valable jusqu'au : {expire_str}</p>
              <hr style='border:none;border-top:1px solid rgba(255,255,255,0.1);margin:20px 0'/>
              <p style='font-size:11px;color:#6b7280;text-align:center'>Ticket Bingo — ticketbingo.space</p>
            </div>
            """
            message = Mail(
                from_email=(FROM_EMAIL, FROM_NAME),
                to_emails=vente["email"],
                subject=f"🎱 Vos tickets Bingo — {vente['jeu']}",
                html_content=html
            )
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
            print(f"[EMAIL] Envoyé à {vente['email']}")
        except Exception as e:
            print(f"[EMAIL ERR] {e}")

    return jsonify({"ok": True, "vente": vente})

@app.route("/api/ventes")
def get_ventes():
    return jsonify(DB["ventes"])

@app.route("/api/stats")
def get_stats():
    today = datetime.date.today().isoformat()
    vj = [v for v in DB["ventes"] if v["date"][:10] == today]
    return jsonify({"ventes_jour": len(vj), "tickets_jour": sum(v["total_feuilles"] for v in vj), "total_jour": sum(v["total"] for v in vj)})

@app.route("/api/ticket", methods=["POST"])
def enregistrer_ticket():
    d = request.json
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    code_org = s["code"] if s else "ADMIN"
    if not d.get("acheteur") or not d.get("jeu") or not d.get("serie"):
        return jsonify({"ok": False, "msg": "Champs manquants"}), 400
    code_acheteur = gen_code(6)
    ticket = {
        "id": hashlib.md5(f"{d['acheteur']}{d['serie']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "acheteur": d["acheteur"], "jeu": d["jeu"], "serie": d["serie"],
        "prix": int(d.get("prix", 0)),
        "photo_url": d.get("photo_url", None),
        "pdf_url": d.get("pdf_url", None),
        "page_debut": d.get("page_debut", None),
        "page_fin": d.get("page_fin", None),
        "code_acheteur": code_acheteur,
        "code_org": code_org,
        "date": datetime.datetime.now().isoformat()
    }
    DB["tickets"].insert(0, ticket)
    DB["tickets_acheteurs"][code_acheteur] = ticket["id"]
    save_data()
    return jsonify({"ok": True, "ticket": ticket, "code_acheteur": code_acheteur})

@app.route("/api/tickets")
def get_tickets():
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if s and not s.get("admin"):
        # Organisateur — voir seulement ses tickets
        code_org = s["code"]
        tickets = [t for t in DB["tickets"] if t.get("code_org") == code_org]
        return jsonify(tickets)
    return jsonify(DB["tickets"])

@app.route("/api/ticket/acheteur/<code>")
def get_ticket_acheteur(code):
    ticket_id = DB["tickets_acheteurs"].get(code.upper())
    if not ticket_id:
        return jsonify({"ok": False, "msg": "Code introuvable"}), 404
    ticket = next((t for t in DB["tickets"] if t["id"] == ticket_id), None)
    if not ticket:
        return jsonify({"ok": False, "msg": "Ticket introuvable"}), 404
    return jsonify({"ok": True, "ticket": ticket})

@app.route("/api/verifier", methods=["POST"])
def verifier():
    d = request.json
    jeu = d.get("jeu", "")
    serie = d.get("serie", "").strip()
    trouve = next((t for t in DB["tickets"] if t["jeu"] == jeu and t["serie"].lower() == serie.lower()), None)
    return jsonify({"gagnant": bool(trouve), "ticket": trouve})

@app.route("/api/admin/generer", methods=["POST"])
def admin_generer():
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    nom = d.get("nom", "Client").strip()
    duree = int(d.get("duree", 30))
    code = gen_code()
    while code in DB["codes"]:
        code = gen_code()
    email_org = d.get("email", "")
    DB["codes"][code] = {"duree": duree, "nom": nom, "actif": True, "email": email_org,
                          "created": datetime.datetime.now().isoformat(),
                          "expire": (datetime.datetime.now() + datetime.timedelta(days=duree)).isoformat()}
    save_data()

    # Envoyer email à l organisateur si email fourni
    if email_org and SENDGRID_API_KEY:
        try:
            html = f"""
            <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
              <div style='text-align:center;margin-bottom:24px'>
                <div style='font-size:48px'>🎱</div>
                <h1 style='font-family:sans-serif;font-size:24px;color:#818cf8;margin:8px 0'>Ticket Bingo</h1>
              </div>
              <p style='font-size:15px'>Bonjour <strong>{nom}</strong>,</p>
              <p style='font-size:14px;color:#9ca3af'>Votre accès à Ticket Bingo a été créé ! Voici vos informations de connexion :</p>
              <div style='background:#111218;border:1px solid rgba(99,102,241,0.4);border-radius:10px;padding:20px;margin:20px 0;text-align:center'>
                <div style='font-size:12px;color:#6b7280;margin-bottom:8px'>VOTRE CODE D'ACCÈS</div>
                <div style='font-family:monospace;font-size:32px;font-weight:800;letter-spacing:8px;color:#818cf8'>{code}</div>
              </div>
              <div style='text-align:center;margin:24px 0'>
                <a href='https://ticketbingo.space' style='display:inline-block;padding:14px 32px;background:linear-gradient(135deg,#6366f1,#818cf8);color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à Ticket Bingo</a>
              </div>
              <p style='font-size:12px;color:#6b7280;text-align:center'>Accès valable {duree} jours</p>
              <hr style='border:none;border-top:1px solid rgba(255,255,255,0.1);margin:20px 0'/>
              <p style='font-size:11px;color:#6b7280;text-align:center'>Ticket Bingo — ticketbingo.space</p>
            </div>
            """
            message = Mail(
                from_email=(FROM_EMAIL, FROM_NAME),
                to_emails=email_org,
                subject=f"🎱 Votre accès Ticket Bingo — Code {code}",
                html_content=html
            )
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            sg.send(message)
            print(f"[EMAIL ORG] Envoyé à {email_org}")
        except Exception as e:
            print(f"[EMAIL ORG ERR] {e}")

    return jsonify({"ok": True, "code": code, "nom": nom, "duree": duree})

@app.route("/api/admin/codes")
def admin_codes():
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    codes = [{"code": c, **info} for c, info in DB["codes"].items() if c != "ADMIN2024"]
    return jsonify(codes)

@app.route("/api/admin/desactiver", methods=["POST"])
def admin_desactiver():
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    code = request.json.get("code", "").strip().upper()
    if code in DB["codes"]:
        DB["codes"][code]["actif"] = False
        save_data()
    return jsonify({"ok": True})


@app.route("/api/bingo", methods=["POST"])
def declarer_bingo():
    d = request.json
    alerte = {
        "id": gen_code(8),
        "acheteur": d.get("acheteur", "Inconnu"),
        "jeu": d.get("jeu", ""),
        "serie": d.get("serie", ""),
        "ticket_id": d.get("ticket_id", ""),
        "date": datetime.datetime.now().isoformat(),
        "statut": "en_attente"
    }
    if "alertes_bingo" not in DB:
        DB["alertes_bingo"] = []
    DB["alertes_bingo"].insert(0, alerte)
    save_data()
    return jsonify({"ok": True, "alerte_id": alerte["id"]})

@app.route("/api/bingo/alertes")
def get_alertes_bingo():
    return jsonify(DB.get("alertes_bingo", []))

@app.route("/api/bingo/valider", methods=["POST"])
def valider_bingo():
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    alerte_id = d.get("alerte_id", "")
    statut = d.get("statut", "valide")
    alertes = DB.get("alertes_bingo", [])
    for a in alertes:
        if a["id"] == alerte_id:
            a["statut"] = statut
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json")

@app.route("/icon-192.png")
def icon192():
    return app.send_static_file("icon-192.png")

@app.route("/icon-512.png")
def icon512():
    return app.send_static_file("icon-512.png")

@app.route("/api/tirage", methods=["POST"])
def sauvegarder_tirage():
    d = request.json
    if "tirage" not in DB:
        DB["tirage"] = []
    DB["tirage"] = d.get("boules", [])
    save_data()
    return jsonify({"ok": True})

@app.route("/api/tirage")
def get_tirage():
    return jsonify({"boules": DB.get("tirage", [])})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
