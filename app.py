import hashlib, datetime, os, secrets, string, json, urllib.request, urllib.parse
from flask import Flask, request, jsonify, send_from_directory, Response
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__, static_folder=".")

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "directionvaikeashop@gmail.com")
FROM_NAME = "Ticket Bingo"
CLOUDINARY_CLOUD = os.environ.get("CLOUDINARY_CLOUD", "dz556b0ee")
CLOUDINARY_PRESET = "alerte_upload"

# Fichier de persistance
DATA_FILE = "/tmp/ticketbingo_data.json"

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                # S'assurer que toutes les clés existent
                if "tickets_acheteurs" not in data:
                    data["tickets_acheteurs"] = {}
                if "acces_docs" not in data:
                    data["acces_docs"] = {}
                return data
    except:
        pass
    return {
        "ventes": [], "tickets": [],
        "jeux": ["P6", "OHANA 75", "QUINES 90", "OHANA 75 4 SERIE"],
        "tournois": [],
        "codes": {"ADMIN2024": {"duree": 36500, "nom": "Administrateur", "actif": True, "admin": True}},
        "sessions": {},
        "acces_docs": {},
        "tickets_acheteurs": {}
    }

def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(DB, f, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"[SAVE ERR] {e}")

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
    save_data()
    return jsonify({"ok": True, "token": token, "nom": info["nom"], "admin": info.get("admin", False)})

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
    token = request.headers.get("X-Token","")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403
    d = request.json
    tournoi = {
        "id": gen_code(6),
        "nom": d.get("nom",""),
        "jeu": d.get("jeu",""),
        "date_tournoi": d.get("date_tournoi",""),
        "created": datetime.datetime.now().isoformat()
    }
    DB["tournois"].insert(0, tournoi)
    save_data()
    return jsonify({"ok": True, "tournoi": tournoi})

@app.route("/api/tournois")
def get_tournois():
    return jsonify(DB["tournois"])

@app.route("/api/vente", methods=["POST"])
def nouvelle_vente():
    d = request.json
    if not d.get("client") or not d.get("jeu") or not d.get("serie"):
        return jsonify({"ok": False, "msg": "Champs manquants"}), 400
    total = int(d.get("qty", 1)) * int(d.get("prix", 0))
    token_doc = secrets.token_hex(16)
    tournoi_id = d.get("tournoi_id","")
    date_expiration = None
    tournoi = next((t for t in DB["tournois"] if t["id"] == tournoi_id), None)
    if tournoi and tournoi.get("date_tournoi"):
        date_expiration = tournoi["date_tournoi"]
    vente = {
        "id": hashlib.md5(f"{d['client']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "client": d["client"], "email": d.get("email",""), "jeu": d["jeu"],
        "pack": int(d.get("pack", 25)), "qty": int(d.get("qty", 1)),
        "total_feuilles": int(d.get("qty", 1)) * int(d.get("pack", 25)),
        "serie": d["serie"], "prix": int(d.get("prix", 0)), "total": total,
        "photo_url": d.get("photo_url", None),
        "pdf_url": d.get("pdf_url", None),
        "token_doc": token_doc,
        "tournoi_id": tournoi_id,
        "date_expiration": date_expiration,
        "date": datetime.datetime.now().isoformat()
    }
    DB["ventes"].insert(0, vente)
    DB["acces_docs"][token_doc] = {
        "vente_id": vente["id"], "client": vente["client"],
        "jeu": vente["jeu"], "date_expiration": date_expiration, "acces_count": 0
    }
    save_data()
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
    if not d.get("acheteur") or not d.get("jeu") or not d.get("serie"):
        return jsonify({"ok": False, "msg": "Champs manquants"}), 400
    
    # Générer un code unique pour l'acheteur
    code_acheteur = gen_code(6)
    
    ticket = {
        "id": hashlib.md5(f"{d['acheteur']}{d['serie']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "acheteur": d["acheteur"],
        "email_acheteur": d.get("email_acheteur",""),
        "jeu": d["jeu"], "serie": d["serie"],
        "prix": int(d.get("prix", 0)),
        "photo_url": d.get("photo_url", None),
        "pdf_url": d.get("pdf_url", None),
        "code_acheteur": code_acheteur,
        "date": datetime.datetime.now().isoformat()
    }
    DB["tickets"].insert(0, ticket)
    
    # Enregistrer le code acheteur
    DB["tickets_acheteurs"][code_acheteur] = ticket["id"]
    save_data()
    
    return jsonify({"ok": True, "ticket": ticket, "code_acheteur": code_acheteur})

@app.route("/api/tickets")
def get_tickets():
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
    DB["codes"][code] = {"duree": duree, "nom": nom, "actif": True,
        "created": datetime.datetime.now().isoformat(),
        "expire": (datetime.datetime.now() + datetime.timedelta(days=duree)).isoformat()}
    save_data()
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
    save_data()
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

@app.route("/api/pdf-proxy")
def pdf_proxy():
    url = request.args.get("url","")
    if not url:
        return jsonify({"ok": False}), 400
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        return Response(data, content_type="application/pdf", headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": "inline"
        })
    except Exception as e:
        print(f"[PDF PROXY ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500
