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

# Stockage persistant
DATA_FILE = "/data/ticketbingo_data.json"

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
            for k in ["tickets_acheteurs", "acces_docs", "alertes_bingo", "tirage"]:
                if k not in data:
                    data[k] = [] if k in ["alertes_bingo", "tirage"] else {}
            if not data.get("jeux"):
                data["jeux"] = ["P6", "OHANA 75", "QUINES 90", "OHANA 75 4 SERIE"]
            return data
    except Exception as e:
        print(f"[LOAD ERR] {e}")
    return {
        "ventes": [], "tickets": [],
        "jeux": ["P6", "OHANA 75", "QUINES 90", "OHANA 75 4 SERIE"],
        "tournois": [],
        "codes": {"ADMIN2024": {"duree": 36500, "nom": "Administrateur", "actif": True, "admin": True}},
        "sessions": {}, "acces_docs": {}, "tickets_acheteurs": {},
        "alertes_bingo": [], "tirage": []
    }

# S'assurer que les jeux par defaut sont toujours presents
def ensure_jeux(data):
    jeux_defaut = ["P6", "OHANA 75", "QUINES 90", "OHANA 75 4 SERIE"]
    if not data.get("jeux"):
        data["jeux"] = jeux_defaut
    return data
    }

def save_data():
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE, "w") as f:
            json.dump(DB, f, ensure_ascii=False, default=str)
        print(f"[SAVE OK] {DATA_FILE}")
    except Exception as e:
        print(f"[SAVE ERR] {e}")

DB = load_data()

def gen_code(n=8):
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))

def verif_session(token):
    # Recharger depuis fichier pour avoir sessions a jour
    fresh = load_data()
    s = fresh["sessions"].get(token)
    if not s:
        return None
    if datetime.datetime.now() > datetime.datetime.fromisoformat(s["expire"]):
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

@app.route("/manifest.json")
def manifest():
    return app.send_static_file("manifest.json")

@app.route("/icon-192.png")
def icon192():
    return app.send_static_file("icon-192.png")

@app.route("/icon-512.png")
def icon512():
    return app.send_static_file("icon-512.png")

@app.route("/api/login", methods=["POST"])
def login():
    global DB
    DB = load_data()
    code = request.json.get("code", "").strip().upper()
    info = DB["codes"].get(code)
    if not info or not info["actif"]:
        return jsonify({"ok": False, "msg": "Code invalide ou expiré"}), 401
    # Verifier expiration du code
    if "expire" in info:
        try:
            if datetime.datetime.now() > datetime.datetime.fromisoformat(info["expire"]):
                return jsonify({"ok": False, "msg": "Code invalide ou expiré"}), 401
        except:
            pass
    expire = datetime.datetime.now() + datetime.timedelta(days=30)
    token = secrets.token_hex(16)
    DB["sessions"][token] = {
        "code": code, "nom": info["nom"],
        "expire": expire.isoformat(),
        "admin": info.get("admin", False)
    }
    save_data()
    return jsonify({"ok": True, "token": token, "nom": info["nom"], "admin": info.get("admin", False), "code_org": code})

@app.route("/api/jeux")
def get_jeux():
    global DB
    DB = load_data()
    return jsonify(DB["jeux"])

@app.route("/api/jeux", methods=["POST"])
def add_jeu():
    global DB
    DB = load_data()
    nom = request.json.get("nom", "").strip()
    if nom and nom not in DB["jeux"]:
        DB["jeux"].append(nom)
        save_data()
    return jsonify(DB["jeux"])

@app.route("/api/jeux/<nom>", methods=["DELETE"])
def del_jeu(nom):
    global DB
    DB = load_data()
    if nom in DB["jeux"]:
        DB["jeux"].remove(nom)
        save_data()
    return jsonify(DB["jeux"])

@app.route("/api/tournoi", methods=["POST"])
def creer_tournoi():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    tournoi = {
        "id": gen_code(6), "nom": d.get("nom", ""), "jeu": d.get("jeu", ""),
        "date_tournoi": d.get("date_tournoi", ""),
        "created": datetime.datetime.now().isoformat()
    }
    DB["tournois"].insert(0, tournoi)
    save_data()
    return jsonify({"ok": True, "tournoi": tournoi})

@app.route("/api/tournois")
def get_tournois():
    global DB
    DB = load_data()
    return jsonify(DB["tournois"])

