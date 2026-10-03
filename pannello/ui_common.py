"""
ui_common.py — pezzi condivisi dell'interfaccia: navigazione tra le pagine,
stile, intestazioni, passi numerati e formattazione di date/numeri in italiano.
"""

from __future__ import annotations

import platform
from datetime import datetime

import streamlit as st

# Le funzioni che usano Chrome, launchd e le credenziali girano solo sul Mac.
# Su Streamlit Cloud (Linux) resta disponibile solo "Aggiorna l'inventario".
IS_MAC = platform.system() == "Darwin"

PAGES = ("home", "inventario", "newsletter", "catalogo", "impostazioni")
MAC_ONLY = {"newsletter", "catalogo", "impostazioni"}

MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]

CSS = """
<style>
  .block-container { max-width: 1100px; padding-top: 4rem; }
  [data-testid="stSidebar"], [data-testid="collapsedControl"] { display: none; }
  .vr-brand { font-size: .95rem; font-weight: 700; letter-spacing: .08em;
              text-transform: uppercase; opacity: .55; margin-bottom: .2rem; }
  .vr-title { font-size: 2.1rem; font-weight: 800; line-height: 1.2; margin: 0 0 .4rem 0; }
  .vr-sub   { font-size: 1.08rem; opacity: .75; margin-bottom: 1.2rem; }
  .vr-step  { display: flex; align-items: center; gap: .6rem;
              font-size: 1.2rem; font-weight: 700; margin: 1.6rem 0 .5rem 0; }
  .vr-step .n { display: inline-flex; align-items: center; justify-content: center;
                width: 1.9rem; height: 1.9rem; border-radius: 50%;
                background: #3B82F6; color: #fff; font-size: 1rem; flex: none; }
  .vr-card-icon  { font-size: 2.4rem; line-height: 1; margin-bottom: .4rem; }
  .vr-card-title { font-size: 1.35rem; font-weight: 800; margin-bottom: .3rem; }
  .vr-card-text  { font-size: 1rem; opacity: .8; min-height: 3.2rem; }
  .vr-card-need  { font-size: .9rem; opacity: .6; margin: .5rem 0 .8rem 0; }
  .vr-small-title { font-size: 1.05rem; font-weight: 700; margin-bottom: .2rem; }
  .vr-muted { opacity: .65; font-size: .92rem; }
</style>
"""


# ─────────────────────────── Navigazione ─────────────────────────────────────
def current_page() -> str:
    """Pagina corrente: dalla sessione, oppure dall'indirizzo (?pagina=…) al ricaricamento."""
    if "page" not in st.session_state:
        st.session_state["page"] = st.query_params.get("pagina", "home")
    page = st.session_state["page"]
    if page not in PAGES or (page in MAC_ONLY and not IS_MAC):
        page = "home"
    return page


def go(page: str) -> None:
    """Callback dei pulsanti: cambia pagina (Streamlit poi ridisegna da solo)."""
    st.session_state["page"] = page
    if page == "home":
        st.query_params.clear()
    else:
        st.query_params["pagina"] = page


def back_button() -> None:
    st.button("← Torna all'inizio", on_click=go, args=("home",), key="back_home")


# ─────────────────────────── Elementi grafici ────────────────────────────────
def apply_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", show_back: bool = True) -> None:
    if show_back:
        back_button()
    st.markdown('<div class="vr-brand">Vroomi</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="vr-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="vr-sub">{subtitle}</div>', unsafe_allow_html=True)


def step(n: int, title: str) -> None:
    st.markdown(f'<div class="vr-step"><span class="n">{n}</span>{title}</div>',
                unsafe_allow_html=True)


# ─────────────────────────── Formattazione ───────────────────────────────────
def when(dt: datetime | None) -> str:
    """'oggi alle 07:12', 'ieri alle 07:12', '28 set alle 07:12'."""
    if not dt:
        return "—"
    days = (datetime.now().date() - dt.date()).days
    hour = dt.strftime("%H:%M")
    if days == 0:
        return f"oggi alle {hour}"
    if days == 1:
        return f"ieri alle {hour}"
    year = f" {dt.year}" if dt.year != datetime.now().year else ""
    return f"{dt.day} {MESI[dt.month - 1]}{year} alle {hour}"


def num(n: int) -> str:
    """1234 → '1.234'."""
    return f"{n:,}".replace(",", ".")


def job_error(errors: list, key: str) -> None:
    """Errore di un lavoro in background, spiegato a parole. Se il problema sono le
    password (MCWS rifiuta il login, Shopify rifiuta la chiave) porta alle Impostazioni."""
    text = "\n\n".join(errors[:3])
    low = text.lower()
    if any(w in low for w in ("login rifiutato", "login non riuscito", "vuoti")):
        st.error("🔑 **modelcarswholesale.com (MCWS) non ha accettato nome utente o password** "
                 "salvati su questo Mac.")
        st.markdown("Apri **⚙️ Impostazioni**, riscrivi il nome utente e la password che usi per "
                    "entrare su modelcarswholesale.com, premi **Salva** e riprova.")
        st.button("🔑 Reinserisci le password MCWS", type="primary", key=key,
                  on_click=go, args=("impostazioni",))
        with st.expander("Messaggio originale"):
            st.text(text)
        return
    st.error("Il lavoro si è fermato per un errore:\n\n" + text)
    if "credenziali" in low or "client_credentials" in low or "shopify" in low:
        st.button("🔑 Controlla le password", key=key, on_click=go, args=("impostazioni",))
