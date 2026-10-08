"""
aggiornamenti_ui.py — scheda «Programma» in cima alla pagina iniziale (versione, «Aggiorna
adesso», «Controlla adesso») e avviso «È disponibile un aggiornamento» in cima alle altre
pagine (logica in aggiornamenti.py).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import streamlit as st

from pannello import aggiornamenti as agg
from pannello.ui_common import when


def _start() -> None:
    try:
        agg.start_update()
    except RuntimeError as e:
        st.session_state["update_error"] = str(e)


def _update_button(s: dict, key: str) -> None:
    busy = agg.busy_reason()
    st.button("⬆️ Aggiorna adesso", type="primary", key=key, on_click=_start,
              disabled=bool(busy))
    if busy:
        st.caption(f"Aspetta che finisca: {busy}.")
    else:
        st.caption("Il pannello si chiude e si riapre da solo (circa un minuto). "
                   "Password, dati e risultati non vengono toccati.")


def _news(s: dict) -> None:
    if s["novita"]:
        with st.expander("Cosa cambia"):
            st.markdown("\n".join(f"- {n}" for n in s["novita"]))


def _in_progress(s: dict) -> None:
    st.info("⏳ **Aggiornamento del programma in corso…** Tra circa un minuto il pannello "
            "si chiude e si riapre da solo in una nuova scheda del browser: questa scheda "
            "poi la puoi chiudere. Non spegnere il Mac.")


@st.fragment(run_every=timedelta(hours=1))
def update_banner() -> None:
    """In cima a ogni pagina. Il controllo su GitHub avviene al massimo una volta al
    giorno (aggiornamenti.check); il riquadro si ridisegna da solo ogni ora, così
    l'avviso compare anche se il pannello resta aperto per giorni."""
    if agg.is_dev_copy():
        return
    s = agg.status()
    if s["in_corso"]:
        _in_progress(s)
        return
    if err := st.session_state.pop("update_error", None):
        st.error(err)
    if s["errore_aggiornamento"] and s["serve"]:
        st.error(f"⚠️ **L'ultimo aggiornamento del programma non è riuscito** "
                 f"({s['errore_aggiornamento']}). Il pannello è rimasto com'era: "
                 "controlla la connessione e riprova.")
    aggiornato = s["aggiornato_il"]
    if (not s["serve"] and aggiornato and datetime.now() - aggiornato < timedelta(minutes=15)
            and not st.session_state.get("update_done_shown")):
        st.session_state["update_done_shown"] = True
        st.toast("✅ Programma aggiornato all'ultima versione.")
    if not s["serve"]:
        return
    if st.session_state.get("update_toast") != s["remoto"]:
        st.session_state["update_toast"] = s["remoto"]
        st.toast("🆕 È disponibile un aggiornamento del programma.")
    with st.container(border=True):
        pub = f" (pubblicato {when(s['pubblicata'])})" if s["pubblicata"] else ""
        st.warning(f"🆕 **È disponibile un aggiornamento del programma**{pub}. "
                   "Conviene installarlo: contiene correzioni e novità.")
        _news(s)
        _update_button(s, "update_banner_btn")


def home_card() -> None:
    """Pagina iniziale, in alto: scheda «Programma» SEMPRE visibile, con la versione e i
    pulsanti «Aggiorna adesso» e «Controlla adesso» (prima era nascosta nelle Impostazioni)."""
    force = st.session_state.pop("update_check_now", False)
    with st.container(border=True):
        if agg.is_dev_copy():
            st.markdown("🔄 **Programma** — copia scaricata con git: si aggiorna con `git pull`.")
            return
        s = agg.status(force=force)
        if s["in_corso"]:
            _in_progress(s)
            return
        if err := st.session_state.pop("update_error", None):
            st.error(err)
        if s["errore_aggiornamento"] and s["serve"]:
            st.error(f"⚠️ L'ultimo aggiornamento non è riuscito ({s['errore_aggiornamento']}): "
                     "il pannello è rimasto com'era. Controlla la connessione e riprova.")
        done = s["aggiornato_il"]
        if (not s["serve"] and done and datetime.now() - done < timedelta(minutes=15)
                and not st.session_state.get("update_done_shown")):
            st.session_state["update_done_shown"] = True
            st.toast("✅ Programma aggiornato all'ultima versione.")
        installed =s["locale"][:7] if s["locale"] else "sconosciuta"
        checked = (f"controllato {when(s['controllato'])}" if s["controllato"]
                   else "non ancora controllato")
        if s["serve"]:
            pub = f" (pubblicata {when(s['pubblicata'])})" if s["pubblicata"] else ""
            head = f"🆕 **È disponibile una versione nuova del programma**{pub}."
        elif s["remoto"]:
            head = "🟢 **Il programma è aggiornato** all'ultima versione."
        else:
            head = "🔄 **Programma**: non riesco a controllare gli aggiornamenti (connessione?)."
        c1, c2, c3 = st.columns([5, 2, 2], vertical_alignment="center")
        with c1:
            st.markdown(head)
            st.caption(f"Versione `{installed}` · {checked}. "
                       "Si aggiorna anche da solo a ogni avvio del pannello.")
        busy = agg.busy_reason()
        c2.button("⬆️ Aggiorna adesso", type="primary" if s["serve"] else "secondary",
                  key="update_home_btn", on_click=_start, disabled=bool(busy),
                  use_container_width=True,
                  help=("Scarica l'ultima versione, poi il pannello si chiude e si riapre da "
                        "solo (circa un minuto). Password e dati non vengono toccati."
                        if s["serve"] else "Sei già all'ultima versione: la reinstalla."))
        c3.button("🔄 Controlla adesso", key="update_check_btn", use_container_width=True,
                  on_click=lambda: st.session_state.update(update_check_now=True))
        if busy:
            st.caption(f"Per aggiornare aspetta che finisca: {busy}.")
        if s["serve"]:
            _news(s)
