"""
catalogo_ui.py — pagina "Catalogo fornitori (automatico)".
È la pipeline pipeline/run.sh (carmodel.com + listino MCWS → file unico), che parte
da sola ogni 2 giorni alle 07:00 oppure a mano da qui.
"""

import streamlit as st

from pannello import controller as ctl
from pannello.ui_common import go, num, page_header, step, when


def _start():
    try:
        ctl.start_pipeline()
    except Exception as e:
        st.session_state["cat_error"] = str(e)


def _toggle_schedule():
    on = st.session_state["cat_auto"]
    ok, msg = ctl.schedule_enable() if on else ctl.schedule_disable()
    if not ok:
        st.session_state["cat_auto"] = not on      # l'interruttore torna com'era
        st.session_state["cat_error"] =("Non sono riuscito a cambiare l'aggiornamento automatico."
                                         + (f" ({msg})" if msg else ""))


def _toggle_shopify():
    ctl.set_enable_shopify(st.session_state["cat_shopify"])


def _last_run_box(s: dict) -> None:
    if not s["finished"]:
        st.warning(f"⚠️ L'ultimo aggiornamento ({when(s['started'])}) si è interrotto prima "
                   "della fine. Il catalogo precedente non è stato toccato.")
    elif not s["problems"] and s["merged"] > 0:
        st.success(f"✅ L'ultimo aggiornamento ({when(s['started'])}) è andato bene: "
                   f"{num(s['merged'])} prodotti.")
    else:
        st.warning(f"⚠️ L'ultimo aggiornamento ({when(s['started'])}) ha avuto dei problemi. "
                   "Il catalogo precedente non è stato toccato.")
        for p in s["problems"][:5]:
            st.markdown(f"- {p}")
        st.caption("Spesso basta riprovare: i siti a volte bloccano la sessione per qualche ora. "
                   "Se dice «login rifiutato», aggiorna la password MCWS nelle Impostazioni.")


def _progress() -> None:
    running = ctl.is_running()

    @st.fragment(run_every=3 if running else None)
    def area():
        if running and not ctl.is_running():
            st.rerun()          # finito: ridisegna tutta la pagina
        log = ctl.current_logfile()
        s = ctl.pipeline_summary(log)
        if running:
            with st.container(border=True):
                stp = s["step"] if s else 0
                label = ctl.PIPELINE_STEPS.get(stp, "Preparo…")
                st.markdown("### ⏳ Aggiornamento in corso")
                st.progress(max(stp - 1, 0) / 4 + 0.05,
                            text=f"Passo {max(stp, 1)} di 4 — {label}")
                st.markdown("Si apre una finestra di **Chrome**: **non chiuderla**. Il Mac deve "
                            "restare acceso. Puoi chiudere questa pagina: il lavoro continua.")
                st.button("⏹  Interrompi", on_click=ctl.stop_pipeline, key="cat_stop")
                with st.expander("🔎 Dettaglio tecnico (registro)"):
                    st.code(ctl.tail_log(log, 120) or "(avvio…)", language="text")
        elif s:
            _last_run_box(s)
            with st.expander("🔎 Dettaglio tecnico dell'ultimo aggiornamento (registro)"):
                st.code(ctl.tail_log(log, 300) or "—", language="text")

    area()


def render_catalogo():
    page_header("🔁 Catalogo fornitori",
                "Scarica i prodotti dei tuoi marchi da carmodel.com (foto, descrizioni, note) e "
                "il listino di MCWS, e crea un unico file con i prodotti presenti su entrambi.")
    st.caption("Il listino MCWS scaricato qui viene usato anche da «Aggiorna l'inventario».")

    creds = ctl.credentials_status()
    running = ctl.is_running()

    if "cat_error" in st.session_state:
        st.error(st.session_state.pop("cat_error"))

    # ── Il file ──────────────────────────────────────────────────────────────
    step(1, "Il catalogo")
    res = ctl.latest_result()
    with st.container(border=True):
        if res:
            st.markdown(f"**{num(res['rows'])} prodotti** — aggiornato {when(res['when'])}")
            b1, b2, _ = st.columns([1.2, 1, 1.3])
            b1.download_button("⬇️ Scarica il catalogo (CSV)", data=res["path"].read_bytes(),
                               file_name=res["name"], mime="text/csv", type="primary",
                               use_container_width=True)
            b2.button("📂 Apri la cartella", use_container_width=True, key="cat_open",
                      on_click=ctl.open_in_mac, args=(ctl.RESULT_DIR,))
        else:
            st.markdown("Non c'è ancora nessun catalogo: premi **Aggiorna adesso** qui sotto.")

    # ── Aggiornamento ────────────────────────────────────────────────────────
    step(2, "Aggiornamento")
    with st.container(border=True):
        st.toggle("**Aggiorna da solo** ogni 2 giorni alle 7:00",
                  value=ctl.schedule_status() == "attivo", key="cat_auto",
                  on_change=_toggle_schedule)
        st.caption("Se a quell'ora il Mac è in stop parte appena si risveglia; se è spento "
                   "salta alla volta dopo. A fine lavoro arriva una notifica sul Mac.")
        st.divider()
        if not creds["mcws"]:
            st.warning("Mancano nome utente e password di MCWS.")
            st.button("🔑 Inserisci le password", on_click=go, args=("impostazioni",),
                      key="cat_to_settings")
        st.button("▶  Aggiorna adesso", type="primary", on_click=_start, key="cat_go",
                  disabled=running or not creds["mcws"])
        st.caption("Ci vogliono circa 25 minuti. Se qualcosa va storto, il catalogo "
                   "precedente resta com'era.")

    _progress()

    # ── Opzioni ──────────────────────────────────────────────────────────────
    with st.expander("⚙️ Opzioni avanzate"):
        st.toggle("Scrivi anche le **note** dei prodotti su Shopify",
                  value=creds["enable_shopify"], key="cat_shopify", on_change=_toggle_shopify,
                  disabled=not creds["shopify"])
        st.caption("Aggiunge la nota del catalogo (es. «LIMITED 300 ITEMS») ai prodotti del "
                   "negozio che non ce l'hanno. Non cancella e non sovrascrive mai le note "
                   "già presenti." + ("" if creds["shopify"] else
                                      " Serve la chiave Shopify (Impostazioni)."))
