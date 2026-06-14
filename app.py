import hashlib, datetime, os, secrets, string, json, base64
import urllib.request, urllib.parse
from flask import Flask, request, jsonify, send_from_directory, Response, send_file, g, make_response
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

# ============================================================
# REGISTRE CENTRAL DES GENERATEURS DE JEUX
# Pour installer un NOUVEAU jeu : 1) ajouter le fichier generate_xxx.py au depot
# 2) ajouter UNE ligne ci-dessous. Le jeu apparait AUTOMATIQUEMENT dans toutes
# les listes (boutique, vente de tickets, annonces) cote admin et organisateur.
# ============================================================
GENERATEURS_JEUX = {}

def _enregistrer_jeu(nom, emoji, module_nom):
    """Enregistre un jeu si son module generateur est present (tolerant aux absents)"""
    try:
        import importlib
        mod = importlib.import_module(module_nom)
        GENERATEURS_JEUX[nom] = {"emoji": emoji, "generer": mod.generate_pdf}
        print(f"[JEU INSTALLE] {emoji} {nom}")
    except Exception as e:
        print(f"[JEU ABSENT] {nom} ({module_nom}) : {e}")

_enregistrer_jeu("TRIPLE ACTION 75", "🎯", "generate_triple_action_75")
_enregistrer_jeu("60 BOULES", "🎱", "generate_60_boules")
_enregistrer_jeu("40 BOULES", "🎳", "generate_40_boules")
_enregistrer_jeu("4 COINS", "🪙", "generate_4_coins")
_enregistrer_jeu("500 FRANCS", "💵", "generate_500_francs")
_enregistrer_jeu("1 DOLLAR", "💰", "generate_1_dollar")
_enregistrer_jeu("OHANA 75 10 BOULES", "🌺", "generate_ohana_75")
_enregistrer_jeu("OHANA 75 8 BOULES", "🌸", "generate_ohana_75_8b")
_enregistrer_jeu("OHANA 75 ORIGINAL", "🏵️", "generate_ohana_75_original")
_enregistrer_jeu("P6", "6️⃣", "generate_p6")
# --- Ajouter les futurs jeux ici, une ligne chacun : ---
# _enregistrer_jeu("OHANA 90", "🌺", "generate_ohana_90")
# _enregistrer_jeu("QUINES 90", "🎲", "generate_quines_90")
# _enregistrer_jeu("RUBIS 90", "💎", "generate_rubis_90")
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__, static_folder=".")
if HAS_WEBSOCKET:
    sock = Sock(app)

@app.before_request
def _verrouiller_ecritures():
    if request.method == "POST":
        _VERROU_ECRITURES.acquire()
        g.verrou_ecriture_pris = True

@app.teardown_request
def _liberer_ecritures(exc=None):
    if getattr(g, "verrou_ecriture_pris", False):
        g.verrou_ecriture_pris = False
        try:
            _VERROU_ECRITURES.release()
        except RuntimeError:
            pass

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "directionvaikeashop@gmail.com")
FROM_NAME = "Ticket Bingo"
CLOUDINARY_CLOUD = os.environ.get("CLOUDINARY_CLOUD", "dz556b0ee")
CLOUDINARY_PRESET = "alerte_upload"

# Stockage persistant
DATA_FILE = "/data/ticketbingo_data.json"

import threading
_VERROU_SAUVEGARDE = threading.Lock()

# Les operations d'ECRITURE (POST) passent une par une pour ne plus jamais
# qu'une operation ecrase ce qu'une autre vient d'enregistrer (perte de pions, etc.)
# Les lectures (GET, actualisation des boules...) restent paralleles et rapides.
_VERROU_ECRITURES = threading.Lock()

def load_data():
    # Essayer le fichier principal, puis la copie de secours (.bak)
    for chemin in [DATA_FILE, DATA_FILE + ".bak"]:
        try:
            if os.path.exists(chemin):
                with open(chemin, "r") as f:
                    data = json.load(f)
                if chemin.endswith(".bak"):
                    print("[LOAD] Fichier principal illisible — copie de secours utilisée")
                # AUTO-REPARATION : recreer toute case manquante (listes et dictionnaires)
                cles_listes = ["alertes_bingo", "tirage", "tournois", "ventes", "tickets",
                               "commandes_pions", "commandes_pions_joueurs", "commandes_tickets",
                               "commandes_tickets_pions", "annonces_jeux", "paiements_stripe"]
                cles_dicts = ["tickets_acheteurs", "acces_docs", "sessions", "pions_joueurs",
                              "pions_org", "coches", "parrainages"]
                for k in cles_listes:
                    if k not in data or not isinstance(data[k], list):
                        data[k] = data.get(k) if isinstance(data.get(k), list) else []
                for k in cles_dicts:
                    if k not in data or not isinstance(data[k], dict):
                        data[k] = data.get(k) if isinstance(data.get(k), dict) else {}
                if "codes" not in data or not isinstance(data["codes"], dict):
                    data["codes"] = {}
                if "ADMIN2024" not in data["codes"]:
                    data["codes"]["ADMIN2024"] = {"duree": 36500, "nom": "Administrateur", "actif": True, "admin": True}
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

# Icônes intégrées (base64) — servies directement pour le Play Store
ICONE_192_B64 = "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"
ICONE_512_B64 = "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"