@app.route("/api/upload-pdf", methods=["POST"])
def upload_pdf():
    """Stocke le PDF dans /data/pdfs et retourne une URL locale"""
    try:
        d = request.json
        pdf_b64 = d.get("pdf_b64", "")
        if not pdf_b64:
            return jsonify({"ok": False, "msg": "PDF manquant"}), 400
        pdf_id = secrets.token_hex(16)
        pdf_dir = "/data/pdfs"
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_path = f"{pdf_dir}/{pdf_id}.pdf"
        with open(pdf_path, "wb") as f:
            f.write(base64.b64decode(pdf_b64))
        print(f"[PDF UPLOAD OK] {pdf_path}")
        return jsonify({"ok": True, "pdf_url": f"/api/pdf/{pdf_id}"})
    except Exception as e:
        print(f"[PDF UPLOAD ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/pdf/<pdf_id>")
def serve_pdf(pdf_id):
    """Sert un PDF depuis /data/pdfs"""
    if not all(c in '0123456789abcdef' for c in pdf_id):
        return jsonify({"ok": False}), 400
    pdf_path = f"/data/pdfs/{pdf_id}.pdf"
    if not os.path.exists(pdf_path):
        return jsonify({"ok": False, "msg": "PDF introuvable"}), 404
    with open(pdf_path, "rb") as f:
        data = f.read()
    return Response(data, content_type="application/pdf", headers={
        "Access-Control-Allow-Origin": "*",
        "Content-Disposition": "inline",
        "Cache-Control": "public, max-age=3600"
    })
@app.route("/api/vente", methods=["POST"])
def nouvelle_vente():
    global DB
    DB = load_data()
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
    DB["acces_docs"][token_doc] = {
        "vente_id": vente["id"], "client": vente["client"],
        "jeu": vente["jeu"], "date_expiration": date_expiration, "acces_count": 0
    }
    save_data()

    if vente["email"] and SENDGRID_API_KEY:
        try:
            html = f"""
            <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
              <div style='text-align:center;margin-bottom:24px'>
                <div style='font-size:48px'>🎱</div>
                <h1 style='font-size:24px;color:#818cf8;margin:8px 0'>Ticket Bingo</h1>
              </div>
              <p>Bonjour <strong>{vente["client"]}</strong>,</p>
              <div style='background:#111218;border-radius:10px;padding:16px;margin:20px 0'>
                <p>🎮 Jeu : {vente["jeu"]}</p>
                <p>🔢 Série : {vente["serie"]}</p>
                <p>📦 Quantité : {vente["qty"]}x{vente["pack"]} feuilles</p>
                <p>💰 Total : {vente["total"]:,} XPF</p>
              </div>
              <div style='text-align:center;margin:24px 0'>
                <a href='https://ticketbingo.space' style='padding:14px 32px;background:#6366f1;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à mes tickets</a>
              </div>
            </div>"""
            message = Mail(from_email=(FROM_EMAIL, FROM_NAME), to_emails=vente["email"],
                          subject=f"🎱 Vos tickets Bingo — {vente['jeu']}", html_content=html)
            SendGridAPIClient(SENDGRID_API_KEY).send(message)
            print(f"[EMAIL] Envoyé à {vente['email']}")
        except Exception as e:
            print(f"[EMAIL ERR] {e}")

    return jsonify({"ok": True, "vente": vente})

@app.route("/api/ventes")
def get_ventes():
    global DB
    DB = load_data()
    return jsonify(DB["ventes"])

@app.route("/api/stats")
def get_stats():
    global DB
    DB = load_data()
    today = datetime.date.today().isoformat()
    vj = [v for v in DB["ventes"] if v["date"][:10] == today]
    return jsonify({"ventes_jour": len(vj), "tickets_jour": sum(v["total_feuilles"] for v in vj), "total_jour": sum(v["total"] for v in vj)})

@app.route("/api/ticket", methods=["POST"])
def enregistrer_ticket():
    global DB
    DB = load_data()
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
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if s and not s.get("admin"):
        code_org = s["code"]
        tickets = [t for t in DB["tickets"] if t.get("code_org") == code_org]
        return jsonify(tickets)
    return jsonify(DB["tickets"])

@app.route("/api/ticket/acheteur/<code>")
def get_ticket_acheteur(code):
    global DB
    DB = load_data()
    code = code.upper().strip()
    # Chercher dans tickets_acheteurs
    ticket_id = DB.get("tickets_acheteurs", {}).get(code)
    if ticket_id:
        ticket = next((t for t in DB["tickets"] if t["id"] == ticket_id), None)
        if ticket:
            return jsonify({"ok": True, "ticket": ticket})
    # Chercher directement dans tickets par code_acheteur
    ticket = next((t for t in DB["tickets"] if t.get("code_acheteur", "").upper() == code), None)
    if ticket:
        return jsonify({"ok": True, "ticket": ticket})
    return jsonify({"ok": False, "msg": "Code introuvable"}), 404

