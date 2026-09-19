"""
Agent d'audit CRO/UX de fiche produit, version Gemini.

Installation :
    pip install -U google-genai

Cle API (gratuite) :
    1. https://aistudio.google.com/apikey -> "Create API key"
    2. export GEMINI_API_KEY="ta_cle"

Lancement :
    python mini_agent_gemini.py [URL_OPTIONNELLE]
"""

import re
import sys
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

MODEL = "gemini-flash-lite-latest"  # remplace par un autre modele de ton compte AI Studio si besoin

# Colle ici le contenu complet de la fiche produit a auditer :
# titre, description, prix, CTA, livraison/retours, avis, variantes...
PAGE_CONTENT = """
Sweat a capuche unisexe en coton bio 320g/m2. Coupe oversize, poche kangourou,
cordon de serrage assorti.
Prix : 59,90 EUR
Tailles disponibles : S, M, L, XL
[Ajouter au panier]
Livraison offerte des 50 EUR d'achat, retours gratuits sous 30 jours.
Plus que 3 en stock dans cette taille !
"""

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


def check_rule(rule_id: str) -> str:
    """Verifie une regle CRO/UX precise sur la fiche produit et retourne un constat.

    Args:
      rule_id: une des regles suivantes : specifications_presentes,
        orientation_benefices, cta_clair, reassurance_livraison_retours,
        preuve_sociale, urgence_ethique, lisibilite_structure,
        disponibilite_variantes.
    """
    print(f"  outil appele : check_rule({rule_id})")
    text = PAGE_CONTENT

    if rule_id == "specifications_presentes":
        hit = re.search(r"\d|taille|dimension|mati[eè]re|poids|composition|cm|kg|g/m", text, re.I)
        result = "Caracteristiques mesurables presentes." if hit else "Aucune specification concrete, a ajouter (matiere, poids, dimensions)."

    elif rule_id == "orientation_benefices":
        hit = re.search(r"\bvous\b|\bvotre\b|permet|id[ée]al pour|offre|profite", text, re.I)
        result = "La fiche s'adresse au client / evoque un benefice." if hit else "Purement descriptive, reformuler en benefices pour le client."

    elif rule_id == "cta_clair":
        hit = re.search(r"ajouter au panier|acheter|commander|je commande", text, re.I)
        result = "CTA d'achat identifiable." if hit else "Aucun CTA explicite detecte, critere Baymard essentiel a corriger en priorite."

    elif rule_id == "reassurance_livraison_retours":
        hit = re.search(r"livraison|retour|remboursement|garantie", text, re.I)
        result = "Rassurance livraison/retours presente." if hit else "Aucune information livraison/retours, source d'anxiete pre-achat documentee par Baymard."

    elif rule_id == "preuve_sociale":
        hit = re.search(r"avis|étoile|etoile|note|clients ont|/5|★", text, re.I)
        result = "Preuve sociale presente." if hit else "Aucun avis client ni note visible, levier de conversion absent."

    elif rule_id == "urgence_ethique":
        vague = re.search(r"d[ée]p[ée]chez|ne ratez pas|offre limit[ée]e(?!.*\d)", text, re.I)
        chiffree = re.search(r"plus que \d+|reste(nt)? \d+|jusqu'? ?\à.*\d", text, re.I)
        if chiffree:
            result = "Urgence chiffree presente : verifier qu'elle reflete un stock reel avant publication (sinon dark pattern)."
        elif vague:
            result = "Urgence non chiffree detectee : risque de fausse urgence, a corriger ou a chiffrer reellement."
        else:
            result = "Aucune urgence affichee, neutre."

    elif rule_id == "lisibilite_structure":
        lines = [l for l in text.strip().split("\n") if l.strip()]
        bullets = sum(1 for l in lines if l.strip().startswith(("-", "•", "*")))
        words = len(text.split())
        if bullets == 0 and words > 40:
            result = f"Bloc de texte dense ({words} mots, aucune liste), a structurer en puces pour le scan visuel."
        else:
            result = f"Structure raisonnablement scannable ({words} mots, {bullets} ligne(s) en liste)."

    elif rule_id == "disponibilite_variantes":
        hit = re.search(r"taille|couleur|stock|disponible", text, re.I)
        result = "Variantes/disponibilite indiquees." if hit else "Aucune indication de tailles/couleurs/stock, a ajouter."

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
            
        result = " ".join(res) if res else "Conformité légale de base (THC, âge) mentionnée sans infractions évidentes."
        
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

        result = " ".join(res) if res else "Aucun ajout synthétique ou abus de label 'bio' détecté."
        
    elif rule_id == "cbd_allegations_medicales":
        alleg = re.search(r"gu[ée]rit|soigne|th[ée]rapeutique|m[ée]dicament|d[ée]pression|insomnie|douleur", text, re.I)
        result = f"Allégations médicales potentiellement illégales détectées ({alleg.group(0)})." if alleg else "Aucune allégation médicale directe détectée."
        
    elif rule_id == "cbd_marketing_ethique":
        hit_high = re.search(r"d[ée]fonce|planer|stone\b|stoned|perch[ée]|d[ée]chirer|d[ée]chir[ée]|d[ée]fonc[ée]", text, re.I)
        if hit_high:
            result = f"MARKETING AGRESSIF/ILLICITE : Vocabulaire récréatif ('{hit_high.group(0)}') détecté. S'éloigne du bien-être pour promettre des effets psychoactifs."
        else:
            result = "Marketing : pas de vocabulaire orienté 'défonce' flagrant."

    else:
        result = "Regle inconnue."

    print(f"  resultat : {result}")
    return result


