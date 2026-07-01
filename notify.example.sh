#!/usr/bin/env bash
# Exemple de hook d'alerte restock, commun à tous les scanners du package
# `stockmonitor` :
#
#   python -m stockmonitor lm    --notify-cmd ./notify.sh   (exporte LM_*)
#   python -m stockmonitor casto  --notify-cmd ./notify.sh   (exporte CASTO_*)
#   python -m stockmonitor all    --notify-cmd ./notify.sh
#
# Variables exportées avant l'appel (préfixe = enseigne) :
#   <PREFIX>_MESSAGE      message déjà formaté (multi-lignes)
#   <PREFIX>_PRODUCT_REF   identifiant produit (réf LM / EAN Casto / ASIN …)
#   <PREFIX>_STORES        JSON des magasins nouvellement en stock
#   CASTO_ONLINE          JSON de la dispo en ligne (Casto)
#
# <PREFIX> ∈ {LM, CASTO, DARTY, AMAZON}.
#
# 1) Copie ce fichier :   cp notify.example.sh notify.sh && chmod +x notify.sh
# 2) Renseigne tes secrets ci-dessous.

# Message commun,quelle que soit l'enseigne qui a déclenché le hook.
MESSAGE="${LM_MESSAGE:-${CASTO_MESSAGE:-${DARTY_MESSAGE:-$AMAZON_MESSAGE}}}"

# --- Option A : Telegram --------------------------------------------------- #
TELEGRAM_BOT_TOKEN="123456:ABC..."     # créé via @BotFather
TELEGRAM_CHAT_ID="123456789"           # ton chat id (via @userinfobot)

if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ "$TELEGRAM_BOT_TOKEN" != "123456:ABC..." ]; then
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
       --data-urlencode "text=${MESSAGE}" >/dev/null
fi

# --- Option B : email (macOS, via mail) ------------------------------------ #
# echo "$MESSAGE" | mail -s "Restock détecté" you@example.com

# --- Option C : notification macOS locale ---------------------------------- #
# osascript -e "display notification \"$MESSAGE\" with title \"Restock\""
