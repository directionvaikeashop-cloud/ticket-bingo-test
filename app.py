import hashlib, datetime, os, secrets, string, json, base64
import urllib.request, urllib.parse
from flask import Flask, request, jsonify, send_from_directory, Response, send_file
try:
    from flask_sock import Sock
    HAS_WEBSOCKET = True
except:
    HAS_WEBSOCKET = False
try:
    import stripe
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if STRIPE_SECRET_KEY:
        stripe.api_key = STRIPE_SECRET_KEY
except ImportError:
    stripe = None
    STRIPE_SECRET_KEY = ""
    STRIPE_WEBHOOK_SECRET = ""
from generate_triple_action_75 import generate_pdf as generate_ta75_pdf
from generate_60_boules import generate_pdf as generate_60b_pdf
from generate_40_boules import generate_pdf as generate_40b_pdf
from generate_4_coins import generate_pdf as generate_4coins_pdf
from generate_500_francs import generate_pdf as generate_500f_pdf
from generate_1_dollar import generate_pdf as generate_1dollar_pdf
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__, static_folder=".")
if HAS_WEBSOCKET:
    sock = Sock(app)

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "directionvaikeashop@gmail.com")
FROM_NAME = "Ticket Bingo"
CLOUDINARY_CLOUD = os.environ.get("CLOUDINARY_CLOUD", "dz556b0ee")
CLOUDINARY_PRESET = "alerte_upload"

# Stockage persistant
DATA_FILE = "/data/ticketbingo_data.json"

import threading
_VERROU_SAUVEGARDE = threading.Lock()

def load_data():
    # Essayer le fichier principal, puis la copie de secours (.bak)
    for chemin in [DATA_FILE, DATA_FILE + ".bak"]:
        try:
            if os.path.exists(chemin):
                with open(chemin, "r") as f:
                    data = json.load(f)
                if chemin.endswith(".bak"):
                    print("[LOAD] Fichier principal illisible — copie de secours utilisée")
                for k in ["tickets_acheteurs", "acces_docs", "alertes_bingo", "tirage"]:
                    if k not in data:
                        data[k] = [] if k in ["alertes_bingo", "tirage"] else {}
                if not data.get("jeux"):
                    data["jeux"] = ["P6", "OHANA 75", "QUINES 90", "OHANA 75 4 SERIE"]
                return data
        except Exception as e:
            print(f"[LOAD ERR] {chemin}: {e}")
            # Conserver le fichier abime pour recuperation eventuelle (jamais l'ecraser)
            try:
                import shutil
                horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy(chemin, chemin + ".corrompu_" + horodatage)
            except Exception:
                pass
    print("[LOAD] ATTENTION : aucune donnée lisible — démarrage sur base vide")
    return {
        "ventes": [], "tickets": [],
        "jeux": ["P6", "OHANA 75", "QUINES 90", "OHANA 75 4 SERIE"],
        "tournois": [],
        "codes": {"ADMIN2024": {"duree": 36500, "nom": "Administrateur", "actif": True, "admin": True}},
        "sessions": {}, "acces_docs": {}, "tickets_acheteurs": {},
        "alertes_bingo": [], "tirage": []
    }