@app.route("/manifest.json")
def manifest():
    """Manifest leger : icones servies separement via URL absolue"""
    import json as _json
    base = "https://ticket-bingo-production.up.railway.app"
    data = {
        "name": "Ticket Bingo",
        "short_name": "Ticket Bingo",
        "description": "Le bingo en ligne de Polynesie : tournois en direct, joue avec ta communaute.",
        "start_url": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#08090d",
        "theme_color": "#08090d",
        "lang": "fr",
        "icons": [
            {"src": base + "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": base + "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": base + "/icone-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": base + "/icone-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ]
    }
    return Response(_json.dumps(data), mimetype="application/manifest+json")

@app.route("/icone-192.png")
def icone_192():
    import base64 as _b64
    return Response(_b64.b64decode(ICONE_192_B64), mimetype="image/png")

@app.route("/icone-512.png")
def icone_512():
    import base64 as _b64
    return Response(_b64.b64decode(ICONE_512_B64), mimetype="image/png")

@app.route("/sw.js")
def service_worker():
    """Service worker minimal — installable mais n'intercepte aucune connexion"""
    sw_code = """// Service Worker minimal — Ticket Bingo
// Ne met rien en cache, n'intercepte aucune requete : toujours la derniere version.
self.addEventListener('install', function(event) {
  self.skipWaiting();
});
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(noms) {
      return Promise.all(noms.map(function(nom) { return caches.delete(nom); }));
    }).then(function() {
      return self.clients.claim();
    })
  );
});
// Aucun gestionnaire 'fetch' : le navigateur charge tout normalement, sans blocage.
"""
    response = Response(sw_code, mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

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
    # Fusion automatique : jeux declares manuellement + jeux dont le generateur est installe
    fusion = list(DB["jeux"])
    for nom in GENERATEURS_JEUX:
        if nom not in fusion:
            fusion.append(nom)
    return jsonify(fusion)

@app.route("/api/jeux-generateurs")
def get_jeux_generateurs():
    """Liste des jeux dont le generateur est installe (pour la boutique a generation automatique)"""
    return jsonify([{"nom": nom, "emoji": infos["emoji"]} for nom, infos in GENERATEURS_JEUX.items()])

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
    # Inscription simple : seul le nom est obligatoire (le jeu/serie seront attribues
    # plus tard lors de l'annonce + validation de la commande en pions). Corrige 12/06/2026.
    if not d.get("acheteur"):
        return jsonify({"ok": False, "msg": "Le nom de la joueuse est obligatoire"}), 400
    # Code joueur EXISTANT fourni : la joueuse garde son code et ses pions.
    # Si un ticket existe deja sur ce code -> ON LE MET A JOUR (nouvelle vente = nouveau
    # jeu / nouvelles fiches sur le MEME code permanent). Corrige le 12/06/2026.
    code_demande = (d.get("code_acheteur") or "").upper().strip()
    if code_demande:
        if not (4 <= len(code_demande) <= 8) or not code_demande.isalnum():
            return jsonify({"ok": False, "msg": "Code joueur invalide (4 à 8 lettres/chiffres)"}), 400
        if code_demande in DB.get("codes_bloques", []):
            return jsonify({"ok": False, "msg": f"Le code {code_demande} est bloqué"}), 400
        deja = next((t for t in DB["tickets"] if t.get("code_acheteur", "").upper() == code_demande), None)
        if deja:
            # Securite : seul l'organisateur proprietaire (ou l'admin) peut re-vendre sur ce code
            if not (s and s.get("admin")) and deja.get("code_org") not in (code_org, "ADMIN"):
                return jsonify({"ok": False, "msg": f"Le code {code_demande} appartient à un autre organisateur"}), 403
            # MISE A JOUR du ticket existant avec la nouvelle vente
            deja["acheteur"] = d["acheteur"]
            deja["jeu"] = d["jeu"]
            deja["serie"] = d["serie"]
            deja["prix"] = int(d.get("prix", 0))
            if d.get("pdf_url"):
                deja["pdf_url"] = d["pdf_url"]
            if d.get("photo_url"):
                deja["photo_url"] = d["photo_url"]
            deja["page_debut"] = d.get("page_debut", deja.get("page_debut"))
            deja["page_fin"] = d.get("page_fin", deja.get("page_fin"))
            if d.get("email"):
                deja["email"] = d["email"]
            deja["code_org"] = code_org if deja.get("code_org") in (None, "", "ADMIN") else deja["code_org"]
            deja["date"] = datetime.datetime.now().isoformat()
            DB["tickets_acheteurs"][code_demande] = deja["id"]
            save_data()
            return jsonify({"ok": True, "ticket": deja, "code_acheteur": code_demande, "mis_a_jour": True})
        code_acheteur = code_demande
    else:
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
    if code in DB.get("codes_bloques", []):
        return jsonify({"ok": False, "msg": "Ce code a été désactivé. Contactez votre organisateur."}), 403
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
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TICKET BINGO — Système de monétisation

IMPORTANT — DEUX CIRCUITS DISTINCTS :

1️⃣ PIONS : AUTOMATIQUE ✅
   - Client achète des pions → Reçoit immédiatement (code fait tout)
   - Paiement Stripe/CCP/Deblock → Pions crédités auto
   - Frais de service 5% déduits et affichés (0% en espèces)
   - Le client reçoit la valeur nette correspondante (rien n'est créé de rien)
   - C'est 100% automatisé

2️⃣ TICKETS : MANUEL (base historique) 📋
   - Org commande des tickets pré-imprimés
   - Admin/Maeva valide MANUELLEMENT
   - Frais de service 5% déduits et affichés (0% en espèces)
   - Le montant net correspond à ce qui est livré
   - C'est du travail MANUEL (validation requise)

NE PAS MÉLANGER : PIONS ≠ TICKETS
"""



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
    
    # 3. NE PLUS JAMAIS EFFACER LES TICKETS (corrige 12/06/2026)
    # Les codes joueurs sont PERMANENTS : le ticket porte le code de connexion de la
    # joueuse et ses pions y sont attaches. Pour le tournoi suivant, l'organisateur
    # REASSIGNE simplement jeu/pages/PDF via "Mes joueurs" — il n'efface rien.
    
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
    d = request.json
    commande_id = d.get("commande_id", "")
    commande = None
    for c in DB.get("commandes_tickets_pions", []):
        if c["id"] == commande_id:
            c["statut"] = "validee"
            commande = c
            break
    if not commande:
        save_data()
        return jsonify({"ok": False, "msg": "Commande introuvable"}), 404

    # === ATTRIBUTION DU TICKET A LA JOUEUSE (circuit restaure 12/06/2026) ===
    # En validant, l'organisateur attribue les fiches : la joueuse voit son ticket immediatement.
    code_joueur = (commande.get("code_joueur") or "").upper().strip()
    page_debut = d.get("page_debut")
    page_fin = d.get("page_fin")
    pdf_url = d.get("pdf_url", "")
    serie = (d.get("serie") or "").strip()
    ticket = next((t for t in DB.get("tickets", []) if (t.get("code_acheteur") or "").upper() == code_joueur), None)
    if ticket is None:
        # Code permanent sans ticket (ex: victime d'un ancien reset) -> on le recree
        ticket = {
            "id": hashlib.md5(f"{code_joueur}{datetime.datetime.now()}".encode()).hexdigest()[:8],
            "acheteur": "Joueuse " + code_joueur,
            "jeu": "", "serie": "-", "prix": 0,
            "photo_url": None, "pdf_url": None,
            "page_debut": None, "page_fin": None,
            "code_acheteur": code_joueur, "email": "",
            "code_org": commande.get("code_org") or (s["code"] if not s.get("admin") else "ADMIN"),
            "date": datetime.datetime.now().isoformat()
        }
        DB["tickets"].insert(0, ticket)
        DB.setdefault("tickets_acheteurs", {})[code_joueur] = ticket["id"]
    # Mettre a jour avec la nouvelle vente
    ticket["jeu"] = commande.get("jeu") or ticket.get("jeu", "")
    if serie:
        ticket["serie"] = serie
    try:
        if page_debut not in (None, ""):
            ticket["page_debut"] = int(page_debut)
        if page_fin not in (None, ""):
            ticket["page_fin"] = int(page_fin)
    except Exception:
        pass
    if pdf_url:
        ticket["pdf_url"] = pdf_url
    ticket["date"] = datetime.datetime.now().isoformat()
    save_data()
    return jsonify({"ok": True, "ticket": ticket})

@app.route("/api/pions/commande-joueur", methods=["POST"])
def commande_pions_joueur():
    global DB
    DB = load_data()
    d = request.json
    if (d.get("code_joueur") or "").upper().strip() in DB.get("codes_bloques", []):
        return jsonify({"ok": False, "msg": "Ce code a été désactivé"}), 403
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
    if code_joueur.upper().strip() in DB.get("codes_bloques", []):
        return jsonify({"pions_20": 0, "pions_50": 0, "pions_100": 0, "bloque": True})
    pions = DB.get("pions_joueurs", {}).get(code_joueur.upper(), {})
    return jsonify({
        "pions_20": pions.get("20", 0),
        "pions_50": pions.get("50", 0),
        "pions_100": pions.get("100", 0)
    })

@app.route("/api/pions/refuser-joueur", methods=["POST"])
def refuser_pions_joueur():
    """ADMIN — Refuser une commande de pions jamais payee (commande fantome)"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    commande_id = request.json.get("commande_id", "")
    for c in DB.get("commandes_pions_joueurs", []):
        if c["id"] == commande_id:
            c["statut"] = "refusee"
            c["date_refus"] = datetime.datetime.now().isoformat()
            save_data()
            return jsonify({"ok": True})
    return jsonify({"ok": False, "msg": "Commande introuvable"}), 404

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

@app.route("/api/maintenance")
def get_maintenance():
    """PUBLIC — Etat du mode maintenance"""
    global DB
    DB = load_data()
    m = DB.get("maintenance", {})
    return jsonify({"actif": bool(m.get("actif")), "message": m.get("message", "")})

@app.route("/api/admin/maintenance", methods=["POST"])
def set_maintenance():
    """ADMIN — Activer/desactiver le mode maintenance"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    DB["maintenance"] = {"actif": bool(d.get("actif")), "message": d.get("message", "")}
    save_data()
    return jsonify({"ok": True, "actif": DB["maintenance"]["actif"]})

@app.route("/api/admin/etat-donnees")
def etat_donnees():
    """ADMIN — Etat des lieux complet de la base de donnees"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    pions_j = DB.get("pions_joueurs", {})
    return jsonify({"ok": True, "etat": {
        "ventes": len(DB.get("ventes", [])),
        "tickets": len(DB.get("tickets", [])),
        "codes_joueurs": len(DB.get("tickets_acheteurs", {})),
        "codes_acces": len(DB.get("codes", {})),
        "tournois": len(DB.get("tournois", [])),
        "commandes_pions_joueurs": len(DB.get("commandes_pions_joueurs", [])),
        "commandes_pions_org": len(DB.get("commandes_pions", [])),
        "boules_tirage": len(DB.get("tirage", [])),
        "joueurs_avec_pions": {c: v for c, v in pions_j.items() if isinstance(v, dict) and any(v.values())}
    }})

@app.route("/api/admin/telecharger-donnees")
def telecharger_donnees():
    """ADMIN — Telecharge une sauvegarde complete de la base (fichier JSON)"""
    global DB
    DB = load_data()
    token = request.args.get("token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    contenu = json.dumps(DB, ensure_ascii=False, default=str, indent=2)
    horod = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    return Response(contenu, mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=sauvegarde_ticketbingo_{horod}.json"})

@app.route("/api/admin/restaurer-donnees", methods=["POST"])
def restaurer_donnees():
    """ADMIN — Restaure la base depuis un fichier de sauvegarde telecharge"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    try:
        donnees = request.json
        if not isinstance(donnees, dict) or "codes" not in donnees:
            return jsonify({"ok": False, "msg": "Fichier de sauvegarde invalide"}), 400
        DB = donnees
        save_data()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500

def _deduire_valeur_pion(montant, nb_pions, valeur_meta):
    """Deduit la valeur du pion : metadata si presente, sinon calcul depuis le montant"""
    if valeur_meta and str(valeur_meta) in ["20", "50", "100"]:
        return str(valeur_meta)
    if nb_pions > 0:
        approx = (montant * 0.98) / nb_pions  # commission carte 2%
        return str(min([20, 50, 100], key=lambda v: abs(v - approx)))
    return "100"

@app.route("/api/admin/stripe-paiements-pions")
def stripe_paiements_pions():
    """ADMIN — Liste les paiements de pions recus sur Stripe avec etat de rapprochement"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Stripe non configuré"}), 503
    try:
        deja_traites = set(DB.get("stripe_credites", []))
        # References deja enregistrees par le webhook (nouveau circuit)
        refs_webhook = set()
        for c in DB.get("commandes_pions_joueurs", []):
            if c.get("ref_paiement"):
                refs_webhook.add(str(c["ref_paiement"]))

        # Recuperer les sessions (compatible toutes versions de la librairie stripe)
        reponse = stripe.checkout.Session.list(limit=100)
        try:
            liste_sessions = list(reponse.auto_paging_iter())
        except Exception:
            liste_sessions = list(getattr(reponse, "data", []) or [])

        resultats = []
        for sess in liste_sessions:
            try:
                # Convertir en dictionnaire simple, quelle que soit la version
                if hasattr(sess, "to_dict_recursive"):
                    d_sess = sess.to_dict_recursive()
                elif hasattr(sess, "to_dict"):
                    d_sess = sess.to_dict()
                else:
                    d_sess = dict(sess)
                if d_sess.get("payment_status") != "paid":
                    continue
                meta = d_sess.get("metadata") or {}
                if not isinstance(meta, dict):
                    meta = dict(meta)
                type_p = meta.get("type", "")
                if type_p not in ["pions", "pions_joueur", "pions_org"]:
                    continue
                code = str(meta.get("code") or meta.get("code_org") or "").upper().strip()
                montant = int(d_sess.get("amount_total") or 0)
                nb_pions = int(meta.get("nb_pions") or 0)
                valeur = _deduire_valeur_pion(montant, nb_pions, meta.get("valeur_pion"))
                sid = str(d_sess.get("id", ""))
                traite = (sid in deja_traites) or (sid[:24] in refs_webhook)
                solde = DB.get("pions_joueurs", {}).get(code, {})
                try:
                    date_txt = datetime.datetime.fromtimestamp(int(d_sess.get("created", 0))).strftime("%d/%m %H:%M")
                except Exception:
                    date_txt = ""
                resultats.append({
                    "session_id": sid,
                    "date": date_txt,
                    "code": code,
                    "montant": montant,
                    "nb_pions": nb_pions,
                    "valeur_pion": valeur,
                    "type": type_p,
                    "deja_traite": traite,
                    "solde_actuel": solde if isinstance(solde, dict) else {}
                })
            except Exception as e_item:
                print(f"[STRIPE SYNC ITEM ERR] {type(e_item).__name__}: {e_item}")
                continue
            if len(resultats) >= 100:
                break
        return jsonify({"ok": True, "paiements": resultats})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "msg": f"{type(e).__name__}: {e}"}), 500

@app.route("/api/admin/stripe-crediter", methods=["POST"])
def stripe_crediter():
    """ADMIN — Credite un paiement Stripe verifie (idempotent : jamais deux fois)"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Stripe non configuré"}), 503
    session_id = request.json.get("session_id", "")
    if "stripe_credites" not in DB:
        DB["stripe_credites"] = []
    if session_id in DB["stripe_credites"]:
        return jsonify({"ok": False, "msg": "Ce paiement a déjà été crédité"}), 400
    try:
        sess = stripe.checkout.Session.retrieve(session_id)
        if hasattr(sess, "to_dict_recursive"):
            sess = sess.to_dict_recursive()
        elif hasattr(sess, "to_dict"):
            sess = sess.to_dict()
        else:
            sess = dict(sess)
        if sess.get("payment_status") != "paid":
            return jsonify({"ok": False, "msg": "Paiement non confirmé chez Stripe"}), 400
        meta = sess.get("metadata", {}) or {}
        code = (meta.get("code") or meta.get("code_org") or "").upper().strip()
        montant = sess.get("amount_total", 0)
        nb_pions = int(meta.get("nb_pions", 0) or 0)
        valeur = _deduire_valeur_pion(montant, nb_pions, meta.get("valeur_pion"))
        if not code or nb_pions <= 0:
            return jsonify({"ok": False, "msg": "Données du paiement incomplètes"}), 400
        if "pions_joueurs" not in DB:
            DB["pions_joueurs"] = {}
        if code not in DB["pions_joueurs"]:
            DB["pions_joueurs"][code] = {}
        # FRAIS DE SERVICE 5% — DÉDUITS ET AFFICHÉS AU CLIENT (rien n'est complété)
        # Le client paie le montant, 5% de frais de service sont déduits,
        # et il reçoit la valeur en pions qui correspond réellement à ce qu'il a payé net.
        frais_service = round(montant * 0.05)
        montant_net = montant - frais_service
        pions_credites = max(1, montant_net // valeur)

        # Le joueur reçoit exactement la valeur nette (aucun pion créé de rien)
        DB["pions_joueurs"][code][valeur] = DB["pions_joueurs"][code].get(valeur, 0) + pions_credites

        DB["stripe_credites"].append(session_id)
        if "commandes_pions_joueurs" not in DB:
            DB["commandes_pions_joueurs"] = []
        DB["commandes_pions_joueurs"].insert(0, {
            "id": secrets.token_hex(4).upper(),
            "code_joueur": code,
            "valeur_pion": int(valeur),
            "montant_paye": montant,
            "frais_service": frais_service,       # 5% de frais de service affichés
            "montant_net": montant_net,           # ce qui est réellement converti en pions
            "pions_credites": pions_credites,
            "mode_paiement": "Carte (Stripe) — rapprochement",
            "ref_paiement": session_id[:24],
            "statut": "validee",
            "date": datetime.datetime.now().isoformat()
        })
        save_data()
        return jsonify({"ok": True, "code": code, "nb_pions": nb_pions, "valeur": valeur, "solde": DB["pions_joueurs"][code]})
    except Exception as e:
        print(f"[STRIPE CREDIT ERR] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

@app.route("/api/message-admin")
def lire_message_admin():
    """Tous — Message d'information publie par l'administration"""
    global DB
    DB = load_data()
    msg = DB.get("message_admin", {})
    if not msg.get("actif"):
        return jsonify({"actif": False})
    return jsonify({"actif": True, "texte": msg.get("texte", ""), "date": msg.get("date", "")})

@app.route("/api/message-joueurs")
def lire_message_joueurs():
    """Tous — Message d'information aux joueuses"""
    global DB
    DB = load_data()
    msg = DB.get("message_joueurs", {})
    if not msg.get("actif"):
        return jsonify({"actif": False})
    return jsonify({"actif": True, "texte": msg.get("texte", ""), "date": msg.get("date", "")})

@app.route("/api/admin/message-joueurs", methods=["POST"])
def publier_message_joueurs():
    """ADMIN — Publier ou retirer le message aux joueuses"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    texte = (d.get("texte") or "").strip()
    if texte:
        DB["message_joueurs"] = {"actif": True, "texte": texte[:600],
                                 "date": datetime.datetime.now().strftime("%d/%m %H:%M")}
    else:
        DB["message_joueurs"] = {"actif": False}
    save_data()
    return jsonify({"ok": True, "actif": bool(texte)})

@app.route("/api/message-prive/<code>")
def lire_message_prive(code):
    """Message personnel destine a UN code precis (organisateur ou joueur)"""
    global DB
    DB = load_data()
    msg = DB.get("messages_prives", {}).get(code.upper().strip(), {})
    if not msg.get("actif"):
        return jsonify({"actif": False})
    return jsonify({"actif": True, "texte": msg.get("texte", ""), "date": msg.get("date", "")})

@app.route("/api/admin/message-prive", methods=["POST"])
def publier_message_prive():
    """ADMIN — Publier ou retirer un message prive pour un code donne"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    code = (d.get("code") or "").upper().strip()
    texte = (d.get("texte") or "").strip()
    if not code:
        return jsonify({"ok": False, "msg": "Code obligatoire"}), 400
    if "messages_prives" not in DB:
        DB["messages_prives"] = {}
    if texte:
        DB["messages_prives"][code] = {"actif": True, "texte": texte[:600],
                                       "date": datetime.datetime.now().strftime("%d/%m %H:%M")}
        msg = f"Message privé publié pour {code} — visible uniquement par ce code"
    else:
        DB["messages_prives"].pop(code, None)
        msg = f"Message privé de {code} retiré"
    save_data()
    return jsonify({"ok": True, "msg": msg})

@app.route("/api/admin/bloquer-code", methods=["POST"])
def bloquer_code_joueur():
    """ADMIN — Bloquer ou debloquer un code joueur (code compromis, litige...)"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    code = (d.get("code") or "").upper().strip()
    bloquer = bool(d.get("bloquer", True))
    if not code:
        return jsonify({"ok": False, "msg": "Code obligatoire"}), 400
    if "codes_bloques" not in DB:
        DB["codes_bloques"] = []
    if bloquer:
        if code not in DB["codes_bloques"]:
            DB["codes_bloques"].append(code)
        msg = f"Code {code} BLOQUÉ — connexion et pions inaccessibles"
    else:
        DB["codes_bloques"] = [c for c in DB["codes_bloques"] if c != code]
        msg = f"Code {code} débloqué"
    save_data()
    return jsonify({"ok": True, "msg": msg, "bloques": DB["codes_bloques"]})

@app.route("/api/admin/envoyer-code", methods=["POST"])
def envoyer_code_joueur():
    """ADMIN — Envoyer par email le code d'acces d'une joueuse (bienvenue + cadeau)"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    code = (d.get("code") or "").upper().strip()
    email = (d.get("email") or "").strip()
    nom = (d.get("nom") or "").strip()
    if not code or not email or "@" not in email:
        return jsonify({"ok": False, "msg": "Code et email valide obligatoires"}), 400
    # Verifier que le code existe (ticket actif)
    ticket = next((t for t in DB.get("tickets", []) if t.get("code_acheteur", "").upper() == code), None)
    if not ticket:
        return jsonify({"ok": False, "msg": f"Aucun ticket actif avec le code {code}"}), 404
    if not nom:
        nom = ticket.get("acheteur", "") or "joueuse"
    if not SENDGRID_API_KEY:
        return jsonify({"ok": False, "msg": "SendGrid non configuré"}), 500
    try:
        html = f"""
        <div style='font-family:sans-serif;max-width:520px;margin:0 auto;background:#08090d;color:#f0f2f8;padding:24px;border-radius:12px'>
          <div style='text-align:center;margin-bottom:24px'>
            <div style='font-size:48px'>🎱</div>
            <h1 style='font-size:24px;color:#34d399;margin:8px 0'>Ticket Bingo</h1>
          </div>
          <p>Ia ora na <strong>{nom}</strong> ! 🌺</p>
          <p>Voici votre code personnel — notez-le précieusement, il est à vous pour toujours :</p>
          <div style='background:#111218;border:2px solid #10b981;border-radius:12px;padding:24px;margin:20px 0;text-align:center'>
            <div style='font-size:12px;color:#6b7280;margin-bottom:8px'>VOTRE CODE PERSONNEL</div>
            <div style='font-family:monospace;font-size:40px;font-weight:800;letter-spacing:10px;color:#34d399'>{code}</div>
          </div>
          <div style='background:#0d2818;border:1px solid #10b981;border-radius:10px;padding:16px;margin:16px 0;text-align:center'>
            <p style='margin:0;font-size:15px'>🎁 <strong>2 000 XPF de pions vous ont été OFFERTS</strong></p>
            <p style='margin:4px 0 0 0;font-size:13px;color:#9ca3af'>Ils vous attendent déjà sur votre code, avec vos pions !</p>
          </div>
          <div style='text-align:center;margin:24px 0'>
            <a href='https://ticket-bingo-production.up.railway.app' style='padding:14px 32px;background:#10b981;color:#fff;text-decoration:none;border-radius:8px;font-size:15px;font-weight:600'>🎯 Jouer maintenant</a>
          </div>
          <p style='font-size:13px;text-align:center'><a href='https://ticket-bingo-production.up.railway.app/guide-joueur' style='color:#34d399'>📗 Le guide du joueur en 2 minutes</a></p>
          <p style='font-size:12px;color:#6b7280;text-align:center'>Entrez votre code dans la section 🎮 Espace Joueur — À très vite pour le prochain tournoi ! 🌺</p>
        </div>"""
        message = Mail(from_email=(FROM_EMAIL, FROM_NAME), to_emails=email,
                      subject=f"🎱 Votre code Ticket Bingo — {code} (+ 2 000 XPF offerts !)", html_content=html)
        SendGridAPIClient(SENDGRID_API_KEY).send(message)
        # Memoriser l'email sur le ticket pour les prochains envois
        ticket["email"] = email
        save_data()
        return jsonify({"ok": True, "msg": f"Email envoyé à {email}"})
    except Exception as e:
        print(f"[EMAIL CODE ERR] {e}")
        return jsonify({"ok": False, "msg": f"Erreur d'envoi : {e}"}), 500

@app.route("/api/admin/message", methods=["POST"])
def publier_message_admin():
    """ADMIN — Publier ou retirer le message d'information"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    texte = (d.get("texte") or "").strip()
    if texte:
        DB["message_admin"] = {"actif": True, "texte": texte[:600],
                               "date": datetime.datetime.now().strftime("%d/%m %H:%M")}
    else:
        DB["message_admin"] = {"actif": False}
    save_data()
    return jsonify({"ok": True, "actif": bool(texte)})

@app.route("/guide")
def guide_organisateur():
    """Page publique : guide de l'organisateur (partageable sur Facebook)"""
    return """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guide de l'Organisateur — Ticket Bingo</title>
<meta property="og:title" content="Ticket Bingo — Guide de l'Organisateur">
<meta property="og:description" content="Tout ce qu'il faut savoir pour gerer vos joueuses et animer vos tournois de bingo en Polynesie.">
<style>
:root{--bg:#0b0c12;--s:#111218;--s2:#1a1c26;--bd:rgba(255,255,255,.1);--ac:#6366f1;--ac2:#818cf8;--mu:rgba(255,255,255,.55)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:#fff;font-family:-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.7;padding:20px 16px 60px}
.wrap{max-width:680px;margin:0 auto}
h1{font-size:30px;text-align:center;margin:18px 0 2px}
.sub{font-size:17px;font-weight:700;color:var(--ac2);text-align:center;margin-bottom:4px}
.tag{font-size:13px;color:var(--mu);text-align:center;margin-bottom:18px}
.regle{background:rgba(220,38,38,.15);border:2px solid #dc2626;border-radius:14px;padding:14px;text-align:center;font-weight:800;color:#fca5a5;font-size:15px;margin-bottom:18px;line-height:1.5}
.card{background:var(--s);border:1px solid var(--bd);border-radius:14px;padding:16px;margin-bottom:14px}
h2{font-size:17px;color:var(--ac2);margin-bottom:8px}
p{font-size:14px;color:rgba(255,255,255,.85);margin-bottom:8px}
li{font-size:14px;color:rgba(255,255,255,.85);margin:6px 0 6px 18px}
b{color:#fff}
.astuce{background:rgba(251,191,36,.12);border-left:3px solid #fbbf24;border-radius:8px;padding:10px;font-size:13px;color:#fcd34d;font-style:italic;margin:8px 0}
.check{background:var(--s2);border-radius:10px;padding:10px 12px;margin:6px 0;font-size:14px;display:flex;gap:10px;align-items:center}
.num{background:var(--ac);color:#fff;font-weight:800;border-radius:8px;min-width:26px;height:26px;display:flex;align-items:center;justify-content:center;font-size:13px}
.pied{text-align:center;color:var(--mu);font-size:13px;margin-top:24px;font-style:italic}
.cta{display:block;text-align:center;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;text-decoration:none;font-weight:800;padding:13px;border-radius:12px;margin-top:18px;font-size:15px}
</style></head><body><div class="wrap">
<h1>🎱 TICKET BINGO</h1>
<div class="sub">Guide de l'Organisateur</div>
<div class="tag">Tout ce qu'il faut savoir pour gérer vos joueuses et animer vos tournois</div>

<div class="regle">⚠️ À RETENIR : LE SEUL LIEN ENTRE L'ADMINISTRATEUR ET VOS JOUEUSES, C'EST L'ACHAT DES PIONS.<br>Tout le reste — tickets, distribution, tournois, cagnotte — c'est VOUS, l'organisateur.</div>

<div class="card"><h2>1. 🏪 S'approvisionner — Acheter des tickets pour les revendre</h2>
<p>Avant vos tournois, achetez vos tickets depuis votre espace :</p>
<li><b>Commandez les tickets</b> (cartons pré-imprimés) : OHANA, TRIPLE ACTION, 1 DOLLAR, etc. Vous payez le prix du carton (ex: 2500 XPF).</li>
<li><b>Après validation de votre paiement</b>, les tickets apparaissent dans « Mes tickets reçus ».</li>
<li><b>Vous les vendez aux joueuses</b> au prix que vous décidez — c'est VOTRE MARGE ! 💰</li></div>

<div class="card"><h2>2. 🔑 Inscrire vos joueuses — leur code</h2>
<p>Pour chaque nouvelle joueuse : « <b>Inscrire une joueuse</b> » → son <b>nom</b> (et son email si vous voulez le lui envoyer) → <b>Générer le code</b>. Transmettez-lui ce code : c'est sa clé pour se connecter, acheter ses pions et recevoir ses tickets.</p>
<div class="astuce">⭐ RÈGLE D'OR : le code d'une joueuse est PERMANENT. Même code à vie, ses pions y restent attachés. Ne créez jamais deux codes pour la même personne.</div>
<p>Le tableau « <b>Mes joueurs</b> » liste ensuite toutes vos joueuses avec leur code et leur solde de pions en temps réel.</p></div>

<div class="card"><h2>3. 📢 Annoncer le jeu — les joueuses commandent et paient</h2>
<p>« Annoncer ce jeu » : jeu, prix du ticket, description (« Jackpot 50 000 XPF ! »). L'annonce s'affiche chez toutes vos joueuses.</p>
<p>Chaque joueuse choisit son <b>nombre de tickets</b> et <b>paie avec ses pions</b>. Vous validez sa commande, ses pions sont débités automatiquement. <b>La vente est faite.</b></p>
<p><b>Plus de pions ?</b> Elle recharge par <b>carte</b> dans l'application (instantané) ou par virement (en indiquant <b>son code</b> dans le libellé). Vous pouvez aussi lui en <b>donner</b> depuis votre stock.</p></div>

<div class="card"><h2>4. 🎫 Distribuer les tickets aux joueuses qui ont payé</h2>
<p>Dans « Mes joueurs » → bouton <b>« Assigner / Modifier »</b> :</p>
<li>1. Le <b>nom</b> de la joueuse</li>
<li>2. Le <b>jeu</b> et sa <b>série</b></li>
<li>3. Ses <b>pages</b> (début/fin) selon le nombre de tickets achetés</li>
<li>4. Le <b>PDF</b> choisi dans vos jeux reçus</li>
<li>5. <b>Enregistrer</b> — c'est tout !</li>
<p>La joueuse entre son code → elle voit SON ticket, et le pointage automatique coche SES numéros.</p>
<div class="astuce">💡 ASTUCE : tenez un registre des pages distribuées (Brenda 1-3, Vaiana 4-6...) pour ne jamais donner deux fois les mêmes feuilles.</div></div>

<div class="card"><h2>5. 🎙️ Animer le tournoi en direct</h2>
<li><b>Tirage des boules</b> : affichées et <b>annoncées vocalement</b> chez chaque joueuse</li>
<li><b>Micro en direct</b> : parlez en continu — ambiance, annonces en reo, encouragements</li>
<li><b>Pointage automatique</b> : les tickets se cochent tout seuls</li>
<li><b>Alertes BINGO</b> : l'alerte arrive avec le ticket de la joueuse — vous vérifiez et validez</li>
<div class="astuce">💡 Demandez aux joueuses de toucher leur écran en arrivant (débloque le son) et de garder l'application affichée.</div>
<p><b>La cagnotte</b> : 80 % des mises pour la gagnante (payée <b>EN PIONS</b>), 20 % pour vous, l'organisateur. La gagnante peut rejouer ses pions sur les prochains tournois.</p></div>

<div class="card"><h2>6. 🔄 Après le tournoi</h2>
<p>Rien d'obligatoire ! Repartez de l'étape 3 : annoncez, encaissez, redistribuez. Le « Reset tournoi » efface tirage et alertes si besoin — <b>les codes et les pions de vos joueuses ne sont jamais touchés</b>.</p></div>

<div class="card"><h2>✅ Check-list avant chaque tournoi</h2>
<div class="check"><span class="num">1</span>Mon jeu PDF est commandé et reçu</div>
<div class="check"><span class="num">2</span>Le jeu est annoncé avec le prix du ticket</div>
<div class="check"><span class="num">3</span>Les commandes des joueuses sont validées (payées en pions)</div>
<div class="check"><span class="num">4</span>Chaque joueuse payée a son ticket assigné (jeu + série + pages + PDF)</div>
<div class="check"><span class="num">5</span>Jour J : tirage lancé, micro activé... que le meilleur ticket gagne ! 🎉</div></div>

<a class="cta" href="https://ticket-bingo-production.up.railway.app">🎱 Ouvrir Ticket Bingo</a>
<div class="pied">Ticket Bingo — L'application des tournois de bingo en Polynésie 🌺<br>Support : 89 22 23 05</div>
</div></body></html>"""

@app.route("/guide-joueur")
def guide_joueur():
    """Page publique : guide de la joueuse (partageable sur Facebook)"""
    return """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Guide du Joueur — Ticket Bingo</title>
<meta property="og:title" content="Ticket Bingo — Guide du Joueur">
<meta property="og:description" content="Ton code, tes pions, tes tickets : comment jouer au bingo en direct sur Ticket Bingo.">
<style>
:root{--bg:#0b0c12;--s:#111218;--s2:#1a1c26;--bd:rgba(255,255,255,.1);--ac:#10b981;--ac2:#34d399;--mu:rgba(255,255,255,.55)}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:#fff;font-family:-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.7;padding:20px 16px 60px}
.wrap{max-width:680px;margin:0 auto}
h1{font-size:30px;text-align:center;margin:18px 0 2px}
.sub{font-size:17px;font-weight:700;color:var(--ac2);text-align:center;margin-bottom:4px}
.tag{font-size:13px;color:var(--mu);text-align:center;margin-bottom:18px}
.regle{background:rgba(220,38,38,.15);border:2px solid #dc2626;border-radius:14px;padding:14px;text-align:center;font-weight:800;color:#fca5a5;font-size:15px;margin-bottom:18px;line-height:1.5}
.card{background:var(--s);border:1px solid var(--bd);border-radius:14px;padding:16px;margin-bottom:14px}
h2{font-size:17px;color:var(--ac2);margin-bottom:8px}
p{font-size:14px;color:rgba(255,255,255,.85);margin-bottom:8px}
li{font-size:14px;color:rgba(255,255,255,.85);margin:6px 0 6px 18px}
b{color:#fff}
.astuce{background:rgba(251,191,36,.12);border-left:3px solid #fbbf24;border-radius:8px;padding:10px;font-size:13px;color:#fcd34d;font-style:italic;margin:8px 0}
.pied{text-align:center;color:var(--mu);font-size:13px;margin-top:24px;font-style:italic}
.cta{display:block;text-align:center;background:linear-gradient(135deg,#059669,#10b981);color:#fff;text-decoration:none;font-weight:800;padding:13px;border-radius:12px;margin-top:18px;font-size:15px}
.code-demo{background:var(--s2);border:1.5px dashed var(--ac);border-radius:10px;padding:10px;text-align:center;font-family:monospace;font-size:22px;font-weight:800;letter-spacing:4px;color:var(--ac2);margin:8px 0}
</style></head><body><div class="wrap">
<h1>🎱 TICKET BINGO</h1>
<div class="sub">Guide du Joueur</div>
<div class="tag">Ton code, tes pions, tes tickets — tout pour jouer au bingo en direct</div>

<div class="regle">⚠️ À RETENIR : pour acheter des PIONS, tu traites avec l'ADMINISTRATEUR.<br>Pour TOUT LE RESTE — tickets, jeux, gains, questions — tu vois avec TON ORGANISATEUR.</div>

<div class="card"><h2>1. 🔑 Ton code personnel</h2>
<p>Ton organisateur te remet un <b>code unique</b> :</p>
<div class="code-demo">XXXXXX</div>
<p>C'est ta clé d'entrée. Sur la page d'accueil, tape-le dans <b>« 🎮 Espace Joueur »</b> et clique <b>« 🎯 Jouer maintenant ! »</b></p>
<div class="astuce">⭐ Ton code est PERMANENT : garde-le précieusement (note-le dans ton téléphone !). Tes pions y restent attachés pour toujours, de tournoi en tournoi. Ne le prête à personne.</div></div>

<div class="card"><h2>2. 🪙 Tes pions — ta monnaie de jeu</h2>
<p>Les pions servent à acheter tes tickets. Pour recharger, bouton <b>« 🪙 Commander des pions »</b> :</p>
<li><b>💳 Carte bancaire</b> : paiement sécurisé dans l'application, tes pions arrivent <b>instantanément</b></li>
<li><b>🏦 Virement (CCP ou Deblock)</b> : les coordonnées s'affichent à l'écran. <b>IMPORTANT : indique TON CODE dans le libellé du virement</b> — c'est lui qui permet de te créditer rapidement</li>
<li><b>🤝 Auprès de ton organisateur</b> : il peut te donner des pions directement</li>
<p>Ton solde de pions s'affiche dans ton espace, mis à jour en temps réel.</p></div>

<div class="card"><h2>3. 🎫 Commander tes tickets</h2>
<p>Quand ton organisateur annonce un jeu (« Samedi : 1 DOLLAR, jackpot ! »), l'annonce apparaît dans ton espace. Clique dessus, choisis ton <b>nombre de tickets</b>, et <b>paie avec tes pions</b>. Dès que l'organisateur valide, c'est réglé — il t'attribue ensuite tes feuilles de jeu.</p></div>

<div class="card"><h2>4. 🎮 Jouer le tournoi en direct</h2>
<li><b>Ton ticket s'affiche</b> avec tes feuilles à toi</li>
<li><b>Chaque boule tirée est annoncée à voix haute</b> sur ton téléphone (lettre + numéro)</li>
<li><b>Tes numéros se cochent automatiquement</b> — mais garde l'oeil, c'est toi la chef !</li>
<li><b>Tu entends ton organisateur en direct</b> au micro 🎙️</li>
<div class="astuce">💡 En arrivant : touche ton écran une fois (ça active le son) et garde l'application affichée pendant tout le tournoi. Mets ton téléphone en charge pour les longues soirées !</div></div>

<div class="card"><h2>5. 🏆 BINGO !</h2>
<p>Ta ligne est complète ? Appuie sur le bouton <b>BINGO</b> ! Ton organisateur reçoit l'alerte avec ton ticket, vérifie tes numéros, et valide ta victoire. C'est lui qui te remet tes gains <b>EN PIONS</b>. 🎉</p></div>

<a class="cta" href="https://ticket-bingo-production.up.railway.app">🎱 Jouer maintenant sur Ticket Bingo</a>
<div class="pied">Ticket Bingo — L'application des tournois de bingo en Polynésie 🌺<br>Bonne chance, et que les boules soient avec toi !</div>
</div></body></html>"""

@app.route("/confidentialite")
def politique_confidentialite():
    """Page publique : politique de confidentialité (requise pour le Play Store)"""
    return """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Politique de confidentialité — Ticket Bingo</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 24px; line-height: 1.7; color: #1a1a1a; background: #fff; }
  h1 { color: #0a6e82; font-size: 26px; border-bottom: 3px solid #1098ad; padding-bottom: 10px; }
  h2 { color: #0a6e82; font-size: 19px; margin-top: 32px; }
  p, li { font-size: 15px; }
  .date { color: #666; font-size: 14px; font-style: italic; }
  .contact { background: #f0f9fb; border: 1px solid #1098ad; border-radius: 8px; padding: 16px; margin-top: 24px; }
  a { color: #1098ad; }
</style>
</head>
<body>

<h1>Politique de confidentialité — Ticket Bingo</h1>
<p class="date">Dernière mise à jour : 14 juin 2026</p>

<p>La présente politique de confidentialité décrit comment l'application <strong>Ticket Bingo</strong>, éditée par <strong>TUKEA IMPORT</strong> (Papeete, Polynésie française), collecte, utilise et protège les informations des personnes qui l'utilisent. En utilisant l'application, vous acceptez les pratiques décrites ci-dessous.</p>

<h2>1. Responsable du traitement</h2>
<p>Le responsable du traitement des données est :</p>
<p><strong>TUKEA IMPORT</strong><br>
Papeete, Polynésie française<br>
Adresse de contact : <a href="mailto:directionvaikeashop@gmail.com">directionvaikeashop@gmail.com</a></p>

<h2>2. Données que nous collectons</h2>
<p>Nous collectons uniquement les données nécessaires au fonctionnement de l'application :</p>
<ul>
<li><strong>Adresse email</strong> : demandée lors de l'inscription, pour créer et identifier votre compte et vous envoyer les informations liées à votre participation.</li>
<li><strong>Nom ou pseudonyme</strong> : pour vous identifier au sein des tournois.</li>
<li><strong>Données de jeu</strong> : votre solde de pions, vos participations aux tournois, vos tickets et l'historique de vos parties.</li>
<li><strong>Données techniques</strong> : informations de connexion nécessaires au bon fonctionnement et à la sécurité du service.</li>
</ul>

<h2>3. Utilisation des données</h2>
<p>Vos données sont utilisées exclusivement pour :</p>
<ul>
<li>Créer et gérer votre compte ;</li>
<li>Vous permettre de participer aux tournois de bingo ;</li>
<li>Gérer votre solde de pions et vos tickets ;</li>
<li>Vous contacter au sujet de votre participation ;</li>
<li>Assurer la sécurité et le bon fonctionnement de l'application.</li>
</ul>
<p>Nous ne vendons, ne louons et ne cédons jamais vos données personnelles à des tiers à des fins commerciales.</p>

<h2>4. Paiements</h2>
<p>Les paiements en ligne sont traités par des prestataires de paiement sécurisés (notamment Stripe). Vos coordonnées bancaires complètes ne sont pas stockées par Ticket Bingo : elles sont traitées directement par le prestataire de paiement, qui applique ses propres normes de sécurité.</p>

<h2>5. Conservation des données</h2>
<p>Vos données sont conservées tant que votre compte est actif. Vous pouvez demander la suppression de votre compte et de vos données personnelles à tout moment en nous écrivant à l'adresse de contact ci-dessous.</p>

<h2>6. Partage des données</h2>
<p>Vos données peuvent être partagées uniquement avec :</p>
<ul>
<li>Les prestataires techniques qui hébergent et font fonctionner l'application ;</li>
<li>Le prestataire de paiement, pour traiter les transactions ;</li>
<li>Les autorités compétentes, si la loi l'exige.</li>
</ul>

<h2>7. Sécurité</h2>
<p>Nous mettons en œuvre des mesures techniques et organisationnelles raisonnables pour protéger vos données contre tout accès, modification ou divulgation non autorisés.</p>

<h2>8. Vos droits</h2>
<p>Conformément à la réglementation applicable, vous disposez d'un droit d'accès, de rectification et de suppression de vos données personnelles. Pour exercer ces droits, contactez-nous à l'adresse indiquée ci-dessous.</p>

<h2>9. Mineurs</h2>
<p>L'application est réservée aux personnes majeures. Nous ne collectons pas sciemment de données concernant des mineurs.</p>

<h2>10. Modifications de cette politique</h2>
<p>Nous pouvons mettre à jour cette politique de confidentialité. Toute modification sera publiée sur cette page avec une nouvelle date de mise à jour.</p>

<div class="contact">
<h2 style="margin-top:0">Nous contacter</h2>
<p style="margin-bottom:0">Pour toute question concernant cette politique de confidentialité ou vos données personnelles :<br>
<strong>TUKEA IMPORT</strong><br>
<a href="mailto:directionvaikeashop@gmail.com">directionvaikeashop@gmail.com</a></p>
</div>

</body>
</html>"""

@app.route("/api/organisateur/mes-joueurs")
def mes_joueurs():
    """ORGANISATEUR — Ses joueurs avec codes, tickets et soldes de pions"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify([]), 403
    if s.get("admin"):
        tickets = DB.get("tickets", [])
    else:
        tickets = [t for t in DB.get("tickets", []) if t.get("code_org") == s["code"]]
    out = []
    for t in tickets:
        code = (t.get("code_acheteur") or "").upper()
        solde = DB.get("pions_joueurs", {}).get(code, {})
        out.append({
            "id": t.get("id"),
            "code": code,
            "acheteur": t.get("acheteur", ""),
            "jeu": t.get("jeu", ""),
            "serie": t.get("serie", ""),
            "page_debut": t.get("page_debut"),
            "page_fin": t.get("page_fin"),
            "pdf_url": t.get("pdf_url"),
            "email": t.get("email", ""),
            "solde_pions": {
                "20": solde.get("20", 0),
                "50": solde.get("50", 0),
                "100": solde.get("100", 0)
            }
        })
    return jsonify(out)

@app.route("/api/ticket/modifier", methods=["POST"])
def modifier_ticket():
    """ORGANISATEUR — Assigner/modifier le jeu, le PDF et les pages d'un ticket joueur"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s:
        return jsonify({"ok": False}), 403
    d = request.json
    tid = d.get("ticket_id", "")
    t = next((x for x in DB.get("tickets", []) if x.get("id") == tid), None)
    if not t:
        return jsonify({"ok": False, "msg": "Ticket introuvable"}), 404
    if not s.get("admin") and t.get("code_org") != s["code"]:
        return jsonify({"ok": False, "msg": "Ce ticket ne vous appartient pas"}), 403
    for champ in ["acheteur", "jeu", "serie", "email"]:
        if d.get(champ) is not None and str(d.get(champ)).strip() != "":
            t[champ] = str(d[champ]).strip()
    for champ in ["page_debut", "page_fin", "prix"]:
        if d.get(champ) not in (None, ""):
            try:
                t[champ] = int(d[champ])
            except Exception:
                pass
    if d.get("pdf_url"):
        t["pdf_url"] = d["pdf_url"]
    save_data()
    return jsonify({"ok": True, "ticket": t})

@app.route("/api/admin/recreer-tickets", methods=["POST"])
def recreer_tickets_masse():
    """ADMIN — Recree des tickets en masse apres un reset.
    Une ligne = un code existant (reutilise) OU +Nom (nouveau code genere)."""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    lignes = [l.strip() for l in (d.get("lignes") or "").split("\n") if l.strip()]
    code_org = d.get("code_org", "").upper().strip() or "ADMIN"
    jeu = d.get("jeu", "").strip()
    if not lignes:
        return jsonify({"ok": False, "msg": "Liste vide"}), 400
    if len(lignes) > 100:
        return jsonify({"ok": False, "msg": "Maximum 100 lignes"}), 400
    resultats = []
    for ligne in lignes:
        try:
            if ligne.startswith("+"):
                # Nouvelle joueuse : nouveau code genere
                nom = ligne[1:].strip() or "Joueuse"
                code = gen_code(6)
                while code in DB.get("tickets_acheteurs", {}) or any(t.get("code_acheteur") == code for t in DB["tickets"]):
                    code = gen_code(6)
                statut = "nouveau"
            else:
                code = ligne.upper()
                if not (4 <= len(code) <= 8) or not code.isalnum():
                    resultats.append({"ligne": ligne, "code": "", "statut": "erreur : code invalide"})
                    continue
                deja = next((t for t in DB["tickets"] if t.get("code_acheteur", "").upper() == code), None)
                if deja:
                    resultats.append({"ligne": ligne, "code": code, "statut": "déjà actif — ignoré"})
                    continue
                nom = "Joueuse " + code
                statut = "réactivé"
            ticket = {
                "id": hashlib.md5(f"{nom}{code}{datetime.datetime.now()}".encode()).hexdigest()[:8],
                "acheteur": nom,
                "jeu": jeu,
                "serie": "-",
                "prix": 0,
                "photo_url": None,
                "pdf_url": None,
                "page_debut": None,
                "page_fin": None,
                "code_acheteur": code,
                "email": "",
                "code_org": code_org,
                "date": datetime.datetime.now().isoformat()
            }
            DB["tickets"].insert(0, ticket)
            if "tickets_acheteurs" not in DB:
                DB["tickets_acheteurs"] = {}
            DB["tickets_acheteurs"][code] = ticket["id"]
            resultats.append({"ligne": ligne, "code": code, "statut": statut})
        except Exception as e:
            resultats.append({"ligne": ligne, "code": "", "statut": f"erreur : {e}"})
    save_data()
    return jsonify({"ok": True, "resultats": resultats})

@app.route("/api/admin/crediter-masse", methods=["POST"])
def crediter_masse():
    """ADMIN — Credite plusieurs codes d'un coup (dedommagement, transferts en serie)"""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False}), 403
    d = request.json
    codes = [c.strip().upper() for c in (d.get("codes") or "").replace(",", "\n").split("\n") if c.strip()]
    valeur = str(int(d.get("valeur_pion", 0)))
    nb = int(d.get("nb_pions", 0))
    profil = d.get("profil", "joueur")  # joueur ou organisateur
    if not codes or valeur not in ["20", "50", "100"] or nb == 0:
        return jsonify({"ok": False, "msg": "Données invalides"}), 400
    if len(codes) > 200:
        return jsonify({"ok": False, "msg": "Maximum 200 codes à la fois"}), 400
    cible = "pions_org" if profil == "organisateur" else "pions_joueurs"
    if cible not in DB:
        DB[cible] = {}
    resultats = []
    for code in codes:
        if code not in DB[cible]:
            DB[cible][code] = {}
        DB[cible][code][valeur] = max(0, DB[cible][code].get(valeur, 0) + nb)
        resultats.append({"code": code, "solde": DB[cible][code]})
    # Tracabilite du geste
    if "credits_masse" not in DB:
        DB["credits_masse"] = []
    DB["credits_masse"].insert(0, {
        "id": secrets.token_hex(4).upper(),
        "codes": codes,
        "valeur_pion": int(valeur),
        "nb_pions": nb,
        "profil": profil,
        "motif": d.get("motif", ""),
        "par": s["code"],
        "date": datetime.datetime.now().isoformat()
    })
    save_data()
    return jsonify({"ok": True, "nb_codes": len(codes), "resultats": resultats})

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