def main():
    global PAGE_CONTENT
    url_info = "URL non fournie (texte brut)"
    if len(sys.argv) > 1:
        url = sys.argv[1]
        url_info = url
        print(f"Telechargement de {url}...")
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.decompose()
            PAGE_CONTENT = soup.get_text(separator=' ', strip=True)
            print(f"Contenu recupere ({len(PAGE_CONTENT)} caracteres).")
        except Exception as e:
            print(f"Erreur lors de la recuperation de l'URL : {e}")
            return

    print("Pre-calcul des regles en cours...")
    rule_results = []
    for rule in RULES:
        res = check_rule(rule)
        rule_results.append(f"- {rule} : {res}")
    rules_text = "\n".join(rule_results)

    client = genai.Client()

    prompt = f"""/ROLE: Expert Legal CBD & CRO
/TASK: Audit fiche produit
/URL: {url_info}
/DATA:
{PAGE_CONTENT}
/REGEX_FLAGS:
{rules_text}

/FORMAT_OUTPUT: Markdown strict
- H1: Audit **[Produit]** (**[Site]**)
- H2: 🏆 Note Globale d'Audit (/100)
- H2: 📋 Fiche Technique Synthétique (Prix, Taux, Type)
- H2: 1. Résumé Exécutif
- H2: 2. Traçabilité & Labo (Origine, Culture, COA)
- H2: 3. Dark Patterns & Biais
- H2: 4. Tableau Constats (Catégorie, Détail, Impact, Effort, Priorité 🔴🟡🟢)
- H2: 5. Plan Action (🔴 Urgences Légales avec Rappel Loi, 🟡 Éthique, 🟢 UX/CRO)

/RULES:
1. Gras OBLIGATOIRE sur taux aberrants, expressions illégales et faits extraits.
2. Direct, factuel, zéro introduction, pas de blabla.
"""

    print("Tache envoyee a l'agent (1 seule requete API)...\n")

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt
    )

    print("\nrapport final de l'agent :\n")
    print(response.text)

    print("\npoint de controle humain")
    valid = input("Valider ce rapport ? (oui/non) : ").strip().lower()
    if valid == "oui":
        print("Audit valide par un humain. Aucune action n'a ete appliquee sans cette etape.")
    else:
        print("Audit non valide, rien n'est applique.")


if __name__ == "__main__":
    main()
