import hashlib, datetime, os, secrets, string
import urllib.request, urllib.parse, json
from flask import Flask, request, jsonify, send_from_directory
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__, static_folder=".")

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "directionvaikeashop@gmail.com")
FROM_NAME = "Ticket Bingo"
CLOUDINARY_CLOUD = os.environ.get("CLOUDINARY_CLOUD", "dz556b0ee")
CLOUDINARY_PRESET = "alerte_upload"

DB = {
    "ventes": [], "tickets": [],
    "jeux": ["Bingo Classique", "Bingo Or", "Bingo Tropical", "Super Jackpot"],
    "codes": {"ADMIN2024": {"duree": 36500, "nom": "Administrateur", "actif": True, "admin": True}},
    "sessions": {}
}

def gen_code(n=8):
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))

def verif_session(token):
    s = DB["sessions"].get(token)
    if not s: return None
    if datetime.datetime.now() > datetime.datetime.fromisoformat(s["expire"]):
        del DB["sessions"][token]
        return None
    return s

def envoyer_email(dest_email, dest_nom, sujet, contenu_html):
    try:
        message = Mail(
            from_email=(FROM_EMAIL, FROM_NAME),
            to_emails=dest_email,
            subject=sujet,
            html_content=contenu_html
        )
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        return True
    except Exception as e:
        print(f"[EMAIL ERR] {e}")
        return False

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/login", methods=["POST"])
def login():
    code = request.json.get("code", "").strip().upper()
    info = DB["codes"].get(code)
    if not info or not info["actif"]:
        return jsonify({"ok": False, "msg": "Code invalide ou expiré"}), 401
    expire = datetime.datetime.now() + datetime.timedelta(hours=12)
    token = secrets.token_hex(16)
    DB["sessions"][token] = {"code": code, "nom": info["nom"], "expire": expire.isoformat(), "admin": info.get("admin", False)}
    return jsonify({"ok": True, "token": token, "nom": info["nom"], "admin": info.get("admin", False)})

@app.route("/api/jeux")
def get_jeux():
    return jsonify(DB["jeux"])

@app.route("/api/jeux", methods=["POST"])
def add_jeu():
    nom = request.json.get("nom", "").strip()
    if nom and nom not in DB["jeux"]:
        DB["jeux"].append(nom)
    return jsonify(DB["jeux"])

@app.route("/api/vente", methods=["POST"])
def nouvelle_vente():
    d = request.json
    if not d.get("client") or not d.get("jeu") or not d.get("serie"):
        return jsonify({"ok": False, "msg": "Champs manquants"}), 400
    total = int(d.get("qty", 1)) * int(d.get("prix", 0))
    vente = {
        "id": hashlib.md5(f"{d['client']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "client": d["client"], "email": d.get("email",""), "jeu": d["jeu"],
        "pack": int(d.get("pack", 25)), "qty": int(d.get("qty", 1)),
        "total_feuilles": int(d.get("qty", 1)) * int(d.get("pack", 25)),
        "serie": d["serie"], "prix": int(d.get("prix", 0)), "total": total,
        "photo_url": d.get("photo_url", None),
        "pdf_url": d.get("pdf_url", None),
        "date": datetime.datetime.now().isoformat()
    }
    DB["ventes"].insert(0, vente)
    return jsonify({"ok": True, "vente": vente})

@app.route("/api/ventes")
def get_ventes():
    return jsonify(DB["ventes"])

@app.route("/api/vente/<vente_id>/document")
def get_document(vente_id):
    vente = next((v for v in DB["ventes"] if v["id"] == vente_id), None)
    if not vente:
        return jsonify({"ok": False, "msg": "Vente introuvable"}), 404
    return jsonify({
        "ok": True,
        "client": vente["client"],
        "jeu": vente["jeu"],
        "serie": vente["serie"],
        "pack": vente["pack"],
        "qty": vente["qty"],
        "photo_url": vente.get("photo_url"),
        "pdf_url": vente.get("pdf_url")
    })

@app.route("/api/stats")
def get_stats():
    today = datetime.date.today().isoformat()
    vj = [v for v in DB["ventes"] if v["date"][:10] == today]
    return jsonify({
        "ventes_jour": len(vj),
        "tickets_jour": sum(v["total_feuilles"] for v in vj),
        "total_jour": sum(v["total"] for v in vj)
    })

@app.route("/api/ticket", methods=["POST"])
def enregistrer_ticket():
    d = request.json
    if not d.get("acheteur") or not d.get("jeu") or not d.get("serie"):
        return jsonify({"ok": False, "msg": "Champs manquants"}), 400
    ticket = {
        "id": hashlib.md5(f"{d['acheteur']}{d['serie']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "acheteur": d["acheteur"], "jeu": d["jeu"], "serie": d["serie"],
        "prix": int(d.get("prix", 0)), "date": datetime.datetime.now().isoformat()
    }
    DB["tickets"].insert(0, ticket)
    return jsonify({"ok": True, "ticket": ticket})

@app.route("/api/tickets")
def get_tickets():
    return jsonify(DB["tickets"])

@app.route("/api/verifier", methods=["POST"])
def verifier():
    d = request.json
    jeu = d.get("jeu", "")
    serie = d.get("serie", "").strip()
    trouve = next((t for t in DB["tickets"] if t["jeu"] == jeu and t["serie"].lower() == serie.lower()), None)
    return jsonify({"gagnant": bool(trouve), "ticket": trouve})

@app.route("/api/admin/generer", methods=["POST"])
def admin_generer():
    token = request.headers.get("X-Token","")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    nom = d.get("nom","Client").strip()
    duree = int(d.get("duree", 30))
    code = gen_code()
    while code in DB["codes"]:
        code = gen_code()
    DB["codes"][code] = {
        "duree": duree, "nom": nom, "actif": True,
        "created": datetime.datetime.now().isoformat(),
        "expire": (datetime.datetime.now() + datetime.timedelta(days=duree)).isoformat()
    }
    return jsonify({"ok": True, "code": code, "nom": nom, "duree": duree})

@app.route("/api/admin/codes")
def admin_codes():
    token = request.headers.get("X-Token","")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    codes = [{"code": c, **info} for c, info in DB["codes"].items() if c != "ADMIN2024"]
    return jsonify(codes)

@app.route("/api/admin/desactiver", methods=["POST"])
def admin_desactiver():
    token = request.headers.get("X-Token","")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    code = request.json.get("code","").strip().upper()
    if code in DB["codes"]:
        DB["codes"][code]["actif"] = False
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