@app.route("/api/verifier", methods=["POST"])
def verifier():
    global DB
    DB = load_data()
    d = request.json
    jeu = d.get("jeu", "")
    serie = d.get("serie", "").strip()
    trouve = next((t for t in DB["tickets"] if t["jeu"] == jeu and t["serie"].lower() == serie.lower()), None)
    return jsonify({"gagnant": bool(trouve), "ticket": trouve})

@app.route("/api/admin/generer", methods=["POST"])
def admin_generer():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    nom = d.get("nom", "Client").strip()
    duree = int(d.get("duree", 30))
    email_org = d.get("email", "")
    code = gen_code()
    while code in DB["codes"]:
        code = gen_code()
    DB["codes"][code] = {
        "duree": duree, "nom": nom, "actif": True, "email": email_org,
        "created": datetime.datetime.now().isoformat(),
        "expire": (datetime.datetime.now() + datetime.timedelta(days=duree)).isoformat()
    }
    save_data()

    if email_org and SENDGRID_API_KEY:
        try:
            html = f"""
            <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
              <div style='text-align:center;margin-bottom:24px'>
                <div style='font-size:48px'>🎱</div>
                <h1 style='font-size:24px;color:#818cf8;margin:8px 0'>Ticket Bingo</h1>
              </div>
              <p>Bonjour <strong>{nom}</strong>,</p>
              <p>Votre accès à Ticket Bingo a été créé !</p>
              <div style='background:#111218;border:1px solid rgba(99,102,241,0.4);border-radius:10px;padding:20px;margin:20px 0;text-align:center'>
                <div style='font-size:12px;color:#6b7280;margin-bottom:8px'>VOTRE CODE D ACCESS</div>
                <div style='font-family:monospace;font-size:32px;font-weight:800;letter-spacing:8px;color:#818cf8'>{code}</div>
              </div>
              <div style='text-align:center;margin:24px 0'>
                <a href='https://ticketbingo.space' style='padding:14px 32px;background:#6366f1;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à Ticket Bingo</a>
              </div>
              <p style='font-size:12px;color:#6b7280;text-align:center'>Accès valable {duree} jours</p>
            </div>"""
            message = Mail(from_email=(FROM_EMAIL, FROM_NAME), to_emails=email_org,
                          subject=f"🎱 Votre accès Ticket Bingo — Code {code}", html_content=html)
            SendGridAPIClient(SENDGRID_API_KEY).send(message)
            print(f"[EMAIL ORG] Envoyé à {email_org}")
        except Exception as e:
            print(f"[EMAIL ORG ERR] {e}")

    return jsonify({"ok": True, "code": code, "nom": nom, "duree": duree})

@app.route("/api/admin/codes")
def admin_codes():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    codes = [{"code": c, **info} for c, info in DB["codes"].items() if c != "ADMIN2024"]
    return jsonify(codes)

@app.route("/api/revendeur/generer", methods=["POST"])
def generer_revendeur():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    code_org = s["code"]
    d = request.json
    nom = d.get("nom", "Revendeur").strip()
    email_rev = d.get("email", "")
    duree = int(d.get("duree", 30))
    code = gen_code()
    while code in DB["codes"]:
        code = gen_code()
    DB["codes"][code] = {
        "duree": duree, "nom": nom, "actif": True, "email": email_rev,
        "role": "revendeur", "code_org": code_org,
        "created": datetime.datetime.now().isoformat(),
        "expire": (datetime.datetime.now() + datetime.timedelta(days=duree)).isoformat()
    }
    save_data()

    if email_rev and SENDGRID_API_KEY:
        try:
            html = f"""
            <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
              <div style='text-align:center;margin-bottom:24px'>
                <div style='font-size:48px'>🎱</div>
                <h1 style='font-size:24px;color:#818cf8;margin:8px 0'>Ticket Bingo</h1>
              </div>
              <p>Bonjour <strong>{nom}</strong>,</p>
              <p>Vous avez été ajouté comme revendeur sur Ticket Bingo !</p>
              <div style='background:#111218;border:1px solid rgba(99,102,241,0.4);border-radius:10px;padding:20px;margin:20px 0;text-align:center'>
                <div style='font-size:12px;color:#6b7280;margin-bottom:8px'>VOTRE CODE REVENDEUR</div>
                <div style='font-family:monospace;font-size:32px;font-weight:800;letter-spacing:8px;color:#818cf8'>{code}</div>
              </div>
              <div style='text-align:center;margin:24px 0'>
                <a href='https://ticketbingo.space' style='padding:14px 32px;background:#6366f1;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à Ticket Bingo</a>
              </div>
              <p style='font-size:12px;color:#6b7280;text-align:center'>Accès valable {duree} jours</p>
            </div>"""
            message = Mail(from_email=(FROM_EMAIL, FROM_NAME), to_emails=email_rev,
                          subject=f"🎱 Votre accès Revendeur Ticket Bingo — Code {code}", html_content=html)
            SendGridAPIClient(SENDGRID_API_KEY).send(message)
            print(f"[EMAIL REV] Envoyé à {email_rev}")
        except Exception as e:
            print(f"[EMAIL REV ERR] {e}")

    return jsonify({"ok": True, "code": code, "nom": nom, "duree": duree})

