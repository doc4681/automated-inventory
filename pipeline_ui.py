"""
pipeline_ui.py — Tab "Catalogo carmodel → Shopify" del pannello.
Lancia la pipeline (scraper → downloader → merger → [Shopify]) in background,
mostra il log in diretta, gestisce gli interruttori Shopify e scheduling.
"""

import time
import streamlit as st

import controller as ctl


def render_pipeline_tab():
    st.markdown("### 🚗 Catalogo carmodel → Shopify")
    st.caption("Scarica i dati da carmodel.com + il listino MCWS, li unisce, e "
               "(se attivo) scrive le note su Shopify. Gira in locale su questo Mac.")

    creds = ctl.credentials_status()

    # ── Credenziali ────────────────────────────────────────────────────────
    if not creds["env_exists"] or not creds["mcws"]:
        st.error(
            f"⚠️ Credenziali mancanti. Crea/completa il file **{creds['env_file']}** con:\n\n"
            "```bash\n"
            'export MCWS_USERNAME="tua@email"\n'
            'export MCWS_PASSWORD="password"\n'
            "```\n"
            "Per l'arricchimento Shopify aggiungi anche `SHOPIFY_CLIENT_ID`, "
            "`SHOPIFY_CLIENT_SECRET`, `SHOPIFY_STORE_DOMAIN`."
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Credenziali MCWS", "✅" if creds["mcws"] else "❌ mancanti")
    c2.metric("Credenziali Shopify", "✅" if creds["shopify"] else "❌ mancanti")
    res = ctl.latest_result()
    c3.metric("Ultimo risultato", f"{res['rows']} righe" if res else "—",
              help=f"{res['name']} · {res['mtime']}" if res else "Nessun file ancora")

    st.divider()

    # ── Interruttore arricchimento Shopify ───────────────────────────────────
    colA, colB = st.columns([2, 1])
    with colA:
        enable = st.toggle(
            "🛍️ Arricchimento Shopify (scrive `custom.notes` dopo il merge)",
            value=creds["enable_shopify"],
            disabled=not creds["shopify"],
            help="Se attivo, dopo il merge aggiorna le note dei prodotti sullo store. "
                 "Richiede le credenziali Shopify.",
        )
        if enable != creds["enable_shopify"]:
            ctl.set_enable_shopify(enable)
            st.toast(f"Arricchimento Shopify {'ATTIVATO' if enable else 'DISATTIVATO'}")
            st.rerun()

    st.divider()

    # ── Avvio / stato pipeline ───────────────────────────────────────────────
    running = ctl.is_running()
    st.markdown("#### ▶️ Esecuzione pipeline")

    bcol1, bcol2, bcol3 = st.columns([1.4, 1, 2])
    with bcol1:
        if st.button("🚀 Avvia pipeline completa", type="primary",
                     use_container_width=True, disabled=running or not creds["mcws"]):
            try:
                ctl.start_pipeline()
                st.toast("Pipeline avviata in background.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(str(e))
    with bcol2:
        if st.button("⏹️ Ferma", use_container_width=True, disabled=not running):
            ctl.stop_pipeline()
            st.toast("Richiesta di stop inviata.")
            time.sleep(1)
            st.rerun()
    with bcol3:
        if running:
            st.warning("● In esecuzione… (puoi chiudere il browser, continua da sola)")
        else:
            st.success("● Pronta / nessuna run in corso")

    # ── Log in diretta ────────────────────────────────────────────────────────
    logf = ctl.current_logfile()
    if logf:
        st.markdown("#### 📜 Log")
        auto = st.checkbox("🔄 Aggiorna automaticamente", value=running)
        st.code(ctl.tail_log(logf, 300) or "(in avvio…)", language="text")
        if auto and running:
            time.sleep(2)
            st.rerun()

    st.divider()

    # ── Ultimo risultato + download ──────────────────────────────────────────
    st.markdown("#### 📄 Ultimo risultato")
    if res:
        st.write(f"**{res['name']}** — {res['rows']} righe — {res['mtime']}")
        st.download_button("⬇️ Scarica CSV", data=res["path"].read_bytes(),
                           file_name=res["name"], mime="text/csv")
    else:
        st.info("Ancora nessun risultato. Avvia la pipeline.")

    st.divider()

    # ── Scheduling automatico ────────────────────────────────────────────────
    st.markdown("#### ⏰ Esecuzione automatica (ogni 2 giorni, 07:00)")
    status = ctl.schedule_status()
    badge = {"attivo": "🟢 Attivo", "sospeso": "🟠 Sospeso", "assente": "⚪️ Non installato"}[status]
    s1, s2, s3 = st.columns([1.2, 1, 1])
    s1.write(f"Stato: **{badge}**")
    with s2:
        if st.button("Attiva", use_container_width=True, disabled=(status == "attivo")):
            ok, msg = ctl.schedule_enable()
            st.toast("Pianificazione attivata." if ok else f"Errore: {msg}")
            st.rerun()
    with s3:
        if st.button("Sospendi", use_container_width=True, disabled=(status != "attivo")):
            ok, msg = ctl.schedule_disable()
            st.toast("Pianificazione sospesa." if ok else f"Errore: {msg}")
            st.rerun()
    st.caption("Quando è attiva, il Mac deve essere acceso e sbloccato alle 07:00. "
               "La sospensione è persistente (sopravvive ai riavvii).")
