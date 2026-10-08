"""
aggiornamenti_ui.py — avviso «È disponibile un aggiornamento» in cima a ogni pagina del
pannello e riquadro «Versione del programma» nelle Impostazioni (logica in aggiornamenti.py).
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


def version_box() -> None:
    """Impostazioni → Versione del programma: versione installata, ultimo controllo,
    «Controlla adesso»."""
    if agg.is_dev_copy():
        st.caption("Questa cartella è una copia git: si aggiorna con  git pull.")
        return
    force = st.session_state.pop("update_check_now", False)
    s = agg.status(force=force)
    with st.container(border=True):
        installed = s["locale"][:7] if s["locale"] else "sconosciuta"
        st.markdown(f"**Versione installata:** `{installed}`"
                    + (f" (ramo `{s['ramo']}`)" if s["ramo"] != "main" else ""))
        if s["in_corso"]:
            _in_progress(s)
            return
        if s["serve"]:
            st.warning("🆕 C'è una versione più recente.")
            _news(s)
            _update_button(s, "update_settings_btn")
        elif s["remoto"]:
            st.success("🟢 È l'ultima versione.")
        checked = f"Ultimo controllo: {when(s['controllato'])}" if s["controllato"] else \
            "Non ancora controllato"
        st.caption(f"{checked}. Il pannello controlla da solo una volta al giorno.")
        if s["errore_controllo"]:
            st.caption(f"⚠️ L'ultimo controllo non è riuscito (connessione?): "
                       f"{s['errore_controllo'][:160]}")
        st.button("🔄 Controlla adesso", key="update_check_btn",
                  on_click=lambda: st.session_state.update(update_check_now=True))
