import os
import re
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template, abort
from flask_cors import CORS
from google import genai
from google.genai import types

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

MODEL = "gemini-flash-lite-latest"

RULES = [
    "specifications_presentes",
    "orientation_benefices",
    "cta_clair",
    "reassurance_livraison_retours",
    "preuve_sociale",
    "urgence_ethique",
    "lisibilite_structure",
    "disponibilite_variantes",
    "cbd_conformite_legale",
    "cbd_transparence_produit",
    "cbd_allegations_medicales",
    "cbd_marketing_ethique",
]

current_text_context = ""

# --- Helper load data ---
def load_articles():
    try:
        with open(os.path.join(app.root_path, 'data', 'articles.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading articles: {e}")
        return []

def get_article_by_slug(slug):
    articles = load_articles()
    for article in articles:
        if article.get('slug') == slug:
            return article
    return None

def check_rule(rule_id: str) -> str:
    """Verifie une regle CRO/UX precise sur la fiche produit et retourne un constat."""
    text = current_text_context
    
    if rule_id == "specifications_presentes":
        hit = re.search(r"\d|taille|dimension|mati[eè]re|poids|composition|cm|kg|g/m", text, re.I)
        return "Caracteristiques mesurables presentes." if hit else "Aucune specification concrete, a ajouter (matiere, poids, dimensions)."
    elif rule_id == "orientation_benefices":
        hit = re.search(r"\bvous\b|\bvotre\b|permet|id[ée]al pour|offre|profite", text, re.I)
        return "La fiche s'adresse au client / evoque un benefice." if hit else "Purement descriptive, reformuler en benefices pour le client."
    elif rule_id == "cta_clair":
        hit = re.search(r"ajouter au panier|acheter|commander|je commande", text, re.I)
        return "CTA d'achat identifiable." if hit else "Aucun CTA explicite detecte, critere Baymard essentiel a corriger en priorite."
    elif rule_id == "reassurance_livraison_retours":
        hit = re.search(r"livraison|retour|remboursement|garantie", text, re.I)
        return "Rassurance livraison/retours presente." if hit else "Aucune information livraison/retours, source d'anxiete pre-achat documentee par Baymard."
    elif rule_id == "preuve_sociale":
        hit = re.search(r"avis|étoile|etoile|note|clients ont|/5|★", text, re.I)
        return "Preuve sociale presente." if hit else "Aucun avis client ni note visible, levier de conversion absent."
    elif rule_id == "urgence_ethique":
        vague = re.search(r"d[ée]p[ée]chez|ne ratez pas|offre limit[ée]e(?!.*\d)", text, re.I)
        chiffree = re.search(r"plus que \d+|reste(nt)? \d+|jusqu'? ?\à.*\d", text, re.I)
        if chiffree:
            return "Urgence chiffree presente : verifier qu'elle reflete un stock reel avant publication (sinon dark pattern)."
        elif vague:
            return "Urgence non chiffree detectee : risque de fausse urgence, a corriger ou a chiffrer reellement."
        return "Aucune urgence affichee, neutre."
    elif rule_id == "lisibilite_structure":
        lines = [l for l in text.strip().split("\n") if l.strip()]
        bullets = sum(1 for l in lines if l.strip().startswith(("-", "•", "*")))
        words = len(text.split())
        if bullets == 0 and words > 40:
            return f"Bloc de texte dense ({words} mots, aucune liste), a structurer en puces pour le scan visuel."
        return f"Structure raisonnablement scannable ({words} mots, {bullets} ligne(s) en liste)."
    elif rule_id == "disponibilite_variantes":
        hit = re.search(r"taille|couleur|stock|disponible", text, re.I)
        return "Variantes/disponibilite indiquees." if hit else "Aucune indication de tailles/couleurs/stock, a ajouter."
        
    elif rule_id == "cbd_conformite_legale":
        hit_thc = re.search(r"0[.,]3%|0[.,]2%|thc|l[ée]gal", text, re.I)
        hit_age = re.search(r"mineur|18 ans|interdit", text, re.I)
        hit_edible = re.search(r"gummies|bonbon|chocolat|gummiz", text, re.I)
        hit_delta9 = re.search(r"delta[- ]9|d9", text, re.I)
        
        res = []
        if not hit_thc: res.append("Taux de THC légal (<0.3%) non mentionné explicitement.")
        if not hit_age: res.append("Interdiction aux mineurs non mentionnée.")
        if hit_edible and hit_delta9: 
            res.append("ALERTE LÉGALE : Vente de comestibles (gummies/chocolats) contenant du Delta-9 THC détectée. Pratique totalement illégale en France (assimilé stupéfiant).")
        elif hit_edible:
            res.append("ALERTE : Vente de comestibles (gummies). Tolérance floue en France (Novel Food), souvent illégal.")
            
        return " ".join(res) if res else "Conformité légale de base (THC, âge) mentionnée sans infractions évidentes."
        
    elif rule_id == "cbd_transparence_produit":
        synth = re.search(r"hhc|h4cbd|h3|vmac|synth[ée]tique|hhc-p|thcp", text, re.I)
        bio_fleur = re.search(r"fleur.*bio|bio.*fleur", text, re.I)
        
        res = []
        if synth: res.append("Présence de cannabinoïdes synthétiques ou semi-synthétiques détectée. Transparence à vérifier.")
        if bio_fleur: res.append("Usage du terme 'bio' associé à des fleurs détecté (souvent abusif dans ce secteur).")
        
        # Detection des taux de CBD impossibles
        cbd_matches = re.findall(r"cbd\+?\s*[:\-]?\s*(\d+[.,]?\d*)\s*%", text, re.I)
        for match in cbd_matches:
            try:
                val = float(match.replace(',', '.'))
                if val >= 12.0:
                    res.append(f"ATTENTION : Taux de CBD annoncé suspect ({val}%). Avec un THC légal < 0.3%, un tel ratio naturel est impossible. Probable fleur manipulée chimiquement (ajout d'isolat non mentionné).")
                    break
            except:
                pass

        return " ".join(res) if res else "Aucun ajout synthétique ou abus de label 'bio' détecté."
        
    elif rule_id == "cbd_allegations_medicales":
        alleg = re.search(r"gu[ée]rit|soigne|th[ée]rapeutique|m[ée]dicament|d[ée]pression|insomnie|douleur", text, re.I)
        return f"Allégations médicales potentiellement illégales détectées ({alleg.group(0)})." if alleg else "Aucune allégation médicale directe détectée."
        
    elif rule_id == "cbd_marketing_ethique":
        hit_high = re.search(r"d[ée]fonce|planer|stone\b|stoned|perch[ée]|d[ée]chirer|d[ée]chir[ée]|d[ée]fonc[ée]", text, re.I)
        if hit_high:
            return f"MARKETING AGRESSIF/ILLICITE : Vocabulaire récréatif ('{hit_high.group(0)}') détecté. S'éloigne du bien-être pour promettre des effets psychoactifs."
        return "Marketing : pas de vocabulaire orienté 'défonce' flagrant."
        
    return "Regle inconnue."

# --- Routes Web ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/guides')
def guides():
    articles = load_articles()
    # Trier par numéro (ordre logique défini par le Pôle)
    articles.sort(key=lambda x: x.get('number', 99))
    return render_template('blog_index.html', articles=articles)

@app.route('/guides/<slug>')
def article_detail(slug):
    article = get_article_by_slug(slug)
    if not article:
        abort(404)
    return render_template('article_detail.html', article=article)

# --- Route API ---
@app.route('/api/audit', methods=['POST'])
def audit():
    global current_text_context
    data = request.json
    if not data or 'url' not in data:
        return jsonify({"error": "URL manquante"}), 400
        
    url = data['url']
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style"]):
            script.decompose()
        current_text_context = soup.get_text(separator=' ', strip=True)
    except Exception as e:
        return jsonify({"error": f"Erreur de téléchargement: {str(e)}"}), 500

    try:
        # Pre-calcul des règles en Python pour eviter de faire 12 requetes API (Rate Limit)
        rule_results = []
        for rule in RULES:
            res = check_rule(rule)
            rule_results.append(f"- {rule} : {res}")
        rules_text = "\n".join(rule_results)

        client = genai.Client()
        prompt = f"""/ROLE: Expert Legal CBD & CRO
/TASK: Audit fiche produit
/URL: {url}
/DATA:
{current_text_context}
/REGEX_FLAGS:
{rules_text}

/FORMAT_OUTPUT: Markdown strict
- H1: Audit **[Produit]** (**[Site]**)
- H2: Note Globale d'Audit : [Score]/100
- Paragraphe court expliquant la note.
- H2: Fiche Technique Synthétique (Prix, Taux, Type)
- H2: 1. Résumé Exécutif
- H2: 2. Traçabilité & Labo (Origine, Culture, COA)
- H2: 3. Dark Patterns & Biais
- H2: 4. Tableau Constats (Catégorie, Détail, Impact, Effort, Priorité 🔴🟠🟢)
- H2: 5. Plan Action (🔴 Urgences Légales avec Rappel Loi, 🟠 Éthique, 🟢 UX/CRO)

/RULES:
1. Gras OBLIGATOIRE sur taux aberrants, expressions illégales et faits extraits.
2. Direct, factuel, zéro introduction, pas de blabla.
"""
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt
        )
        return jsonify({"report": response.text})
    except Exception as e:
        return jsonify({"error": f"Erreur Gemini API: {str(e)}"}), 500

if __name__ == '__main__':
    os.makedirs('static', exist_ok=True)
    app.run(port=5000, debug=True)

