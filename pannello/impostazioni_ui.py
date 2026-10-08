"""
impostazioni_ui.py — pagina "Impostazioni": password (credenziali.env), marchi e ricarichi,
versione del programma (aggiornamenti).
"""

import streamlit as st

from pannello import controller as ctl
from pannello.aggiornamenti_ui import version_box
from pannello.ui_common import page_header, step


def _ok(flag: bool) -> str:
    return "🟢 inserita" if flag else "🔴 manca"


def _count_lines(path) -> int:
    try:
        return sum(1 for l in path.read_text(encoding="utf-8").splitlines()
                   if l.strip() and not l.upper().startswith(("#", "TRADEMARK", "COSTO SOTTO")))
    except OSError:
        return 0


def render_impostazioni():
    page_header("⚙️ Impostazioni", "Password di accesso, marchi che vendi e ricarichi.")
    creds = ctl.credentials_status()
    if st.session_state.pop("creds_saved", False):
        st.success("✅ Password salvate.")

    # ── Password ─────────────────────────────────────────────────────────────
    step(1, "Password di accesso")
    st.caption("Restano solo su questo Mac (nel file credenziali.env). "
               "Te le fornisce Matteo. Lascia vuoto un campo per non cambiarlo.")
    with st.form("credenziali", border=True):
        st.markdown(f"**modelcarswholesale.com (MCWS)** — {_ok(creds['mcws'])}  \n"
                    "Serve per le newsletter e per il catalogo automatico.")
        user = st.text_input("Nome utente MCWS", value=ctl.env_value_set("MCWS_USERNAME"))
        pwd = st.text_input("Password MCWS", type="password",
                            placeholder="•••••• (già inserita)" if creds["mcws"] else "")
        st.divider()
        st.markdown(f"**Shopify** — {_ok(creds['shopify'])}  \n"
                    "Serve per creare i prodotti dalle newsletter e per scrivere le note.")
        secret = st.text_input("Chiave Shopify (Client secret)", type="password",
                               placeholder="•••••• (già inserita)" if creds["shopify"] else "")
        if st.form_submit_button("💾 Salva", type="primary"):
            values = {"MCWS_USERNAME": user.strip(), "MCWS_PASSWORD": pwd,
                      "SHOPIFY_CLIENT_SECRET": secret.strip()}
            try:
                ctl.save_credentials(values)
                st.session_state["creds_saved"] = True
                st.rerun()
            except ValueError:
                st.error("Una password contiene un apostrofo ( ' ): non posso salvarla da qui. "
                         "Apri il file credenziali.env (pulsante qui sotto) e scrivila a mano.")
    if creds["env_exists"]:
        st.button("Apri il file delle password con TextEdit", key="open_env",
                  on_click=ctl.open_in_mac, args=(ctl.env_file(), True))

    # ── Marchi e ricarichi ───────────────────────────────────────────────────
    step(2, "Marchi e ricarichi")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        with st.container(border=True):
            st.markdown(f"**Marchi che vendi** — {_count_lines(ctl.TRADEMARKS_FILE)}")
            st.caption("Un marchio per riga (es. AUTOART). Solo questi vengono scaricati, "
                       "aggiornati e creati dalle newsletter.")
            st.button("✏️ Modifica (si apre TextEdit)", key="open_tm", use_container_width=True,
                      on_click=ctl.open_in_mac, args=(ctl.TRADEMARKS_FILE, True))
    with c2:
        with st.container(border=True):
            st.markdown(f"**Ricarichi per marchio** — {_count_lines(ctl.MARKUP_FILE)}")
            st.caption("Marchio, poi il moltiplicatore sul costo (es. Autoart 1,50). "
                       "Un marchio senza ricarico viene saltato dalle newsletter.")
            st.button("✏️ Modifica (si apre TextEdit)", key="open_mk", use_container_width=True,
                      on_click=ctl.open_in_mac, args=(ctl.MARKUP_FILE, True))
    st.caption("Dopo aver modificato un file, salvalo in TextEdit: il pannello usa subito "
               "i nuovi valori.")

    # ── Versione del programma ───────────────────────────────────────────────
    step(3, "Versione del programma")
    version_box()