def save_data():
    try:
        with _VERROU_SAUVEGARDE:
            os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
            # 1) Ecrire dans un fichier TEMPORAIRE (le fichier principal n'est jamais a moitie ecrit)
            tmp = DATA_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(DB, f, ensure_ascii=False, default=str)
                f.flush()
                os.fsync(f.fileno())
            # 2) Conserver la version precedente comme copie de secours
            if os.path.exists(DATA_FILE):
                try:
                    os.replace(DATA_FILE, DATA_FILE + ".bak")
                except Exception:
                    pass
            # 3) Remplacement ATOMIQUE : soit l'ancien fichier, soit le nouveau, jamais un fichier abime
            os.replace(tmp, DATA_FILE)
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
    # Si pas de date d'expiration (admin) ou session non expirée
    if s.get("expire"):
        try:
            if datetime.datetime.now() > datetime.datetime.fromisoformat(s["expire"]):
                return None
        except:
            pass
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
    # Admin = session sans expiration, autres = 30 jours
    if info.get("admin"):
        expire = datetime.datetime.now() + datetime.timedelta(days=3650)
    else:
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
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    code_destinataire = d.get("code_org_destinataire", "")
    if s and s.get("admin") and code_destinataire:
        code_org_vente = code_destinataire
    else:
        code_org_vente = s["code"] if s else "ADMIN"
    vente = {
        "id": hashlib.md5(f"{d['client']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "client": d["client"], "email": d.get("email", ""), "jeu": d["jeu"],
        "code_org": code_org_vente,
        "paiement_statut": "en_attente",
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
                <a href='https://ticket-bingo-production.up.railway.app' style='padding:14px 32px;background:#6366f1;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à mes tickets</a>
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
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    # Admin voit tout
    if s and s.get("admin"):
        return jsonify(DB["ventes"])
    # Organisateur voit seulement ses ventes
    if s:
        code_org = s["code"]
        ventes = [v for v in DB["ventes"] if v.get("code_org") == code_org]
        return jsonify(ventes)
    return jsonify([])

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
    email_joueur = d.get("email", "")
    ticket = {
        "id": hashlib.md5(f"{d['acheteur']}{d['serie']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "acheteur": d["acheteur"], "jeu": d["jeu"], "serie": d["serie"],
        "prix": int(d.get("prix", 0)),
        "photo_url": d.get("photo_url", None),
        "pdf_url": d.get("pdf_url", None),
        "page_debut": d.get("page_debut", None),
        "page_fin": d.get("page_fin", None),
        "code_acheteur": code_acheteur,
        "email": email_joueur,
        "code_org": code_org,
        "date": datetime.datetime.now().isoformat()
    }
    DB["tickets"].insert(0, ticket)
    DB["tickets_acheteurs"][code_acheteur] = ticket["id"]
    save_data()

    # Envoyer email au joueur si email fourni
    if email_joueur and SENDGRID_API_KEY:
        try:
            page_info = ""
            if ticket["page_debut"] and ticket["page_fin"]:
                page_info = f"<p>📄 Vos feuilles : pages {ticket['page_debut']} à {ticket['page_fin']}</p>"
            html = f"""
            <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
              <div style='text-align:center;margin-bottom:24px'>
                <div style='font-size:48px'>🎱</div>
                <h1 style='font-size:24px;color:#818cf8;margin:8px 0'>Ticket Bingo</h1>
              </div>
              <p>Bonjour <strong>{ticket['acheteur']}</strong> !</p>
              <p>Votre ticket a été enregistré. Voici votre code d'accès :</p>
              <div style='background:#111218;border:2px solid #6366f1;border-radius:12px;padding:24px;margin:20px 0;text-align:center'>
                <div style='font-size:12px;color:#6b7280;margin-bottom:8px'>VOTRE CODE TICKET</div>
                <div style='font-family:monospace;font-size:40px;font-weight:800;letter-spacing:10px;color:#818cf8'>{code_acheteur}</div>
              </div>
              <div style='background:#1a1040;border-radius:10px;padding:16px;margin:16px 0'>
                <p>🎮 Jeu : <strong>{ticket['jeu']}</strong></p>
                <p>🔢 Série : <strong>{ticket['serie']}</strong></p>
                {page_info}
              </div>
              <div style='text-align:center;margin:24px 0'>
                <a href='https://ticket-bingo-production.up.railway.app' style='padding:14px 32px;background:#6366f1;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à mon ticket</a>
              </div>
              <p style='font-size:12px;color:#6b7280;text-align:center'>Entrez votre code dans la section 🎮 Espace Joueur</p>
            </div>"""
            message = Mail(from_email=(FROM_EMAIL, FROM_NAME), to_emails=email_joueur,
                          subject=f"🎱 Votre ticket Bingo — Code {code_acheteur}", html_content=html)
            SendGridAPIClient(SENDGRID_API_KEY).send(message)
            print(f"[EMAIL JOUEUR] Envoyé à {email_joueur}")
        except Exception as e:
            print(f"[EMAIL JOUEUR ERR] {e}")

    return jsonify({"ok": True, "ticket": ticket, "code_acheteur": code_acheteur})

@app.route("/api/tickets")
def get_tickets():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    # Admin voit tout
    if s and s.get("admin"):
        return jsonify(DB["tickets"])
    # Organisateur/revendeur voit seulement ses tickets
    if s:
        code_org = s["code"]
        # Vérifier si c'est un revendeur
        info = DB["codes"].get(code_org, {})
        if info.get("role") == "revendeur":
            # Revendeur voit ses propres tickets ET ceux de son organisateur
            code_org_parent = info.get("code_org", "")
            tickets = [t for t in DB["tickets"] if t.get("code_org") == code_org]
            return jsonify(tickets)
        else:
            # Organisateur voit ses tickets
            tickets = [t for t in DB["tickets"] if t.get("code_org") == code_org]
            return jsonify(tickets)
    return jsonify([])

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
                <a href='https://ticket-bingo-production.up.railway.app' style='padding:14px 32px;background:#6366f1;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à Ticket Bingo</a>
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
                <a href='https://ticket-bingo-production.up.railway.app' style='padding:14px 32px;background:#6366f1;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Accéder à Ticket Bingo</a>
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
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    # Trouver l'organisateur du ticket
    ticket_id = d.get("ticketId", "")
    ticket = next((t for t in DB["tickets"] if t["id"] == ticket_id), None)
    code_org_alerte = ticket.get("code_org", "") if ticket else ""
    
    alerte = {
        "id": gen_code(8),
        "acheteur": d.get("acheteur", "Inconnu"),
        "code_org": code_org_alerte,
        "jeu": d.get("jeu", ""),
        "serie": d.get("serie", ""),
        "ticket_id": d.get("ticketId", ""),
        "pdf_url": d.get("pdf_url", None),
        "page_debut": d.get("page_debut", None),
        "page_fin": d.get("page_fin", None),
        "coches": d.get("coches", []),
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
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    alertes = DB.get("alertes_bingo", [])
    # Admin voit toutes les alertes
    if s and s.get("admin"):
        return jsonify(alertes)
    # Organisateur voit seulement ses alertes
    if s:
        code_org = s["code"]
        alertes = [a for a in alertes if a.get("code_org") == code_org or not a.get("code_org")]
        return jsonify(alertes)
    return jsonify([])

import threading

def effacer_pdfs_apres_tournoi(code_org, delai_secondes=10800):
    """Efface les PDFs 3 heures après validation du gagnant"""
    import time
    time.sleep(delai_secondes)
    try:
        global DB
        DB = load_data()
        
        pdfs_supprimes = []
        
        # Effacer les PDFs de cet organisateur
        tickets = [t for t in DB.get("tickets", []) if t.get("code_org") == code_org]
        for ticket in tickets:
            pdf_url = ticket.get("pdf_url", "")
            if pdf_url:
                # Extraire l'ID du PDF depuis l'URL
                pdf_id = pdf_url.split("/")[-1].replace(".pdf", "")
                pdf_path = f"/data/pdfs/{pdf_id}.pdf"
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
                    pdfs_supprimes.append(pdf_path)
        
        # Effacer les PDFs de commandes
        commandes = [c for c in DB.get("commandes", []) if c.get("code_org") == code_org]
        for commande in commandes:
            pdf_path = commande.get("pdf_path", "")
            if pdf_path and os.path.exists(pdf_path):
                os.remove(pdf_path)
                pdfs_supprimes.append(pdf_path)
        
        # Effacer aussi les PDFs dans /data/*.pdf liés à cet organisateur
        if os.path.exists("/data"):
            for f in os.listdir("/data"):
                if f.endswith(".pdf"):
                    try:
                        os.remove(f"/data/{f}")
                        pdfs_supprimes.append(f"/data/{f}")
                    except:
                        pass
        
        # Enregistrer dans DB
        if "historique_effacement" not in DB:
            DB["historique_effacement"] = []
        DB["historique_effacement"].append({
            "code_org": code_org,
            "date": datetime.datetime.now().isoformat(),
            "nb_pdfs_supprimes": len(pdfs_supprimes),
            "pdfs": pdfs_supprimes
        })
        save_data()
        print(f"[AUTO-EFFACEMENT] {len(pdfs_supprimes)} PDFs effacés pour {code_org}")
    except Exception as e:
        print(f"[AUTO-EFFACEMENT ERR] {e}")

# === COMMANDES TICKETS ORGANISATEUR ===
# === NOUVEAU SYSTEME PIONS ===
@app.route("/api/pions/commande", methods=["POST"])
def commander_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    code_org = s["code"]
    valeur_pion = int(d.get("valeur_pion", 0))
    montant_paye = float(d.get("montant_paye", 0))
    commission = float(d.get("commission", 0))
    nb_pions = int(d.get("nb_pions", 0))
    if not valeur_pion or montant_paye < 500 or nb_pions <= 0:
        return jsonify({"ok": False, "msg": "Données invalides"}), 400
    if "commandes_pions" not in DB:
        DB["commandes_pions"] = []
    mode_paiement = d.get("mode_paiement", "")
    ref_paiement = d.get("ref_paiement", "")
    
    # Si le mode de paiement est fourni, passer directement en en_attente_validation
    statut_initial = "en_attente_validation" if mode_paiement else "en_attente"
    
    commande = {
        "id": secrets.token_hex(4).upper(),
        "code_org": code_org,
        "nom_org": s.get("nom", code_org),
        "valeur_pion": valeur_pion,
        "montant_paye": montant_paye,
        "commission": commission,
        "nb_pions": nb_pions,
        "statut": statut_initial,
        "mode_paiement": mode_paiement,
        "ref_paiement": ref_paiement,
        "date": datetime.datetime.now().isoformat()
    }
    DB["commandes_pions"].insert(0, commande)
    save_data()
    return jsonify({"ok": True, "commande_id": commande["id"]})

@app.route("/api/pions/mes-commandes")
def mes_commandes_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify([])
    commandes = DB.get("commandes_pions", [])
    if s.get("admin"):
        return jsonify(commandes)
    return jsonify([c for c in commandes if c.get("code_org") == s["code"]])

@app.route("/api/pions/soldes")
def get_soldes_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    code_org = s["code"]
    pions = DB.get("pions_org", {}).get(code_org, {})
    return jsonify({
        "pions_20": pions.get("20", 0),
        "pions_50": pions.get("50", 0),
        "pions_100": pions.get("100", 0)
    })

@app.route("/api/pions/confirmer-paiement", methods=["POST"])
def confirmer_paiement_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    d = request.json
    commande_id = d.get("commande_id", "")
    mode = d.get("mode", "")
    ref = d.get("ref", "")
    for c in DB.get("commandes_pions", []):
        if c["id"] == commande_id and c["code_org"] == s["code"]:
            c["statut"] = "en_attente_validation"
            c["mode_paiement"] = mode
            c["ref_paiement"] = ref
            c["date_confirmation"] = datetime.datetime.now().isoformat()
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/api/pions/valider-commande", methods=["POST"])
def valider_commande_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    commande_id = request.json.get("commande_id", "")
    for c in DB.get("commandes_pions", []):
        if c["id"] == commande_id and c.get("statut") in ["en_attente", "en_attente_validation"]:
            c["statut"] = "validee"
            code_org = c["code_org"]
            valeur = str(c["valeur_pion"])
            nb = c["nb_pions"]
            if "pions_org" not in DB:
                DB["pions_org"] = {}
            if code_org not in DB["pions_org"]:
                DB["pions_org"][code_org] = {}
            DB["pions_org"][code_org][valeur] = DB["pions_org"][code_org].get(valeur, 0) + nb
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/api/pions/donner", methods=["POST"])
def donner_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    d = request.json
    code_org = s["code"]
    code_joueur = d.get("code_joueur", "").upper()
    valeur_pion = str(d.get("valeur_pion", 0))
    nb_pions = int(d.get("nb_pions", 0))
    # Vérifier solde
    solde = DB.get("pions_org", {}).get(code_org, {}).get(valeur_pion, 0)
    if nb_pions > solde:
        return jsonify({"ok": False, "msg": f"Solde insuffisant — vous avez {solde} pions à {valeur_pion} XPF"}), 400
    # Débiter organisateur
    DB["pions_org"][code_org][valeur_pion] -= nb_pions
    # Créditer joueur
    if "pions_joueurs" not in DB:
        DB["pions_joueurs"] = {}
    if code_joueur not in DB["pions_joueurs"]:
        DB["pions_joueurs"][code_joueur] = {}
    DB["pions_joueurs"][code_joueur][valeur_pion] = DB["pions_joueurs"][code_joueur].get(valeur_pion, 0) + nb_pions
    save_data()
    return jsonify({"ok": True})

@app.route("/api/admin/reset-donnees", methods=["POST"])
def reset_donnees_admin():
    """Remet toutes les données à zéro sauf les codes"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    # Effacer toutes les données de test
    DB["ventes"] = []
    DB["tickets"] = []
    DB["alertes_bingo"] = []
    DB["tirage"] = []
    DB["tirage_vitesse"] = 3
    DB["coches"] = {}
    DB["commandes_tickets"] = []
    DB["paiements_stripe"] = []
    DB["gains_finaux"] = []
    
    # Effacer les PDFs physiques
    import os
    pdf_dir = "/data/pdfs"
    if os.path.exists(pdf_dir):
        for f in os.listdir(pdf_dir):
            if f.endswith(".pdf"):
                try:
                    os.remove(os.path.join(pdf_dir, f))
                except:
                    pass
    
    save_data()
    print("[RESET ADMIN] Toutes les données remises à zéro")
    return jsonify({"ok": True})

@app.route("/api/commande/passer", methods=["POST"])
def passer_commande():
    """L'organisateur passe une commande de tickets"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    d = request.json
    code_org = s["code"]
    jeu = d.get("jeu", "")
    pack = int(d.get("pack", 0))
    prix = int(d.get("prix", 0))
    serie = d.get("serie", "1")
    
    if not jeu or not pack:
        return jsonify({"ok": False, "msg": "Champs manquants"}), 400
    
    if "commandes_tickets" not in DB:
        DB["commandes_tickets"] = []
    
    commande = {
        "id": secrets.token_hex(4).upper(),
        "code_org": code_org,
        "nom_org": s.get("nom", code_org),
        "jeu": jeu,
        "pack": pack,
        "prix": prix,
        "serie": serie,
        "statut": "en_attente",
        "date": datetime.datetime.now().isoformat()
    }
    
    DB["commandes_tickets"].insert(0, commande)
    save_data()
    print(f"[COMMANDE] {code_org} commande {pack} tickets {jeu}")
    return jsonify({"ok": True, "commande_id": commande["id"]})

@app.route("/api/commande/liste")
def get_commandes():
    """Liste des commandes"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify([])
    
    commandes = DB.get("commandes_tickets", [])
    
    # Admin voit tout, organisateur voit ses commandes
    if s.get("admin"):
        return jsonify(commandes)
    
    mes_commandes = [c for c in commandes if c.get("code_org") == s["code"]]
    return jsonify(mes_commandes)

@app.route("/api/commande/traiter", methods=["POST"])
def traiter_commande():
    """Marquer une commande comme traitée"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    
    commande_id = request.json.get("commande_id", "")
    for c in DB.get("commandes_tickets", []):
        if c["id"] == commande_id:
            c["statut"] = "traitee"
            c["date_traitement"] = datetime.datetime.now().isoformat()
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/api/commande/annuler", methods=["POST"])
def annuler_commande():
    """Annuler une commande"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    
    commande_id = request.json.get("commande_id", "")
    for c in DB.get("commandes_tickets", []):
        if c["id"] == commande_id:
            c["statut"] = "annulee"
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/api/tournoi/reset", methods=["POST"])
def reset_tournoi():
    """Remet tout à zéro après un tournoi"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    code_org = s["code"]
    
    # 1. Remettre le tirage à zéro
    DB["tirage"] = []
    DB["tirage_vitesse"] = 3
    
    # 2. Effacer TOUTES les alertes bingo
    DB["alertes_bingo"] = []
    
    # 3. Effacer les tickets vendus aux joueurs pour ce tournoi
    DB["tickets"] = [t for t in DB.get("tickets", []) if t.get("code_org") != code_org]
    
    # 4. Effacer les coches/pointages joueurs
    DB["coches"] = {}
    
    # 5. Les ventes (PDFs achetés par l'organisateur) RESTENT INTACTES
    # On efface uniquement les tickets joueurs, pas les achats de l'organisateur
    
    # 6. Effacer les commandes tickets pions de ce tournoi
    DB["commandes_tickets_pions"] = [c for c in DB.get("commandes_tickets_pions", []) if c.get("code_org") != code_org]
    
    # 7. Supprimer l'annonce du jeu en cours
    DB["annonces_jeux"] = [a for a in DB.get("annonces_jeux", []) if a.get("code_org") != code_org]
    
    # 8. Remettre le micro à zéro
    DB["micro_status"] = {"actif": False, "message": ""}
    
    # NE PAS EFFACER : codes joueurs, codes organisateurs, soldes pions, ventes/PDFs organisateur
    
    save_data()
    print(f"[RESET] Tournoi remis à zéro pour {code_org}")
    return jsonify({"ok": True, "message": "Tournoi remis à zéro !"})

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
    code_org = s["code"]
    
    for a in DB.get("alertes_bingo", []):
        if a["id"] == alerte_id:
            a["statut"] = statut
            break
    
    # Enregistrer la fin du tournoi
    if "tournois_termines" not in DB:
        DB["tournois_termines"] = []
    DB["tournois_termines"].append({
        "code_org": code_org,
        "alerte_id": alerte_id,
        "date_fin": datetime.datetime.now().isoformat(),
        "effacement_prevu": (datetime.datetime.now() + datetime.timedelta(minutes=10)).isoformat()
    })
    save_data()
    
    # Lancer le timer d'effacement automatique (3 heures = 10800 secondes)
    if statut == "valide":
        timer = threading.Thread(
            target=effacer_pdfs_apres_tournoi,
            args=(code_org, 600),
            daemon=True
        )
        timer.start()
        print(f"[TIMER] Effacement PDFs programmé dans 10 minutes pour {code_org}")
    
    return jsonify({"ok": True, "message": "Gagnant validé ! PDFs effacés automatiquement dans 3 heures."})

@app.route("/api/tirage", methods=["POST"])
def sauvegarder_tirage():
    global DB
    DB = load_data()
    d = request.json
    DB["tirage"] = d.get("boules", [])
    DB["tirage_vitesse"] = d.get("vitesse", 3)
    save_data()
    return jsonify({"ok": True})

@app.route("/api/tirage")
def get_tirage():
    global DB
    DB = load_data()
    return jsonify({"boules": DB.get("tirage", []), "vitesse": DB.get("tirage_vitesse", 3)})

@app.route("/api/verifier-bingo", methods=["POST"])
def verifier_bingo_auto():
    """Vérifie automatiquement si un ticket est gagnant"""
    global DB
    DB = load_data()
    d = request.json
    ticket_id = d.get("ticket_id", "")
    
    # Récupérer le ticket
    ticket = next((t for t in DB["tickets"] if t["id"] == ticket_id), None)
    if not ticket:
        return jsonify({"ok": False, "msg": "Ticket introuvable"}), 404
    
    # Récupérer les boules tirées
    boules_tirees = DB.get("tirage", [])
    
    # Récupérer les numéros cochés par le joueur
    coches = d.get("coches", [])
    
    if not coches:
        return jsonify({"ok": True, "valide": False, "msg": "Aucun numéro coché", "details": []})
    
    # Vérifier chaque numéro coché
    details = []
    tous_valides = True
    for num in coches:
        est_sorti = int(num) in boules_tirees
        details.append({"numero": num, "sorti": est_sorti})
        if not est_sorti:
            tous_valides = False
    
    return jsonify({
        "ok": True,
        "valide": tous_valides,
        "coches": len(coches),
        "valides": sum(1 for d in details if d["sorti"]),
        "details": details,
        "boules_tirees": len(boules_tirees)
    })

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

@app.route("/api/vente/confirmer-paiement", methods=["POST"])
def confirmer_paiement():
    global DB
    DB = load_data()
    d = request.json
    vente_id = d.get("vente_id", "")
    preuve = d.get("preuve", "")
    
    for v in DB["ventes"]:
        if v["id"] == vente_id:
            v["paiement_statut"] = "en_attente_validation"
            v["preuve_paiement"] = preuve
            v["date_paiement"] = datetime.datetime.now().isoformat()
            break
    save_data()
    
    # Notifier l'admin
    if SENDGRID_API_KEY:
        try:
            vente = next((v for v in DB["ventes"] if v["id"] == vente_id), None)
            if vente:
                html = f"""
                <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
                  <h2 style='color:#f59e0b'>💳 Confirmation de paiement reçue</h2>
                  <p>Client : <strong>{vente['client']}</strong></p>
                  <p>Jeu : {vente['jeu']} — Série {vente['serie']}</p>
                  <p>Montant : {vente['total']:,} XPF</p>
                  <p>Preuve : {preuve}</p>
                  <p style='color:#f59e0b'>→ Connectez-vous sur l'application pour valider.</p>
                </div>"""
                message = Mail(from_email=(FROM_EMAIL, FROM_NAME), to_emails=FROM_EMAIL,
                              subject=f"💳 Paiement reçu — {vente['client']}", html_content=html)
                SendGridAPIClient(SENDGRID_API_KEY).send(message)
        except Exception as e:
            print(f"[PAIEMENT ERR] {e}")
    
    return jsonify({"ok": True})

@app.route("/api/vente/valider-paiement", methods=["POST"])
def valider_paiement():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    vente_id = request.json.get("vente_id", "")
    for v in DB["ventes"]:
        if v["id"] == vente_id:
            v["paiement_statut"] = "valide"
            break
    save_data()
    return jsonify({"ok": True})

# === SYSTEME DE PIONS ===
PIONS_TARIFS = [
    {"pions": 1, "prix": 20, "label": "1 pion"},
    {"pions": 2, "prix": 50, "label": "2 pions"},
    {"pions": 4, "prix": 100, "label": "4 pions"},
    {"pions": 8, "prix": 200, "label": "8 pions"},
]

@app.route("/api/pions/tarifs")
def get_pions_tarifs():
    return jsonify(PIONS_TARIFS)

@app.route("/api/pions/solde/<code_joueur>")
def get_pions_solde(code_joueur):
    global DB
    DB = load_data()
    pions = DB.get("pions", {})
    return jsonify({"solde": pions.get(code_joueur.upper(), 0)})

@app.route("/api/pions/crediter", methods=["POST"])
def crediter_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    code_joueur = d.get("code_joueur", "").upper()
    nb_pions = int(d.get("pions", 0))
    prix = int(d.get("prix", 0))
    
    if "pions" not in DB:
        DB["pions"] = {}
    if "transactions_pions" not in DB:
        DB["transactions_pions"] = []
    
    # Prendre 5% commission
    commission = round(prix * 0.05)
    
    DB["pions"][code_joueur] = DB["pions"].get(code_joueur, 0) + nb_pions
    DB["transactions_pions"].append({
        "id": gen_code(6),
        "code_joueur": code_joueur,
        "pions": nb_pions,
        "prix": prix,
        "commission": commission,
        "code_org": s["code"],
        "date": datetime.datetime.now().isoformat()
    })
    save_data()
    return jsonify({"ok": True, "solde": DB["pions"][code_joueur], "commission": commission})

@app.route("/api/pions/utiliser", methods=["POST"])
def utiliser_pions():
    global DB
    DB = load_data()
    d = request.json
    code_joueur = d.get("code_joueur", "").upper()
    nb_pions = int(d.get("pions", 0))
    
    if "pions" not in DB:
        DB["pions"] = {}
    
    solde = DB["pions"].get(code_joueur, 0)
    if solde < nb_pions:
        return jsonify({"ok": False, "msg": f"Solde insuffisant ({solde} pions)"}), 400
    
    DB["pions"][code_joueur] = solde - nb_pions
    save_data()
    return jsonify({"ok": True, "solde": DB["pions"][code_joueur]})

# === CAGNOTTE 13% ===
@app.route("/api/cagnotte/calculer", methods=["POST"])
def calculer_cagnotte():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    d = request.json
    total_mises = float(d.get("total_mises", 0))
    
    # Calcul cagnotte — 80% joueur, 20% organisateur
    cagnotte_annoncee = round(total_mises * 0.80)  # 80% pour le gagnant
    part_org = round(total_mises * 0.20)            # 20% pour l'organisateur
    
    # Sauvegarder la cagnotte du tournoi
    if "cagnottes" not in DB:
        DB["cagnottes"] = []
    
    cagnotte = {
        "id": gen_code(6),
        "code_org": s["code"],
        "total_mises": total_mises,
        "cagnotte_annoncee": cagnotte_annoncee,
        "part_org": part_org,
        "date": datetime.datetime.now().isoformat()
    }
    DB["cagnottes"].append(cagnotte)
    save_data()
    
    return jsonify({
        "ok": True,
        "total_mises": total_mises,
        "cagnotte_annoncee": cagnotte_annoncee,
        "part_org": part_org
    })

@app.route("/api/demande-acces", methods=["POST"])
def demande_acces():
    d = request.json
    nom = d.get("nom", "")
    email = d.get("email", "")
    tel = d.get("tel", "")
    formule = d.get("formule", "")
    
    formules = {
        "1mois": "1 mois — 9 990 XPF",
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

# === SIGNALING WEBRTC POUR MICRO ===
@app.route("/api/micro/signal", methods=["POST"])
def micro_signal():
    global DB
    DB = load_data()
    d = request.json
    if "signals" not in DB:
        DB["signals"] = []
    signal = {
        "id": gen_code(8),
        "type": d.get("type"),
        "data": d.get("data"),
        "from": d.get("from", "org"),
        "date": datetime.datetime.now().isoformat()
    }
    DB["signals"].append(signal)
    # Garder seulement les 50 derniers signals
    DB["signals"] = DB["signals"][-50:]
    save_data()
    return jsonify({"ok": True, "signal": signal})

@app.route("/api/micro/signals")
def get_signals():
    global DB
    DB = load_data()
    after = request.args.get("after", "")
    signals = DB.get("signals", [])
    if after:
        signals = [s for s in signals if s["id"] > after]
    return jsonify(signals)

# === PIONS JOUEUR DIRECT ===
# === ANNONCES JEUX ===
@app.route("/api/annonce/jeu", methods=["POST", "DELETE"])
def gerer_annonce_jeu():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    
    if "annonces_jeux" not in DB:
        DB["annonces_jeux"] = []
    
    if request.method == "DELETE":
        code_org = request.json.get("code_org", "")
        DB["annonces_jeux"] = [a for a in DB["annonces_jeux"] if a.get("code_org") != code_org]
        save_data()
        return jsonify({"ok": True})
    
    d = request.json
    # Supprimer l'ancienne annonce de cet organisateur
    DB["annonces_jeux"] = [a for a in DB["annonces_jeux"] if a.get("code_org") != s["code"]]
    
    annonce = {
        "id": secrets.token_hex(4).upper(),
        "code_org": s["code"],
        "nom_org": s.get("nom", s["code"]),
        "jeu": d.get("jeu", ""),
        "prix": int(d.get("prix", 0)),
        "desc": d.get("desc", ""),
        "date": datetime.datetime.now().isoformat()
    }
    DB["annonces_jeux"].insert(0, annonce)
    save_data()
    return jsonify({"ok": True})

@app.route("/api/annonce/jeux")
def get_annonces_jeux():
    global DB
    DB = load_data()
    return jsonify(DB.get("annonces_jeux", []))

@app.route("/api/commande/ticket-pions", methods=["POST"])
def commander_ticket_pions():
    global DB
    DB = load_data()
    d = request.json
    code_joueur = d.get("code_joueur", "").upper()
    jeu = d.get("jeu", "")
    prix = int(d.get("prix", 0))
    nb_tickets = int(d.get("nb_tickets", 1))
    total = int(d.get("total", 0))
    code_org = d.get("code_org", "")
    
    # Vérifier solde pions du joueur
    pions_joueur = DB.get("pions_joueurs", {}).get(code_joueur, {})
    
    # Trouver les pions disponibles (priorité aux pions de plus grande valeur)
    solde_total = 0
    for valeur, nb in pions_joueur.items():
        solde_total += int(valeur) * nb
    
    if solde_total < total:
        return jsonify({"ok": False, "msg": f"Solde insuffisant — vous avez {solde_total} XPF de pions, il faut {total} XPF"}), 400
    
    # Débiter les pions (priorité aux pions de plus petite valeur)
    reste = total
    for valeur in ["20", "50", "100"]:
        nb_dispo = pions_joueur.get(valeur, 0)
        if nb_dispo > 0 and reste > 0:
            val_int = int(valeur)
            nb_utilise = min(nb_dispo, reste // val_int)
            if nb_utilise > 0:
                pions_joueur[valeur] = nb_dispo - nb_utilise
                reste -= nb_utilise * val_int
    
    if reste > 0:
        return jsonify({"ok": False, "msg": "Solde insuffisant en pions"}), 400
    
    DB["pions_joueurs"][code_joueur] = pions_joueur
    
    # Créditer les pions à l'organisateur
    if "pions_org" not in DB:
        DB["pions_org"] = {}
    if code_org not in DB["pions_org"]:
        DB["pions_org"][code_org] = {}
    
    # Enregistrer la commande ticket
    if "commandes_tickets_pions" not in DB:
        DB["commandes_tickets_pions"] = []
    
    commande = {
        "id": secrets.token_hex(4).upper(),
        "code_joueur": code_joueur,
        "code_org": code_org,
        "jeu": jeu,
        "prix": prix,
        "nb_tickets": nb_tickets,
        "total_pions": total,
        "statut": "en_attente",
        "date": datetime.datetime.now().isoformat()
    }
    DB["commandes_tickets_pions"].insert(0, commande)
    save_data()
    return jsonify({"ok": True, "commande_id": commande["id"]})

@app.route("/api/commande/tickets-pions-org")
def get_commandes_tickets_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify([])
    commandes = DB.get("commandes_tickets_pions", [])
    return jsonify([c for c in commandes if c.get("code_org") == s["code"]])

@app.route("/api/commande/ticket-pions/valider", methods=["POST"])
def valider_ticket_pions():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    commande_id = request.json.get("commande_id", "")
    for c in DB.get("commandes_tickets_pions", []):
        if c["id"] == commande_id:
            c["statut"] = "validee"
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/api/pions/commande-joueur", methods=["POST"])
def commande_pions_joueur():
    global DB
    DB = load_data()
    d = request.json
    code_joueur = d.get("code_joueur", "").upper()
    valeur_pion = int(d.get("valeur_pion", 0))
    montant_paye = float(d.get("montant_paye", 0))
    commission = float(d.get("commission", 0))
    nb_pions = int(d.get("nb_pions", 0))
    mode_paiement = d.get("mode_paiement", "")
    ref_paiement = d.get("ref_paiement", "")
    
    if not code_joueur or not valeur_pion or montant_paye < 500:
        return jsonify({"ok": False, "msg": "Données invalides"}), 400
    
    if "commandes_pions_joueurs" not in DB:
        DB["commandes_pions_joueurs"] = []
    
    commande = {
        "id": secrets.token_hex(4).upper(),
        "code_joueur": code_joueur,
        "valeur_pion": valeur_pion,
        "montant_paye": montant_paye,
        "commission": commission,
        "nb_pions": nb_pions,
        "mode_paiement": mode_paiement,
        "ref_paiement": ref_paiement,
        "statut": "en_attente_validation",
        "date": datetime.datetime.now().isoformat()
    }
    DB["commandes_pions_joueurs"].insert(0, commande)
    save_data()
    return jsonify({"ok": True, "commande_id": commande["id"]})

@app.route("/api/pions/solde-joueur/<code_joueur>")
def solde_pions_joueur(code_joueur):
    global DB
    DB = load_data()
    pions = DB.get("pions_joueurs", {}).get(code_joueur.upper(), {})
    return jsonify({
        "pions_20": pions.get("20", 0),
        "pions_50": pions.get("50", 0),
        "pions_100": pions.get("100", 0)
    })

@app.route("/api/pions/valider-joueur", methods=["POST"])
def valider_pions_joueur():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    
    commande_id = request.json.get("commande_id", "")
    for c in DB.get("commandes_pions_joueurs", []):
        if c["id"] == commande_id:
            c["statut"] = "validee"
            code_joueur = c["code_joueur"]
            valeur = str(c["valeur_pion"])
            nb = c["nb_pions"]
            if "pions_joueurs" not in DB:
                DB["pions_joueurs"] = {}
            if code_joueur not in DB["pions_joueurs"]:
                DB["pions_joueurs"][code_joueur] = {}
            DB["pions_joueurs"][code_joueur][valeur] = DB["pions_joueurs"][code_joueur].get(valeur, 0) + nb
            break
    save_data()
    return jsonify({"ok": True})

@app.route("/api/pions/recrediter-joueur", methods=["POST"])
def recrediter_pions_joueur():
    """ADMIN — Recredite directement des pions a un joueur (recuperation apres incident)"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    code_joueur = d.get("code_joueur", "").upper().strip()
    valeur = str(int(d.get("valeur_pion", 0)))
    nb = int(d.get("nb_pions", 0))
    if not code_joueur or valeur not in ["20", "50", "100"] or nb == 0:
        return jsonify({"ok": False, "msg": "Données invalides"}), 400
    if "pions_joueurs" not in DB:
        DB["pions_joueurs"] = {}
    if code_joueur not in DB["pions_joueurs"]:
        DB["pions_joueurs"][code_joueur] = {}
    DB["pions_joueurs"][code_joueur][valeur] = max(0, DB["pions_joueurs"][code_joueur].get(valeur, 0) + nb)
    save_data()
    return jsonify({"ok": True, "solde": DB["pions_joueurs"][code_joueur]})

@app.route("/api/pions/commandes-joueurs")
def get_commandes_joueurs():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify([])
    return jsonify(DB.get("commandes_pions_joueurs", []))

# === WEBSOCKET MICRO ===
# Connectés WebSocket : {code_org: [ws_connections]}
ws_micro_org = {}  # organisateur -> list of ws
ws_micro_joueurs = {}  # liste des joueurs connectés

if HAS_WEBSOCKET:
    @sock.route("/ws/micro/org/<code_org>")
    def ws_organisateur(ws, code_org):
        """WebSocket organisateur — envoie l'audio"""
        if code_org not in ws_micro_org:
            ws_micro_org[code_org] = []
        try:
            while True:
                data = ws.receive()
                if data is None:
                    break
                # Diffuser à tous les joueurs connectés sur ce code_org
                joueurs = ws_micro_joueurs.get(code_org, [])
                deconnectes = []
                for j_ws in joueurs:
                    try:
                        j_ws.send(data)
                    except:
                        deconnectes.append(j_ws)
                for d in deconnectes:
                    joueurs.remove(d)
        except:
            pass

    @sock.route("/ws/micro/joueur/<code_org>")
    def ws_joueur(ws, code_org):
        """WebSocket joueur — reçoit l'audio"""
        if code_org not in ws_micro_joueurs:
            ws_micro_joueurs[code_org] = []
        ws_micro_joueurs[code_org].append(ws)
        try:
            while True:
                # Garder la connexion ouverte
                # None = simple timeout d'attente, PAS une deconnexion -> on continue
                # (une vraie deconnexion leve une exception, geree par le except)
                data = ws.receive(timeout=25)
                if data is None:
                    continue
        except:
            pass
        finally:
            if ws in ws_micro_joueurs.get(code_org, []):
                ws_micro_joueurs[code_org].remove(ws)

@app.route("/api/micro/audio", methods=["POST"])
def recevoir_audio():
    global DB
    try:
        d = request.json
        audio_b64 = d.get("audio", "")
        code_org = d.get("code_org", "")
        if audio_b64:
            DB["micro_audio"] = {
                "audio": audio_b64,
                "code_org": code_org,
                "timestamp": datetime.datetime.now().isoformat()
            }
            save_data()
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

@app.route("/api/micro/audio/get")
def get_audio():
    global DB
    DB = load_data()
    return jsonify(DB.get("micro_audio", {}))

@app.route("/api/micro/status", methods=["POST"])
def micro_status():
    global DB
    DB = load_data()
    d = request.json
    DB["micro_actif"] = d.get("actif", False)
    DB["micro_message"] = d.get("message", "")
    save_data()
    return jsonify({"ok": True})

@app.route("/api/micro/status")
def get_micro_status():
    global DB
    DB = load_data()
    return jsonify({
        "actif": DB.get("micro_actif", False),
        "message": DB.get("micro_message", "")
    })

# === GENERATION TICKETS TRIPLE ACTION 75 ===
@app.route("/api/admin/generer-ta75", methods=["POST"])
def generer_ta75():
    """Génère un PDF de tickets TRIPLE ACTION 75 et le retourne en téléchargement"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    d = request.json or {}
    nb_tickets = min(int(d.get("nb_tickets", 500)), 1000)
    serie_start = int(d.get("serie_start", 1))
    
    output_path = f"/data/TA75_{serie_start:05d}_to_{serie_start + nb_tickets - 1:05d}.pdf"
    os.makedirs("/data", exist_ok=True)
    
    try:
        generate_ta75_pdf(
            nb_tickets=nb_tickets,
            serie_start=serie_start,
            output_path=output_path
        )
        save_commande("TRIPLE ACTION 75", nb_tickets, serie_start, output_path, d.get("client",""))
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"TRIPLE_ACTION_75_{serie_start:05d}.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        print(f"[TA75 ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/admin/generer-ta75/status", methods=["GET"])
def generer_ta75_status():
    """Vérifie que la génération TA75 est disponible"""
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    return jsonify({"ok": True, "disponible": True})

# === HISTORIQUE COMMANDES ===
def save_commande(jeu, nb_tickets, serie_start, output_path, client=""):
    global DB
    if "commandes" not in DB:
        DB["commandes"] = []
    DB["commandes"].insert(0, {
        "id": gen_code(8),
        "jeu": jeu,
        "nb_tickets": nb_tickets,
        "serie_start": serie_start,
        "serie_end": serie_start + nb_tickets - 1,
        "pdf_path": output_path,
        "client": client,
        "date": datetime.datetime.now().isoformat()
    })
    # Garder max 200 commandes
    DB["commandes"] = DB["commandes"][:200]
    save_data()

@app.route("/api/admin/commandes")
def get_commandes_admin():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    return jsonify(DB.get("commandes", []))

@app.route("/api/admin/commande/telecharger/<commande_id>")
def telecharger_commande(commande_id):
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    commande = next((c for c in DB.get("commandes", []) if c["id"] == commande_id), None)
    if not commande:
        return jsonify({"ok": False, "msg": "Commande introuvable"}), 404
    pdf_path = commande["pdf_path"]
    if not os.path.exists(pdf_path):
        return jsonify({"ok": False, "msg": "Fichier introuvable sur le serveur"}), 404
    nom_fichier = f"{commande['jeu'].replace(' ','_')}_{commande['serie_start']:05d}.pdf"
    return send_file(pdf_path, as_attachment=True, download_name=nom_fichier, mimetype="application/pdf")

# === GENERATION 60 BOULES ===
@app.route("/api/admin/generer-60-boules", methods=["POST"])
def generer_60_boules():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json or {}
    nb_tickets = min(int(d.get("nb_tickets", 500)), 1000)
    serie_start = int(d.get("serie_start", 1))
    output_path = f"/data/60B_{serie_start:05d}.pdf"
    os.makedirs("/data", exist_ok=True)
    try:
        generate_60b_pdf(nb_tickets=nb_tickets, serie_start=serie_start, output_path=output_path)
        save_commande("60 BOULES", nb_tickets, serie_start, output_path, d.get("client",""))
        return send_file(output_path, as_attachment=True, download_name=f"60_BOULES_{serie_start:05d}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# === GENERATION 40 BOULES ===
@app.route("/api/admin/generer-40-boules", methods=["POST"])
def generer_40_boules():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json or {}
    nb_tickets = min(int(d.get("nb_tickets", 500)), 1000)
    serie_start = int(d.get("serie_start", 1))
    output_path = f"/data/40B_{serie_start:05d}.pdf"
    os.makedirs("/data", exist_ok=True)
    try:
        generate_40b_pdf(nb_tickets=nb_tickets, serie_start=serie_start, output_path=output_path)
        save_commande("40 BOULES", nb_tickets, serie_start, output_path, d.get("client",""))
        return send_file(output_path, as_attachment=True, download_name=f"40_BOULES_{serie_start:05d}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# === GENERATION 4 COINS ===
@app.route("/api/admin/generer-4-coins", methods=["POST"])
def generer_4_coins():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json or {}
    nb_tickets = min(int(d.get("nb_tickets", 500)), 1000)
    serie_start = int(d.get("serie_start", 1))
    output_path = f"/data/4COINS_{serie_start:05d}.pdf"
    os.makedirs("/data", exist_ok=True)
    try:
        generate_4coins_pdf(nb_tickets=nb_tickets, serie_start=serie_start, output_path=output_path)
        save_commande("4 COINS", nb_tickets, serie_start, output_path, d.get("client",""))
        return send_file(output_path, as_attachment=True, download_name=f"4_COINS_{serie_start:05d}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# === GENERATION 500 FRANCS ===
@app.route("/api/admin/generer-500-francs", methods=["POST"])
def generer_500_francs():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json or {}
    nb_tickets = min(int(d.get("nb_tickets", 500)), 1000)
    serie_start = int(d.get("serie_start", 1))
    output_path = f"/data/500F_{serie_start:05d}.pdf"
    os.makedirs("/data", exist_ok=True)
    try:
        generate_500f_pdf(nb_tickets=nb_tickets, serie_start=serie_start, output_path=output_path)
        save_commande("500 FRANCS", nb_tickets, serie_start, output_path, d.get("client",""))
        return send_file(output_path, as_attachment=True, download_name=f"500_FRANCS_{serie_start:05d}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# === GENERATION 1 DOLLAR ===
@app.route("/api/admin/generer-1-dollar", methods=["POST"])
def generer_1_dollar():
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json or {}
    nb_tickets = min(int(d.get("nb_tickets", 500)), 1000)
    serie_start = int(d.get("serie_start", 1))
    output_path = f"/data/1DOLLAR_{serie_start:05d}.pdf"
    os.makedirs("/data", exist_ok=True)
    try:
        generate_1dollar_pdf(nb_tickets=nb_tickets, serie_start=serie_start, output_path=output_path)
        save_commande("1 DOLLAR", nb_tickets, serie_start, output_path, d.get("client",""))
        return send_file(output_path, as_attachment=True, download_name=f"1_DOLLAR_{serie_start:05d}.pdf", mimetype="application/pdf")
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# === STRIPE PAIEMENT ===
@app.route("/api/paiement/creer-session", methods=["POST"])
def creer_session_paiement():
    """Crée une session de paiement Stripe pour abonnement ou achat"""
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Paiement en ligne non configuré"}), 503
    
    d = request.json
    type_paiement = d.get("type", "abonnement")  # abonnement, tickets, pions
    montant = int(d.get("montant", 0))  # en XPF
    description = d.get("description", "Ticket Bingo")
    code_org = d.get("code_org", "")
    
    if montant <= 0:
        return jsonify({"ok": False, "msg": "Montant invalide"}), 400
    
    try:
        # Stripe utilise les centimes — XPF = 1 XPF = 1 centime (pas de décimale)
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "xpf",
                    "product_data": {
                        "name": description,
                        "description": f"Ticket Bingo — {description}"
                    },
                    "unit_amount": montant,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"https://ticket-bingo-production.up.railway.app?paiement=success&session_id={{CHECKOUT_SESSION_ID}}&code={code_org}",
            cancel_url=f"https://ticket-bingo-production.up.railway.app?paiement=cancel&code={code_org}",
            metadata={
                "type": type_paiement,
                "code_org": code_org,
                "description": description
            }
        )
        return jsonify({"ok": True, "url": session.url, "session_id": session.id})
    except Exception as e:
        print(f"[STRIPE ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/pions/stripe-checkout", methods=["POST"])
def stripe_checkout_pions():
    """Cree une session de paiement Stripe pour un achat de pions (joueur ou organisateur)"""
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Paiement par carte non configuré — choisissez un autre mode"}), 503
    global DB
    DB = load_data()
    d = request.json
    profil = d.get("profil", "joueur")  # joueur ou organisateur
    valeur_pion = int(d.get("valeur_pion", 0))
    montant = int(d.get("montant", 0))

    if profil == "organisateur":
        token = request.headers.get("X-Token", "")
        s = verif_session(token)
        if not s:
            return jsonify({"ok": False, "msg": "Session expirée"}), 403
        code = s["code"]
    else:
        code = d.get("code", "").upper().strip()

    if not code or valeur_pion not in [20, 50, 100] or montant < 500:
        return jsonify({"ok": False, "msg": "Données invalides"}), 400

    # Calcul COTE SERVEUR (anti-triche) : commission 20%, pions sur la valeur restante
    commission = round(montant * 0.20)
    nb_pions = int((montant - commission) // valeur_pion)
    if nb_pions <= 0:
        return jsonify({"ok": False, "msg": "Montant trop faible pour cette valeur de pion"}), 400

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "xpf",
                    "product_data": {
                        "name": f"{nb_pions} pions à {valeur_pion} XPF",
                        "description": f"Ticket Bingo — Pions ({code})"
                    },
                    "unit_amount": montant,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url="https://ticket-bingo-production.up.railway.app?paiement=pions_ok",
            cancel_url="https://ticket-bingo-production.up.railway.app?paiement=pions_annule",
            metadata={
                "type": "pions_joueur" if profil == "joueur" else "pions_org",
                "code": code,
                "valeur_pion": str(valeur_pion),
                "nb_pions": str(nb_pions),
                "commission": str(commission)
            }
        )
        return jsonify({"ok": True, "url": session.url})
    except Exception as e:
        print(f"[STRIPE PIONS ERR] {e}")
        return jsonify({"ok": False, "msg": "Erreur de paiement — choisissez un autre mode"}), 500

@app.route("/api/paiement/webhook", methods=["POST"])
def stripe_webhook():
    """Reçoit les notifications Stripe après paiement"""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        return jsonify({"ok": False}), 400
    
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        type_p = metadata.get("type", "")
        code_org = metadata.get("code_org", "")
        montant = session.get("amount_total", 0)
        
        global DB
        DB = load_data()
        
        if "paiements_stripe" not in DB:
            DB["paiements_stripe"] = []
        
        paiement_data = {
            "id": session["id"],
            "type": type_p,
            "code_org": code_org,
            "montant": montant,
            "description": metadata.get("description", ""),
            "date": datetime.datetime.now().isoformat(),
            "statut": "paye"
        }
        
        # Si c'est un paiement de grille, ajouter les détails
        if type_p == "grille":
            paiement_data.update({
                "nb_grilles": metadata.get("nb_grilles", "1"),
                "jeu": metadata.get("jeu", ""),
                "acheteur": metadata.get("acheteur", ""),
                "tournoi_id": metadata.get("tournoi_id", ""),
                "part_ticket_bingo": int(metadata.get("part_ticket_bingo", 0)),
                "part_cagnotte": int(metadata.get("part_cagnotte", 0)),
                "part_org": int(metadata.get("part_org", 0)),
                "total": int(metadata.get("total", 0))
            })
        
        DB["paiements_stripe"].append(paiement_data)
        
        # Si c'est un abonnement, activer le code organisateur
        if type_p == "abonnement" and code_org:
            if code_org in DB["codes"]:
                DB["codes"][code_org]["paiement_stripe"] = True
                DB["codes"][code_org]["date_paiement"] = datetime.datetime.now().isoformat()
        
        # Si c'est un achat de pions, créditer automatiquement
        if type_p == "pions" and code_org:
            nb_pions = int(metadata.get("nb_pions", 0))
            if nb_pions > 0:
                if "pions" not in DB:
                    DB["pions"] = {}
                DB["pions"][code_org] = DB["pions"].get(code_org, 0) + nb_pions
                if "transactions_pions" not in DB:
                    DB["transactions_pions"] = []
                DB["transactions_pions"].append({
                    "id": gen_code(6),
                    "code_org": code_org,
                    "pions": nb_pions,
                    "prix": montant,
                    "mode": "stripe",
                    "date": datetime.datetime.now().isoformat()
                })
                print(f"[STRIPE] {nb_pions} pions crédités à {code_org}")
        
        # Pions JOUEUR payes par carte : crediter automatiquement
        if type_p == "pions_joueur":
            code_joueur = metadata.get("code", "")
            valeur = metadata.get("valeur_pion", "0")
            nb_pions = int(metadata.get("nb_pions", 0))
            if code_joueur and nb_pions > 0:
                if "pions_joueurs" not in DB:
                    DB["pions_joueurs"] = {}
                if code_joueur not in DB["pions_joueurs"]:
                    DB["pions_joueurs"][code_joueur] = {}
                DB["pions_joueurs"][code_joueur][valeur] = DB["pions_joueurs"][code_joueur].get(valeur, 0) + nb_pions
                if "commandes_pions_joueurs" not in DB:
                    DB["commandes_pions_joueurs"] = []
                DB["commandes_pions_joueurs"].insert(0, {
                    "id": secrets.token_hex(4).upper(),
                    "code_joueur": code_joueur,
                    "valeur_pion": int(valeur),
                    "montant_paye": montant,
                    "commission": int(metadata.get("commission", 0)),
                    "nb_pions": nb_pions,
                    "mode_paiement": "Carte (Stripe)",
                    "ref_paiement": session["id"][:24],
                    "statut": "validee",
                    "date": datetime.datetime.now().isoformat()
                })
                print(f"[STRIPE] {nb_pions} pions credites au joueur {code_joueur}")

        # Pions ORGANISATEUR payes par carte : crediter automatiquement
        if type_p == "pions_org":
            code_o = metadata.get("code", "")
            valeur = metadata.get("valeur_pion", "0")
            nb_pions = int(metadata.get("nb_pions", 0))
            if code_o and nb_pions > 0:
                if "pions_org" not in DB:
                    DB["pions_org"] = {}
                if code_o not in DB["pions_org"]:
                    DB["pions_org"][code_o] = {}
                DB["pions_org"][code_o][valeur] = DB["pions_org"][code_o].get(valeur, 0) + nb_pions
                if "commandes_pions" not in DB:
                    DB["commandes_pions"] = []
                DB["commandes_pions"].insert(0, {
                    "id": secrets.token_hex(4).upper(),
                    "code_org": code_o,
                    "nom_org": code_o,
                    "valeur_pion": int(valeur),
                    "montant_paye": montant,
                    "commission": int(metadata.get("commission", 0)),
                    "nb_pions": nb_pions,
                    "mode_paiement": "Carte (Stripe)",
                    "ref_paiement": session["id"][:24],
                    "statut": "validee",
                    "date": datetime.datetime.now().isoformat()
                })
                print(f"[STRIPE] {nb_pions} pions credites a l'organisateur {code_o}")

        # Si c'est un achat PDF, enregistrer la commande
        if type_p == "pdf" and code_org:
            nb_tickets = int(metadata.get("nb_tickets", 0))
            jeu = metadata.get("jeu", "")
            if "commandes_pdf_stripe" not in DB:
                DB["commandes_pdf_stripe"] = []
            DB["commandes_pdf_stripe"].append({
                "id": gen_code(8),
                "code_org": code_org,
                "jeu": jeu,
                "nb_tickets": nb_tickets,
                "prix": montant,
                "statut": "paye_en_attente_generation",
                "date": datetime.datetime.now().isoformat()
            })
            print(f"[STRIPE] Commande PDF {jeu} {nb_tickets} tickets pour {code_org}")
        
        save_data()
        print(f"[STRIPE] Paiement reçu: {type_p} — {montant} XPF — {code_org}")
    
    return jsonify({"ok": True})

@app.route("/api/paiement/historique")
def get_paiements_stripe():
    """Historique des paiements Stripe pour l'Admin"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    return jsonify(DB.get("paiements_stripe", []))

@app.route("/api/paiement/abonnement", methods=["POST"])
def payer_abonnement():
    """Crée un lien de paiement pour abonnement organisateur"""
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Paiement en ligne non configuré"}), 503
    d = request.json
    code_org = d.get("code_org", "")
    montant = int(d.get("montant", 9990))
    
    # Définir le nom selon le montant
    if montant == 4990:
        nom = "Offre de lancement — 1er mois Ticket Bingo"
        desc = "Engagement 1 an — À partir du 2ème mois : 9 990 XPF/mois"
    else:
        nom = "Abonnement mensuel Ticket Bingo"
        desc = "Accès organisateur — Toutes fonctionnalités incluses"
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "xpf",
                    "product_data": {
                        "name": nom,
                        "description": desc
                    },
                    "unit_amount": montant,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"https://ticket-bingo-production.up.railway.app?paiement=success&code={code_org}",
            cancel_url=f"https://ticket-bingo-production.up.railway.app?paiement=cancel",
            metadata={"type": "abonnement", "code_org": code_org, "montant": str(montant)}
        )
        return jsonify({"ok": True, "url": session.url})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

# === PAIEMENT PIONS VIA STRIPE ===
@app.route("/api/paiement/pions", methods=["POST"])
def payer_pions():
    """Crée une session Stripe pour achat de pions par l'organisateur"""
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Paiement en ligne non configuré"}), 503
    
    d = request.json
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    nb_pions = int(d.get("nb_pions", 0))
    prix = int(d.get("prix", 0))
    code_org = s["code"]
    
    if nb_pions <= 0 or prix <= 0:
        return jsonify({"ok": False, "msg": "Montant invalide"}), 400
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "xpf",
                    "product_data": {
                        "name": f"{nb_pions} pions Ticket Bingo",
                        "description": f"Pack de {nb_pions} pions pour vos tournois"
                    },
                    "unit_amount": prix,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"https://ticket-bingo-production.up.railway.app?paiement=pions_ok&code={code_org}&nb={nb_pions}",
            cancel_url=f"https://ticket-bingo-production.up.railway.app?paiement=cancel",
            metadata={
                "type": "pions",
                "code_org": code_org,
                "nb_pions": str(nb_pions),
                "prix": str(prix)
            }
        )
        return jsonify({"ok": True, "url": session.url, "session_id": session.id})
    except Exception as e:
        print(f"[STRIPE PIONS ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

# === PAIEMENT PDF VIA STRIPE ===
@app.route("/api/paiement/pdf", methods=["POST"])
def payer_pdf():
    """Crée une session Stripe pour achat de tickets PDF"""
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Paiement en ligne non configuré"}), 503
    
    d = request.json
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    
    nb_tickets = int(d.get("nb_tickets", 0))
    prix = int(d.get("prix", 0))
    jeu = d.get("jeu", "Tickets Bingo")
    code_org = s["code"]
    
    if nb_tickets <= 0 or prix <= 0:
        return jsonify({"ok": False, "msg": "Montant invalide"}), 400
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "xpf",
                    "product_data": {
                        "name": f"{nb_tickets} tickets {jeu}",
                        "description": f"Pack de {nb_tickets} tickets — {jeu}"
                    },
                    "unit_amount": prix,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"https://ticket-bingo-production.up.railway.app?paiement=pdf_ok&code={code_org}",
            cancel_url=f"https://ticket-bingo-production.up.railway.app?paiement=cancel",
            metadata={
                "type": "pdf",
                "code_org": code_org,
                "nb_tickets": str(nb_tickets),
                "jeu": jeu,
                "prix": str(prix)
            }
        )
        return jsonify({"ok": True, "url": session.url, "session_id": session.id})
    except Exception as e:
        print(f"[STRIPE PDF ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

# === PAIEMENT GRILLES JOUEURS ===
@app.route("/api/paiement/grille", methods=["POST"])
def payer_grille():
    """Crée une session Stripe pour achat de grilles"""
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Paiement en ligne non configuré"}), 503
    
    d = request.json
    nb_grilles = int(d.get("nb_grilles", 1))
    prix_grille = int(d.get("prix_grille", 100))  # en XPF
    jeu = d.get("jeu", "Bingo")
    code_org = d.get("code_org", "")
    acheteur = d.get("acheteur", "Joueur")
    tournoi_id = d.get("tournoi_id", "")
    
    total = nb_grilles * prix_grille
    
    # Calculer les parts
    part_ticket_bingo = round(total * 0.02)  # 2% pour toi
    part_cagnotte = round(total * 0.11)       # 11% cagnotte
    part_org = total - part_ticket_bingo - part_cagnotte  # reste à l'organisateur
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "xpf",
                    "product_data": {
                        "name": f"{nb_grilles} grille(s) — {jeu}",
                        "description": f"Tournoi Ticket Bingo — {jeu}"
                    },
                    "unit_amount": total,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"https://ticket-bingo-production.up.railway.app?paiement=grille_ok&tournoi={tournoi_id}&acheteur={acheteur}",
            cancel_url=f"https://ticket-bingo-production.up.railway.app?paiement=cancel",
            metadata={
                "type": "grille",
                "nb_grilles": str(nb_grilles),
                "prix_grille": str(prix_grille),
                "jeu": jeu,
                "code_org": code_org,
                "acheteur": acheteur,
                "tournoi_id": tournoi_id,
                "part_ticket_bingo": str(part_ticket_bingo),
                "part_cagnotte": str(part_cagnotte),
                "part_org": str(part_org),
                "total": str(total)
            }
        )
        return jsonify({
            "ok": True,
            "url": session.url,
            "session_id": session.id,
            "total": total,
            "part_ticket_bingo": part_ticket_bingo,
            "part_cagnotte": part_cagnotte,
            "part_org": part_org
        })
    except Exception as e:
        print(f"[STRIPE GRILLE ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/paiement/cagnotte/<tournoi_id>")
def get_cagnotte_stripe(tournoi_id):
    """Récupère la cagnotte accumulée via Stripe pour un tournoi"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    
    paiements = DB.get("paiements_stripe", [])
    paiements_tournoi = [p for p in paiements if p.get("tournoi_id") == tournoi_id]
    
    total_mises = sum(int(p.get("total", 0)) for p in paiements_tournoi)
    cagnotte = sum(int(p.get("part_cagnotte", 0)) for p in paiements_tournoi)
    commission_tb = sum(int(p.get("part_ticket_bingo", 0)) for p in paiements_tournoi)
    nb_joueurs = len(paiements_tournoi)
    
    return jsonify({
        "ok": True,
        "tournoi_id": tournoi_id,
        "nb_joueurs": nb_joueurs,
        "total_mises": total_mises,
        "cagnotte_11": cagnotte,
        "commission_ticket_bingo_2": commission_tb,
        "paiements": paiements_tournoi
    })

@app.route("/api/paiement/calculer-gain-final", methods=["POST"])
def calculer_gain_final():
    """Calcule le gain final après prélèvement de tous les frais Ticket Bingo"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    
    d = request.json
    cagnotte = float(d.get("cagnotte", 0))
    nb_revendeurs = int(d.get("nb_revendeurs", 0))
    
    if cagnotte <= 0:
        return jsonify({"ok": False, "msg": "Montant invalide"}), 400
    
    # TOUS LES PRÉLÈVEMENTS SUR LE GAIN FINAL (sans frais revendeurs)
    prel_cagnotte_2 = round(cagnotte * 0.02)        # 2% cagnotte invisible
    prel_commissions_5 = round(cagnotte * 0.05)     # 5% commissions jeux
    prel_pions_1 = round(cagnotte * 0.01)           # 1% pions
    prel_tournoi = 500                               # Frais fixes tournoi
    
    total_preleve = prel_cagnotte_2 + prel_commissions_5 + prel_pions_1 + prel_tournoi
    gain_gagnant = round(cagnotte - total_preleve)
    
    # Sauvegarder dans DB
    if "gains_finaux" not in DB:
        DB["gains_finaux"] = []
    
    gain_data = {
        "id": gen_code(8),
        "cagnotte": cagnotte,
        "prel_cagnotte_2": prel_cagnotte_2,
        "prel_commissions_5": prel_commissions_5,
        "prel_pions_1": prel_pions_1,
        "prel_tournoi": prel_tournoi,
        "total_preleve": total_preleve,
        "gain_gagnant": gain_gagnant,
        "code_org": s["code"],
        "date": datetime.datetime.now().isoformat()
    }
    DB["gains_finaux"].insert(0, gain_data)
    save_data()
    
    return jsonify({
        "ok": True,
        "cagnotte": cagnotte,
        "prel_cagnotte_2": prel_cagnotte_2,
        "prel_commissions_5": prel_commissions_5,
        "prel_pions_1": prel_pions_1,
        "prel_tournoi": prel_tournoi,
        "total_preleve": total_preleve,
        "gain_gagnant": gain_gagnant
    })

@app.route("/api/paiement/virement-gagnant", methods=["POST"])
def virement_gagnant():
    """Enregistre le virement au gagnant"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    
    d = request.json
    if "virements_gagnants" not in DB:
        DB["virements_gagnants"] = []
    
    DB["virements_gagnants"].append({
        "id": gen_code(8),
        "tournoi_id": d.get("tournoi_id", ""),
        "gagnant": d.get("gagnant", ""),
        "montant": d.get("montant", 0),
        "mode": d.get("mode", ""),
        "date": datetime.datetime.now().isoformat(),
        "valide_par": s["code"]
    })
    save_data()
    return jsonify({"ok": True})

@app.route("/api/paiement/gains-finaux")
def get_gains_finaux():
    """Historique des gains finaux pour l'Admin"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    return jsonify(DB.get("gains_finaux", []))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