@app.route("/api/revendeur/liste")
def liste_revendeurs():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    code_org = s["code"]
    revendeurs = [{"code": c, **info} for c, info in DB["codes"].items() 
                  if info.get("role") == "revendeur" and info.get("code_org") == code_org]
    return jsonify(revendeurs)

@app.route("/api/admin/desactiver", methods=["POST"])
def admin_desactiver():
    global DB
    DB = load_data()
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
    global DB
    DB = load_data()
    d = request.json
    alerte = {
        "id": gen_code(8),
        "acheteur": d.get("acheteur", "Inconnu"),
        "jeu": d.get("jeu", ""),
        "serie": d.get("serie", ""),
        "ticket_id": d.get("ticketId", ""),
        "pdf_url": d.get("pdf_url", None),
        "page_debut": d.get("page_debut", None),
        "page_fin": d.get("page_fin", None),
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
    global DB
    DB = load_data()
    return jsonify(DB.get("alertes_bingo", []))

@app.route("/api/bingo/valider", methods=["POST"])
def valider_bingo():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    alerte_id = d.get("alerte_id", "")
    statut = d.get("statut", "valide")
    for a in DB.get("alertes_bingo", []):
        if a["id"] == alerte_id:
            a["statut"] = statut
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/api/tirage", methods=["POST"])
def sauvegarder_tirage():
    global DB
    DB = load_data()
    d = request.json
    DB["tirage"] = d.get("boules", [])
    save_data()
    return jsonify({"ok": True})

@app.route("/api/tirage")
def get_tirage():
    global DB
    DB = load_data()
    return jsonify({"boules": DB.get("tirage", [])})

@app.route("/api/proxy-pdf")
def proxy_pdf():
    """Proxy pour servir les PDFs depuis Cloudinary"""
    try:
        url = request.args.get("url", "")
        if not url or "cloudinary.com" not in url:
            return jsonify({"ok": False}), 400
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        return Response(data, content_type="application/pdf", headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": "inline",
            "Cache-Control": "public, max-age=3600"
        })
    except Exception as e:
        print(f"[PROXY ERR] {e}")
        return jsonify({"ok": False}), 500

@app.route("/api/demande-acces", methods=["POST"])
def demande_acces():
    d = request.json
    nom = d.get("nom", "")
    email = d.get("email", "")
    tel = d.get("tel", "")
    formule = d.get("formule", "")
    
    formules = {
        "1mois": "1 mois — 4 990 XPF",
        "3mois": "3 mois — 12 000 XPF",
        "6mois": "6 mois — 22 000 XPF",
        "1an": "1 an — 40 000 XPF"
    }
    formule_txt = formules.get(formule, formule)
    
    if SENDGRID_API_KEY:
        try:
            html = f"""
            <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
              <div style='text-align:center;margin-bottom:24px'>
                <div style='font-size:48px'>🎪</div>
                <h1 style='font-size:20px;color:#818cf8;margin:8px 0'>Nouvelle demande d accès Organisateur</h1>
              </div>
              <div style='background:#111218;border-radius:10px;padding:16px;margin:20px 0'>
                <p>👤 <b>Nom :</b> {nom}</p>
                <p>📧 <b>Email :</b> {email}</p>
                <p>📞 <b>Téléphone :</b> {tel}</p>
                <p>📋 <b>Formule :</b> {formule_txt}</p>
              </div>
              <p style='color:#6b7280;font-size:13px'>Générez le code depuis l'onglet Admin après réception du paiement.</p>
            </div>"""
            message = Mail(
                from_email=(FROM_EMAIL, FROM_NAME),
                to_emails=FROM_EMAIL,
                subject=f"🎪 Nouvelle demande organisateur — {nom}",
                html_content=html
            )
            SendGridAPIClient(SENDGRID_API_KEY).send(message)
            print(f"[DEMANDE] {nom} - {email} - {formule_txt}")
        except Exception as e:
            print(f"[DEMANDE ERR] {e}")
    
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