# === GENERATION GENERIQUE : TOUS LES JEUX DU REGISTRE ===
@app.route("/api/admin/generer-jeu", methods=["POST"])
def generer_jeu_generique():
    """ADMIN — Genere un PDF pour N'IMPORTE QUEL jeu du registre GENERATEURS_JEUX.
    Couvre automatiquement OHANA 75 10 BOULES et tous les futurs jeux installes."""
    global DB
    DB = load_data()
    token = request.headers.get("X-Token", "")
    s = verif_session(token)
    if not s or not s.get("admin"):
        return jsonify({"ok": False, "msg": "Accès refusé"}), 403

    d = request.json or {}
    jeu = (d.get("jeu") or "").strip()
    infos = GENERATEURS_JEUX.get(jeu)
    if not infos:
        return jsonify({"ok": False, "msg": f"Jeu inconnu du registre : {jeu}"}), 404

    nb_tickets = max(1, min(int(d.get("nb_tickets", 500)), 1000))
    serie_start = max(1, int(d.get("serie_start", 1)))

    slug = "".join(c if c.isalnum() else "_" for c in jeu)
    output_path = f"/data/{slug}_{serie_start:05d}_to_{serie_start + nb_tickets - 1:05d}.pdf"
    os.makedirs("/data", exist_ok=True)

    try:
        infos["generer"](nb_tickets=nb_tickets, serie_start=serie_start, output_path=output_path)
        save_commande(jeu, nb_tickets, serie_start, output_path, d.get("client", ""))
        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"{slug}_{serie_start:05d}.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        print(f"[GENERER-JEU ERR] {jeu} : {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500

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

    # Calcul COTE SERVEUR (anti-triche) : commission CARTE = 2%, pions sur la valeur restante
    commission = round(montant * 0.02)
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

def _notifier_admin_stripe(titre, details, montant_xpf):
    """Email a l'administratrice a chaque paiement Stripe recu (restaure 12/06/2026)"""
    if not SENDGRID_API_KEY:
        return
    try:
        m = int(montant_xpf)
    except Exception:
        m = 0
    try:
        html = f"""
        <div style='font-family:sans-serif;max-width:480px;margin:0 auto;background:#0b0c12;color:#fff;padding:20px;border-radius:12px'>
          <h2 style='color:#34d399;margin:0 0 4px 0'>💳 Paiement carte reçu !</h2>
          <p style='color:#9ca3af;font-size:13px;margin:0 0 16px 0'>{datetime.datetime.now().strftime("%d/%m/%Y à %H:%M")}</p>
          <div style='background:#111218;border:1px solid #10b981;border-radius:10px;padding:16px'>
            <div style='font-size:26px;font-weight:800;color:#fbbf24;text-align:center;margin-bottom:10px'>{m:,} XPF</div>
            <p style='margin:4px 0;font-size:14px'><strong>{titre}</strong></p>
            <p style='margin:4px 0;font-size:13px;color:#d1d5db'>{details}</p>
            <p style='margin:8px 0 0 0;font-size:12px;color:#34d399'>✅ Crédité automatiquement — aucune action nécessaire</p>
          </div>
          <p style='font-size:11px;color:#6b7280;text-align:center;margin-top:14px'>Ticket Bingo — notification automatique Stripe</p>
        </div>"""
        message = Mail(from_email=(FROM_EMAIL, FROM_NAME), to_emails=FROM_EMAIL,
                       subject=f"💳 {m:,} XPF reçus — {titre}", html_content=html)
        SendGridAPIClient(SENDGRID_API_KEY).send(message)
    except Exception as e:
        print(f"[NOTIF STRIPE ERR] {e}")


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
                _notifier_admin_stripe(f"ABONNEMENT — code {code_org}",
                    "Abonnement organisateur payé et activé", montant)
        
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
                _notifier_admin_stripe(f"Pions ORGANISATEUR — code {code_org}",
                    f"{nb_pions} pions crédités automatiquement", montant)
        
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
                _notifier_admin_stripe(f"Pions JOUEUR — code {code_joueur}",
                    f"{nb_pions} pions de {valeur} XPF crédités automatiquement", montant)

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
                _notifier_admin_stripe(f"Pions ORGANISATEUR — code {code_o}",
                    f"{nb_pions} pions de {valeur} XPF crédités automatiquement", montant)

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
            _notifier_admin_stripe(f"Commande PDF — {jeu}",
                f"{nb_tickets} tickets commandés par {code_org}", montant)
        
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



@app.route("/codes-par-organisateur")
def codes_par_organisateur():
    """Affiche tous les codes joueurs classés par organisateur"""
    global DB
    DB = load_data()
    
    joueur_vers_org = {}
    joueur_vers_nom = {}
    for t in DB.get("tickets", []):
        cj = t.get("code_acheteur")
        co = t.get("code_org")
        if cj and co:
            joueur_vers_org[cj] = co
            if t.get("acheteur"):
                joueur_vers_nom[cj] = t.get("acheteur")
    
    orgs = {}
    for code, info in DB.get("codes", {}).items():
        if info.get("admin"):
            continue
        orgs.setdefault(code, {"nom": info.get("nom", "?"), "email": info.get("email", ""), "joueurs": []})
    
    tous_joueurs = set(DB.get("pions_joueurs", {}).keys())
    tous_joueurs.update(joueur_vers_org.keys())
    
    sans_org = []
    for cj in sorted(tous_joueurs):
        co = joueur_vers_org.get(cj)
        nom_j = joueur_vers_nom.get(cj, "")
        if co and co in orgs:
            orgs[co]["joueurs"].append({"code": cj, "nom": nom_j})
        else:
            sans_org.append({"code": cj, "nom": nom_j})
    
    html = """<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Codes par organisateur</title><style>body{font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;padding:20px}h1{color:#58a6ff}h2{color:#3fb950;margin:0 0 4px 0}.org{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;margin:16px 0}.email{color:#8b949e;font-size:13px;margin-bottom:10px}.joueur{background:#0d1117;padding:8px 12px;margin:4px 0;border-radius:6px;border-left:3px solid #58a6ff}.code{font-weight:bold;color:#f0883e;font-family:monospace;font-size:16px}.nom{color:#8b949e;margin-left:10px}.count{background:#1f6feb;color:white;padding:2px 10px;border-radius:12px;font-size:13px}</style></head><body><h1>Codes joueurs par organisateur</h1>"""
    
    for co, data_org in orgs.items():
        nb = len(data_org["joueurs"])
        html += f"<div class='org'><h2>{data_org['nom']} <span class='count'>{nb}</span></h2><div class='email'>{co}"
        if data_org["email"]:
            html += f" - {data_org['email']}"
        html += "</div>"
        for j in data_org["joueurs"]:
            html += f"<div class='joueur'><span class='code'>{j['code']}</span><span class='nom'>{j['nom']}</span></div>"
        html += "</div>"
    
    if sans_org:
        html += f"<div class='org'><h2>Joueurs sans org ({len(sans_org)})</h2>"
        for j in sans_org:
            html += f"<div class='joueur'><span class='code'>{j['code']}</span><span class='nom'>{j['nom']}</span></div>"
        html += "</div>"
    
    html += "</body></html>"
    return html



@app.route("/releve-transactions")
def releve_transactions():
    """Relevé de toutes les transactions (comme un relevé bancaire)"""
    global DB
    DB = load_data()
    
    transactions = []
    
    # Paiements Stripe (ventes de pions/tickets)
    for pid, p in DB.get("paiements_stripe", {}).items():
        if p.get("statut") == "valide":
            transactions.append({
                "date": p.get("date", "?"),
                "type": "Paiement Stripe",
                "description": f"Vente pions/tickets - {p.get('description', '?')}",
                "montant_entree": p.get("montant_xpf", 0),
                "montant_sortie": 0,
                "code": p.get("code_joueur", "?")
            })
    
    # Ventes de tickets
    for v in DB.get("ventes", []):
        transactions.append({
            "date": v.get("date", "?"),
            "type": "Vente de tickets",
            "description": f"{v.get('jeu', '?')} - Pack {v.get('pack', '?')} cartes",
            "montant_entree": v.get("total", 0),
            "montant_sortie": 0,
            "code": v.get("code_org", "?")
        })
    
    # Commandes de pions
    for cpo in DB.get("commandes_pions_joueurs", []):
        montant = cpo.get("montant_total_xpf", 0)
        transactions.append({
            "date": cpo.get("date", "?"),
            "type": "Achat de pions",
            "description": f"Commande pions - {cpo.get('pack_type', '?')}",
            "montant_entree": montant,
            "montant_sortie": 0,
            "code": cpo.get("code_joueur", "?")
        })
    
    # Transactions pions (crédit/débit)
    for tp in DB.get("transactions_pions", []):
        if tp.get("type") == "achat":
            transactions.append({
                "date": tp.get("date", "?"),
                "type": "Crédit pions",
                "description": f"{tp.get('montant', 0)} XPF - {tp.get('raison', '?')}",
                "montant_entree": tp.get("montant", 0),
                "montant_sortie": 0,
                "code": tp.get("code_joueur", "?")
            })
    
    # Trier par date (plus récent d'abord)
    transactions.sort(key=lambda x: x["date"], reverse=True)
    
    # Calculer les totaux
    total_entrees = sum(t["montant_entree"] for t in transactions)
    total_sorties = sum(t["montant_sortie"] for t in transactions)
    solde = total_entrees - total_sorties
    
    # Générer HTML
    html = """<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Relevé de transactions</title><style>
    body{font-family:'Courier New',monospace;background:#0d1117;color:#e6edf3;padding:20px}
    h1{color:#58a6ff;text-align:center}
    .resume{background:#161b22;border:2px solid #30363d;border-radius:10px;padding:16px;margin:20px 0;display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;text-align:center}
    .resume-item h3{color:#3fb950;margin:0;font-size:14px;color:#8b949e}
    .resume-item .montant{font-size:24px;font-weight:bold;font-family:monospace}
    .entrees{color:#3fb950}
    .sorties{color:#f85149}
    .solde{color:#58a6ff}
    table{width:100%;border-collapse:collapse;background:#161b22;border:1px solid #30363d;margin-top:20px}
    th{background:#0d1117;border:1px solid #30363d;padding:12px;text-align:left;color:#8b949e;font-weight:bold;font-size:12px}
    td{border:1px solid #30363d;padding:12px;font-size:13px}
    tr:nth-child(even){background:#161b22}
    tr:hover{background:#21262d}
    .date{color:#8b949e;width:180px}
    .type{color:#58a6ff;font-weight:bold;width:120px}
    .description{color:#e6edf3}
    .montant-entree{color:#3fb950;text-align:right;width:100px;font-weight:bold}
    .montant-sortie{color:#f85149;text-align:right;width:100px;font-weight:bold}
    .code{color:#f0883e;font-weight:bold;width:80px}
    </style></head><body>
    <h1>📊 Relevé de transactions</h1>
    <div class='resume'>
        <div class='resume-item'>
            <h3>Entrées</h3>
            <div class='montant entrees'>+{total_entrees:,} XPF</div>
        </div>
        <div class='resume-item'>
            <h3>Sorties</h3>
            <div class='montant sorties'>-{total_sorties:,} XPF</div>
        </div>
        <div class='resume-item'>
            <h3>Solde</h3>
            <div class='montant solde'>{solde:,} XPF</div>
        </div>
    </div>
    <table>
        <thead>
            <tr>
                <th class='date'>Date</th>
                <th class='type'>Type</th>
                <th class='description'>Description</th>
                <th class='code'>Code</th>
                <th class='montant-entree'>+ Entrée</th>
                <th class='montant-sortie'>- Sortie</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for t in transactions:
        e = f"{t['montant_entree']:,}" if t['montant_entree'] > 0 else ""
        s = f"{t['montant_sortie']:,}" if t['montant_sortie'] > 0 else ""
        html += f"""<tr>
            <td class='date'>{t['date'][:16]}</td>
            <td class='type'>{t['type']}</td>
            <td class='description'>{t['description']}</td>
            <td class='code'>{t['code']}</td>
            <td class='montant-entree'>{e}</td>
            <td class='montant-sortie'>{s}</td>
        </tr>"""
    
    html += """</tbody></table></body></html>"""
    return html



@app.route("/releve/<code>")
def releve_code(code):
    """Relevé de compte pour un joueur ou organisateur spécifique"""
    global DB
    DB = load_data()
    
    # Vérifier que le code existe
    if code not in DB.get("codes", {}):
        return "<h1>Code introuvable</h1>", 404
    
    info_code = DB["codes"][code]
    nom_code = info_code.get("nom", code)
    
    transactions = []
    
    try:
        # Paiements Stripe
        for pid, p in DB.get("paiements_stripe", {}).items():
            if isinstance(p, dict) and p.get("code_joueur") == code and p.get("statut") == "valide":
                transactions.append({
                    "date": p.get("date", "?"),
                    "type": "Paiement",
                    "description": p.get("description", "?"),
                    "entree": p.get("montant_xpf", 0),
                    "sortie": 0
                })
    except:
        pass
    
    try:
        # Ventes de tickets
        for v in DB.get("ventes", []):
            if isinstance(v, dict) and v.get("code_org") == code:
                transactions.append({
                    "date": v.get("date", "?"),
                    "type": "Vente tickets",
                    "description": f"{v.get('jeu', '?')} - {v.get('pack', '?')} cartes",
                    "entree": v.get("total", 0),
                    "sortie": 0
                })
    except:
        pass
    
    try:
        # Commandes pions
        for cpo in DB.get("commandes_pions_joueurs", []):
            if isinstance(cpo, dict) and cpo.get("code_joueur") == code:
                transactions.append({
                    "date": cpo.get("date", "?"),
                    "type": "Achat pions",
                    "description": f"Pack {cpo.get('pack_type', '?')}",
                    "entree": cpo.get("montant_total_xpf", 0),
                    "sortie": 0
                })
    except:
        pass
    
    transactions.sort(key=lambda x: x["date"], reverse=True)
    
    total_e = sum(t["entree"] for t in transactions)
    total_s = sum(t["sortie"] for t in transactions)
    solde = total_e - total_s
    
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'><title>Relevé {code}</title><style>
    body{{font-family:monospace;background:#0d1117;color:#e6edf3;padding:20px}}
    h1{{color:#58a6ff}}
    .info{{color:#8b949e;margin:10px 0 30px 0}}
    .totaux{{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px;margin:20px 0;display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;text-align:center}}
    .montant{{font-size:20px;font-weight:bold}}
    .vert{{color:#3fb950}}
    .rouge{{color:#f85149}}
    .bleu{{color:#58a6ff}}
    table{{width:100%;border-collapse:collapse;margin-top:20px}}
    th{{background:#0d1117;border:1px solid #30363d;padding:10px;text-align:left;color:#8b949e}}
    td{{border:1px solid #30363d;padding:10px}}
    tr:hover{{background:#21262d}}
    </style></head><body>
    <h1>Relevé de {code}</h1>
    <div class='info'>{nom_code}</div>
    <div class='totaux'>
        <div><strong>Entrées</strong><br><span class='montant vert'>+{total_e:,} XPF</span></div>
        <div><strong>Sorties</strong><br><span class='montant rouge'>-{total_s:,} XPF</span></div>
        <div><strong>Solde</strong><br><span class='montant bleu'>{solde:,} XPF</span></div>
    </div>
    """
    
    if transactions:
        html += "<table><tr><th>Date</th><th>Type</th><th>Description</th><th>Entrée</th><th>Sortie</th></tr>"
        for t in transactions:
            e = f"{t['entree']:,}" if t['entree'] > 0 else ""
            s = f"{t['sortie']:,}" if t['sortie'] > 0 else ""
            html += f"<tr><td>{t['date'][:16]}</td><td>{t['type']}</td><td>{t['description']}</td><td>{e}</td><td>{s}</td></tr>"
        html += "</table>"
    else:
        html += "<p style='color:#8b949e;margin-top:20px'>Aucune transaction</p>"
    
    html += f"""<br><br><a href="/releve/{code}/download" style="padding:10px 20px;background:#58a6ff;color:#0d1117;border:none;border-radius:4px;cursor:pointer;font-weight:bold;text-decoration:none;display:inline-block">Telecharger en TXT</a></body></html>"""
    return html

    return html




@app.route("/releves-all")
def releves_all():
    global DB
    DB = load_data()
    
    codes = sorted(DB.get("codes", {}).items(), key=lambda x: x[1].get("nom", ""))
    
    html = '''<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Releves</title><style>
    body{font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;padding:20px}
    h1{color:#58a6ff;text-align:center}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;max-width:1200px;margin:0 auto}
    .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:16px}
    .card:hover{border-color:#58a6ff;background:#21262d}
    .nom{color:#58a6ff;font-weight:bold;font-size:15px;margin-bottom:8px}
    .code{color:#8b949e;font-family:monospace;font-size:12px;margin-bottom:12px}
    .badge{display:inline-block;padding:4px 8px;border-radius:4px;font-size:11px;background:#0d1117;color:#3fb950}
    .link{display:block;margin-top:12px;padding:10px;background:#58a6ff;color:#0d1117;text-decoration:none;border-radius:4px;text-align:center;font-weight:bold}
    </style></head><body>
    <h1>Tous les releves</h1>
    <div class="grid">'''
    
    for code, info in codes:
        nom = info.get("nom", code)
        badge = "Admin" if info.get("admin") else "Code"
        html += f'<div class="card"><div class="nom">{nom}</div><div class="code">{code}</div><div class="badge">{badge}</div><a href="/releve/{code}" class="link">Voir</a></div>'
    
    html += '</div></body></html>'
    return html








@app.route("/releve/<code>/download")
def releve_download(code):
    global DB
    DB = load_data()
    
    if code not in DB.get("codes", {}):
        return "Code introuvable", 404
    
    info = DB["codes"][code]
    nom = info.get("nom", code)
    
    lines = [f"RELEVE DE {code}", f"Nom: {nom}", ""]
    
    for v in DB.get("ventes", []):
        if v.get("code_org") == code:
            lines.append(f"{v.get('date', '?')[:10]} | Vente {v.get('jeu', '?')} | {v.get('total', 0)} XPF")
    
    for p in DB.get("paiements_stripe", {}).values():
        if p.get("code_joueur") == code and p.get("statut") == "valide":
            lines.append(f"{p.get('date', '?')[:10]} | Paiement | {p.get('montant_xpf', 0)} XPF")
    
    text = "\n".join(lines)
    response = make_response(text)
    response.headers["Content-Disposition"] = f"attachment; filename=releve_{code}.txt"
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    return response
