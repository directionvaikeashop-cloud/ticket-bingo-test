import hashlib, datetime, os
from flask import Flask, request, jsonify, send_from_directory

app = Flask(__name__, static_folder=".")
DB = {"ventes": [], "tickets": [], "jeux": ["Bingo Classique", "Bingo Or", "Bingo Tropical", "Super Jackpot"]}

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

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
    vente = {"id": hashlib.md5(f"{d['client']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "client": d["client"], "jeu": d["jeu"], "pack": int(d.get("pack", 25)),
        "qty": int(d.get("qty", 1)), "total_feuilles": int(d.get("qty", 1)) * int(d.get("pack", 25)),
        "serie": d["serie"], "prix": int(d.get("prix", 0)), "total": total,
        "date": datetime.datetime.now().isoformat()}
    DB["ventes"].insert(0, vente)
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
    ticket = {"id": hashlib.md5(f"{d['acheteur']}{d['serie']}{datetime.datetime.now()}".encode()).hexdigest()[:8],
        "acheteur": d["acheteur"], "jeu": d["jeu"], "serie": d["serie"],
        "prix": int(d.get("prix", 0)), "date": datetime.datetime.now().isoformat()}
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
