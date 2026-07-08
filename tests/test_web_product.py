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


def test_classify_product_page_marks_optimea_in_stock_product_from_woocommerce_meta():
    state, status_text, blocked = classify_product_page(
        """
        <html>
          <head>
            <script src="https://www.google.com/recaptcha/api.js"></script>
            <meta property="product:availability" content="in stock" />
          </head>
          <body>
            <h1>Climatiseur monobloc fixe réversible OAC-250-RE2</h1>
          </body>
        </html>
        """,
        "https://www.optimea.fr/product/climatiseur-monobloc-fixe-reversible-oac-250-re2-2410-w-sans-unite-exterieure-2/",
    )

    assert state == "IN"
    assert status_text == "in stock"
    assert blocked is False


def test_classify_product_page_marks_optimea_out_of_stock_product_from_woocommerce_meta():
    state, status_text, blocked = classify_product_page(
        """
        <html>
          <head>
            <meta property="product:availability" content="out of stock" />
          </head>
          <body>
            <h1>Climatiseur Split Mobile MIDEA</h1>
            <button>Ajouter au panier</button>
          </body>
        </html>
        """,
        "https://www.optimea.fr/product/climatiseur-split-mobile-midea/",
    )

    assert state == "OUT"
    assert status_text == "out of stock"
    assert blocked is False


def test_classify_product_page_returns_compact_visible_text_for_unknown_status():
    state, status_text, blocked = classify_product_page(
        "<html><body><script>hidden()</script><main>Statut pas encore lisible</main></body></html>"
    )

    assert state == "UNKNOWN"
    assert status_text == "Statut pas encore lisible"
    assert blocked is False
