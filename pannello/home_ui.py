"""
home_ui.py — pagina iniziale: "Cosa vuoi fare?".
Due scelte principali (inventario, newsletter) e, sotto, catalogo automatico e impostazioni.
"""

import streamlit as st

from pannello import controller as ctl
from pannello.ui_common import IS_MAC, go, num, page_header, when


def _big_card(icon, title, text, need, button, page, key, disabled_reason=""):
    with st.container(border=True):
        st.markdown(f'<div class="vr-card-icon">{icon}</div>'
                    f'<div class="vr-card-title">{title}</div>'
                    f'<div class="vr-card-text">{text}</div>'
                    f'<div class="vr-card-need">{need}</div>', unsafe_allow_html=True)
        st.button(button, type="primary", use_container_width=True, key=key,
                  on_click=go, args=(page,), disabled=bool(disabled_reason))
        if disabled_reason:
            st.caption(disabled_reason)


def _small_card(title, status, button, page, key):
    with st.container(border=True):
        st.markdown(f'<div class="vr-small-title">{title}</div>'
                    f'<div class="vr-muted">{status}</div>', unsafe_allow_html=True)
        st.button(button, use_container_width=True, key=key, on_click=go, args=(page,))


def _catalog_status() -> str:
    if ctl.is_running():
        s = ctl.pipeline_summary(ctl.current_logfile())
        step = s["step"] if s else 0
        return f"🔵 Aggiornamento in corso{f' (passo {step} di 4)' if step else ''}…"
    res = ctl.latest_result()
    auto = ctl.schedule_status() == "attivo" and not ctl.schedule_other_folder()
    last = f"Ultimo: {when(res['when'])} · {num(res['rows'])} prodotti" if res else "Mai aggiornato"
    return f"{last}<br>Aggiornamento automatico: {'🟢 acceso' if auto else '⚪️ spento'}"


def render_home():
    page_header("Cosa vuoi fare?", "Scegli una delle due attività qui sotto.", show_back=False)

    creds = ctl.credentials_status() if IS_MAC else None
    if IS_MAC and not creds["mcws"]:
        with st.container(border=True):
            st.warning("**Manca la password di MCWS** (modelcarswholesale.com): senza, non "
                       "funzionano le newsletter e il catalogo automatico. Basta inserirla una volta.")
            st.button("🔑 Inserisci le password", type="primary", on_click=go,
                      args=("impostazioni",), key="home_to_settings")

    if IS_MAC and ctl.newsletter_running():
        st.info("🔵 La creazione dei prodotti da newsletter è in corso. "
                "Apri **Crea prodotti dalle newsletter** per vedere a che punto è.")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        _big_card(
            "📦", "Aggiorna l'inventario",
            "Aggiorna <b>disponibilità, costi e prezzi</b> dei prodotti che sono già nel "
            "negozio Shopify, confrontandoli con i listini dei fornitori.",
            ("Non serve caricare niente: legge i prodotti da Shopify.<br>Prima controlli, "
             "poi applichi le modifiche con un click." if creds and creds["shopify"] else
             "Ti serve: l'export dei prodotti da Shopify.<br>Alla fine scarichi un file da "
             "importare su Shopify."),
            "Aggiorna l'inventario  →", "inventario", "card_inventario")
    with c2:
        _big_card(
            "🆕", "Crea prodotti dalle newsletter",
            "Crea su Shopify le <b>schede dei modelli nuovi</b> annunciati nelle newsletter "
            "di MCWS. Vengono create come bozze, non visibili ai clienti.",
            "Ti serve: il numero della newsletter (oppure tutte le recenti).<br>"
            "I prodotti che hai già vengono saltati.",
            "Crea prodotti dalle newsletter  →", "newsletter", "card_newsletter",
            disabled_reason="" if IS_MAC else "Disponibile solo nel pannello sul Mac.")

    if not IS_MAC:
        st.caption("☁️ Questa è la versione online: qui puoi solo aggiornare l'inventario. "
                   "Le altre funzioni si usano dal pannello sul Mac "
                   "(doppio click su *AVVIA PANNELLO.command*).")
        return

    st.write("")
    st.markdown("##### Altro")
    s1, s2 = st.columns(2, gap="large")
    with s1:
        _small_card("🔁 Catalogo fornitori (automatico)", _catalog_status(),
                    "Apri", "catalogo", "card_catalogo")
    with s2:
        ok = creds["mcws"] and creds["shopify"]
        _small_card("⚙️ Impostazioni",
                    ("🟢 Password inserite" if ok else "🟠 Mancano alcune password")
                    + "<br>Marchi, ricarichi e password",
                    "Apri", "impostazioni", "card_impostazioni")
