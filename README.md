# stockmonitor 🌬️

Surveille le stock d'un climatiseur (Leroy Merlin / Castorama) dans les magasins près de chez toi, et te prévient quand il revient en stock.

> Codé avec passion, uniquement à but de recherche et d'information — pour donner un coup de main à celles et ceux qui galèrent à trouver une clim, et surtout aux personnes les plus vulnérables face à la canicule. 🙏

---

## 🐣 Tu ne codes pas ? Pas de panique.

Tu n'as **rien à comprendre au code**. Juste 3 étapes, une seule fois, puis une seule commande à retenir. Suis le guide.

---

## 1️⃣ Installer Python (une seule fois)

- **Windows** : va sur [python.org/downloads](https://www.python.org/downloads/), télécharge Python, lance l'installateur et **coche la case « Add Python to PATH »** avant de cliquer sur Install.
- **Mac** : Python est souvent déjà là. Sinon, télécharge-le aussi sur [python.org/downloads](https://www.python.org/downloads/).

---

## 2️⃣ Ouvrir le terminal dans le dossier du projet

Le « terminal », c'est la fenêtre noire où on tape des commandes.

- **Windows** : ouvre le dossier `lm-stock-monitor`, clique dans la barre d'adresse en haut, tape `cmd` puis Entrée.
- **Mac** : ouvre l'app **Terminal**, tape `cd ` (avec un espace), puis glisse-dépose le dossier `lm-stock-monitor` dans la fenêtre, puis Entrée.

---

## 3️⃣ Installer le programme (une seule fois)

Copie-colle cette commande dans le terminal, puis Entrée. Attends que ça finisse (ça peut prendre 1-2 minutes) :

```
pip install -r requirements.txt && python -m camoufox fetch
```

> Si `pip` ne marche pas, essaie `pip3` à la place.

---

## 🚀 Lancer le programme

À chaque fois que tu veux surveiller le stock, une seule commande :

```
python -m stockmonitor
```

> Si `python` ne marche pas, essaie `python3`.

Ensuite, **tu n'as qu'à répondre aux questions** avec les flèches ⬆️⬇️ du clavier et la touche **Entrée** :

1. **Quelle enseigne ?** → Leroy Merlin, Castorama, ou les deux.
2. **Quelle zone ?** → Île-de-France, Paris 200 km, France entière…
3. **Quel produit ?** → garde celui par défaut (Entrée), ou colle l'adresse d'une autre fiche produit.
4. **Un seul scan ou en boucle ?** → « boucle » revérifie tout seul toutes les 15 / 30 / 60 min.

Et c'est parti : un tableau en direct affiche les magasins et lesquels ont du stock. 🟢

Pour tout arrêter : appuie sur **Ctrl + C**.

---

## ❓ Petits soucis fréquents

- **« pip / python n'est pas reconnu »** → ajoute un `3` : `pip3`, `python3`. Sinon, réinstalle Python en cochant bien « Add Python to PATH » (étape 1).
- **Ça plante au premier lancement** → refais l'étape 3, elle installe tout ce qu'il faut.

C'est tout. Prends soin de toi et reste au frais. ❄️
