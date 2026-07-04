# stockmonitor 🌬️

Surveille le stock d'un climatiseur (Leroy Merlin / Castorama) dans les magasins près de chez toi, et te prévient quand il revient en stock.

> Codé avec passion, uniquement à but de recherche et d'information — pour donner un coup de main à celles et ceux qui galèrent à trouver une clim, et surtout aux personnes les plus vulnérables face à la canicule. 🙏

---

## 🐣 Tu ne codes pas ? Tu n'as RIEN d'installé ? Pas de panique.

On part **de zéro** : pas de Python, pas de Homebrew, rien du tout. Tu n'as **rien à comprendre au code**. Suis juste les étapes une par une, une seule fois. Ensuite, une seule commande à retenir.

> Pas besoin de Homebrew, ni de Git, ni de compte GitHub, ni de quoi que ce soit d'autre. Juste ce qui suit.

---

## 1️⃣ Télécharger le projet sur ton ordi

1. En haut de cette page (sur GitHub), clique sur le bouton vert **« Code »**, puis **« Download ZIP »**.
2. Ouvre le fichier `.zip` téléchargé (généralement dans ton dossier **Téléchargements**) pour le décompresser.
3. Tu obtiens un dossier nommé `lm-stock-monitor` (ou `lm-stock-monitor-main`). Déplace-le où tu veux, par ex. sur le **Bureau**, pour le retrouver facilement.

---

## 2️⃣ Installer Python (une seule fois)

Python, c'est le moteur qui fait tourner le programme. **Pas besoin de Homebrew** : on prend l'installateur officiel.

- **Windows** : va sur [python.org/downloads](https://www.python.org/downloads/), clique sur le gros bouton jaune **« Download Python »**, lance le fichier téléchargé, et **⚠️ COCHE bien la case « Add Python to PATH »** en bas de la fenêtre **avant** de cliquer sur **« Install Now »**. Cette case est indispensable, ne l'oublie pas.
- **Mac** : va sur [python.org/downloads](https://www.python.org/downloads/), clique sur **« Download Python »**, ouvre le fichier `.pkg` téléchargé et clique **Continuer / Installer** jusqu'au bout (tu devras taper le mot de passe de ta session).

> Pour vérifier plus tard que c'est bien installé : ouvre le terminal (étape 3) et tape `python --version` (ou `python3 --version`). Si ça affiche un numéro comme `Python 3.12.x`, c'est bon. ✅

---

## 3️⃣ Ouvrir le terminal dans le dossier du projet

Le « terminal », c'est la fenêtre où on tape des commandes.

- **Windows** : ouvre le dossier `lm-stock-monitor` (celui décompressé à l'étape 1), clique dans la **barre d'adresse** tout en haut de la fenêtre, efface ce qu'il y a, tape `cmd` puis Entrée. Une fenêtre noire s'ouvre, déjà placée dans le bon dossier.
- **Mac** : ouvre l'app **Terminal** (cherche « Terminal » avec Spotlight : ⌘ + Espace, tape « terminal », Entrée). Puis tape `cd ` (les 3 lettres c-d puis un espace), et **glisse-dépose le dossier** `lm-stock-monitor` directement dans la fenêtre du Terminal : son chemin s'écrit tout seul. Appuie sur Entrée.

---

## 4️⃣ Installer le programme (une seule fois)

Copie-colle cette commande dans le terminal, puis Entrée. Attends que ça finisse (ça peut prendre 1-2 minutes, c'est normal que ça défile) :

```
python install.py
```

> Si `python` ne marche pas, essaie `python3` :
>
> ```
> python3 install.py
> ```
>
> Le script s'occupe tout seul de créer l'environnement isolé, d'installer les dépendances et de télécharger le navigateur nécessaire.

---

## 🚀 Lancer le programme

À chaque fois que tu veux surveiller le stock, une seule commande :

```
python run.py
```

> Si `python` ne marche pas, essaie `python3 run.py`.

Ensuite, **tu n'as qu'à répondre aux questions** avec les flèches ⬆️⬇️ du clavier et la touche **Entrée** :

1. **Quelle enseigne ?** → Leroy Merlin, Castorama, ou les deux.
2. **Ton code postal ?** → tape ton code postal (5 chiffres, ex. `59000`).
3. **Quel rayon ?** → un nombre de km entre 5 et 700 autour de chez toi. Le programme trouve tout seul les magasins dans ce périmètre et calcule le minimum de points à scanner.
4. **Quel produit ?** → garde celui par défaut (Entrée), ou colle l'adresse d'une autre fiche produit.
5. **Un seul scan ou en boucle ?** → « boucle » revérifie tout seul toutes les 15 / 30 / 60 min.
6. **Alerte Telegram ?** → tu peux garder une alerte existante, configurer Telegram avec le token du bot + ton chat id, ou lancer sans alerte.

Et c'est parti : un tableau en direct affiche les magasins et lesquels ont du stock. 🟢

Si tu configures Telegram, le programme peut envoyer un message de test, puis sauvegarder l'alerte pour les prochains lancements. Les alertes ne sont envoyées que pour les nouveaux restocks, pas à chaque boucle si le même magasin reste disponible.

Pour tout arrêter : appuie sur **Ctrl + C**.

---

## ❓ Petits soucis fréquents

- **« pip / python n'est pas reconnu »** → ajoute un `3` : `pip3`, `python3`. Sinon, réinstalle Python en cochant bien « Add Python to PATH » (étape 2), puis **ferme et rouvre** le terminal.
- **Ça plante au premier lancement** → refais l'étape 4, elle installe tout ce qu'il faut.
- **Tu ne retrouves pas le dossier dans le terminal** → recommence l'étape 3 (le glisser-déposer sur Mac, ou le `cmd` dans la barre d'adresse sur Windows).

C'est tout. Prends soin de toi et reste au frais. ❄️
