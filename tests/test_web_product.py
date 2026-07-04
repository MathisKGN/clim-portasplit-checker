from __future__ import annotations

from stockmonitor.retailers.web_product import classify_product_page


def test_classify_product_page_detects_anti_bot_block():
    state, status_text, blocked = classify_product_page(
        "<html><title>Just a moment...</title><script src='challenges.cloudflare.com'></script>"
    )

    assert state == "UNKNOWN"
    assert "protection anti-bot" in status_text
    assert blocked is True


def test_classify_product_page_marks_out_before_in_when_signals_conflict():
    state, status_text, blocked = classify_product_page(
        "<main><button>Ajouter au panier</button><p>Produit indisponible</p></main>"
    )

    assert state == "OUT"
    assert status_text == "produit indisponible"
    assert blocked is False


def test_classify_product_page_marks_in_stock_page():
    state, status_text, blocked = classify_product_page(
        "<main><button>Ajouter au panier</button><p>Livraison gratuite</p></main>"
    )

    assert state == "IN"
    assert status_text == "ajouter au panier"
    assert blocked is False


def test_classify_product_page_returns_compact_visible_text_for_unknown_status():
    state, status_text, blocked = classify_product_page(
        "<html><body><script>hidden()</script><main>Statut pas encore lisible</main></body></html>"
    )

    assert state == "UNKNOWN"
    assert status_text == "Statut pas encore lisible"
    assert blocked is False
