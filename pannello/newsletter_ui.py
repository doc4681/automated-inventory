"""
newsletter_ui.py — pagina "Crea prodotti dalle newsletter".
Usa lo stesso programma dei 3 script in Vroomi-Newsletter/ (run.py), lanciato in
background: prima un controllo (non crea nulla), poi la creazione delle bozze su Shopify.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from pannello import controller as ctl
from pannello.ui_common import go, job_error, num, page_header, step, when

STATUS_LABELS = {
    "DA-CREARE": "🆕 Da creare",
    "DRY-RUN": "🆕 Da creare (non verificato su Shopify)",
    "ESISTE": "✔️ Già nel negozio",
    "CREATO": "✅ Creato come bozza",
    "SALTATO: NON DISPONIBILE": "⏭️ Saltato: non disponibile (etichetta azzurra)",
    "SALTATO: SENZA PREZZO": "⏭️ Saltato: senza prezzo",
    "SALTATO: MARCHIO SENZA RICARICO": "⏭️ Saltato: marchio non valido o senza ricarico",
}


def _started(log: Path | None) -> datetime | None:
    m = re.search(r"newsletter_(\d{4}-\d{2}-\d{2})_(\d{6})", log.name) if log else None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H%M%S") if m else None


def _last_line(log: Path | None) -> str:
    lines = [l.strip() for l in ctl.tail_log(log, 30).splitlines() if l.strip()]
    return lines[-1][:140] if lines else ""


def _ids_from_form() -> str:
    if st.session_state.get("nl_scope", "some") == "all":
        return ""
    return ",".join(re.findall(r"\d+", st.session_state.get("nl_ids") or ""))


def _start(apply: bool, ids: str | None = None) -> None:
    """Callback dei pulsanti. ids=None → li legge dal modulo al momento del click
    (gli args dei pulsanti sono fissati prima che l'ultima modifica arrivi)."""
    if ids is None:
        ids = _ids_from_form()
        if not ids and st.session_state.get("nl_scope", "some") == "some":
            st.session_state["nl_error"] = ("Scrivi il numero della newsletter oppure scegli "
                                            "«Tutte le newsletter recenti».")
            return
    try:
        ctl.start_newsletter(ids, apply=apply)
    except Exception as e:
        st.session_state["nl_error"] = str(e)


def _start_from_check(ids: str, pending_file: str) -> None:
    """«Ora crea queste N bozze»: usa i prodotti trovati dal controllo appena fatto,
    senza riaprire MCWS (niente Chrome, niente login). Senza il file (controllo fatto
    con una versione vecchia) rifà tutto come prima."""
    try:
        ctl.start_newsletter(ids, apply=True, from_check=pending_file)
    except Exception as e:
        st.session_state["nl_error"] = str(e)


def _report_table(path: Path | None) -> None:
    if not path or not path.exists():
        return
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return
    if df.empty:
        return
    df["Stato"] = df["status"].map(lambda s: STATUS_LABELS.get(s, f"❌ {s}"))
    view = df[["Stato", "sku", "title", "brand", "price", "admin_url"]].rename(columns={
        "sku": "SKU", "title": "Prodotto", "brand": "Newsletter", "price": "Prezzo €",
        "admin_url": "Su Shopify"})
    st.dataframe(view, use_container_width=True, hide_index=True,
                 column_config={"Su Shopify": st.column_config.LinkColumn(display_text="apri")})


def _result(log: Path) -> None:
    """Riepilogo dell'ultimo lavoro concluso."""
    s = ctl.newsletter_summary(log)
    info = ctl.newsletter_info()
    text = ctl.tail_log(log, 100000)
    apply = info.get("apply", "[DRY-RUN]" not in text)
    ids = info.get("ids", "")
    what = f"newsletter {ids.replace(',', ', ')}" if ids else "tutte le newsletter recenti"

    st.markdown(f"**Ultimo lavoro:** {'creazione bozze' if apply else 'controllo'} di "
                f"{what} — {when(_started(log))}")

    if s["none_found"]:
        st.warning("Non ho trovato newsletter da usare.")
        if s["skipped"]:
            st.markdown(f"Scartate: {s['skipped']}")
            st.caption("«manca markup» = il marchio non ha un ricarico: aggiungilo nel file dei "
                       "ricarichi (Impostazioni). «non in Valid_Trademarks» = non è tra i marchi che vendi.")
    elif s["errors"] and not (s["created"] or s["existing"] or s["to_create"]):
        job_error(s["errors"], key="nl_err_settings", log=log)
    elif apply:
        st.success(f"✅ **{num(s['created'])} bozze create** su Shopify. "
                   f"{num(s['existing'])} prodotti erano già nel negozio e sono stati saltati.")
        st.caption("Le trovi su Shopify → Prodotti, filtro «Bozza». Controllale e pubblicale "
                   "quando sei pronto.")
    else:
        st.info(f"🔍 Controllo fatto: **{num(s['to_create'])} prodotti nuovi** da creare, "
                f"{num(s['existing'])} già nel negozio. Non è stato creato niente.")
        if s["to_create"]:
            st.button(f"✅  Ora crea queste {num(s['to_create'])} bozze su Shopify", type="primary",
                      on_click=_start_from_check, args=(ids, s["pending_file"]),
                      key="nl_apply_after_check",
                      disabled=not ctl.credentials_status()["shopify"])

    if s["create_errors"]:
        st.error(f"{num(s['create_errors'])} prodotti non sono stati creati per un errore: "
                 "li vedi nella tabella qui sotto.")
    if s["no_price"]:
        st.caption(f"{num(s['no_price'])} prodotti senza prezzo nella newsletter sono stati saltati.")
    if s["not_available"]:
        with st.expander(f"⏭️ {num(len(s['not_available']))} prodotti saltati perché non "
                         "disponibili (etichetta azzurra, non «Disponibile»)"):
            st.text("\n".join(s["not_available"]))
    if s["no_label"]:
        st.caption(f"⚠️ Per {num(s['no_label'])} prodotti non ho trovato l'etichetta di "
                   "disponibilità: li ho trattati come disponibili (dettaglio nel registro).")

    for t in s["tallies"]:
        st.caption(f"📋 {t}")
    _report_table(s["report"])
    with st.expander("🔎 Dettaglio tecnico (registro completo)"):
        st.code(ctl.tail_log(log, 400) or "—", language="text")


def _progress() -> None:
    running = ctl.newsletter_running()

    @st.fragment(run_every=2 if running else None)
    def area():
        log = ctl.newsletter_logfile()
        if ctl.newsletter_running() != running:
            # Lavoro finito, oppure appena partito da un pulsante qui dentro («Applica» /
            # «Crea le bozze»): il riquadro ricorda ancora lo stato vecchio, quindi
            # ridisegna tutta la pagina (avanzamento, pulsanti, risultato).
            st.rerun()
        if running:
            with st.container(border=True):
                st.markdown("### ⏳ Sto lavorando…")
                if ctl.newsletter_info().get("from_check"):
                    st.markdown("Creo su Shopify le bozze trovate dal controllo (non serve "
                                "Chrome). Puoi anche chiudere questa pagina: il lavoro "
                                "continua lo stesso.")
                else:
                    st.markdown("Si apre una finestra di **Chrome** per entrare su MCWS: "
                                "**non chiuderla**. Puoi anche chiudere questa pagina: il "
                                "lavoro continua lo stesso.")
                last = _last_line(log)
                if last:
                    st.caption(f"Adesso: {last}")
                st.button("⏹  Interrompi", on_click=ctl.stop_newsletter, key="nl_stop")
                with st.expander("🔎 Dettaglio tecnico (registro)"):
                    st.code(ctl.tail_log(log, 80) or "(avvio…)", language="text")
        elif log and Path(log).exists():
            _result(Path(log))

    area()


def render_newsletter():
    page_header("🆕 Crea prodotti dalle newsletter",
                "Crea su Shopify le schede dei modelli nuovi annunciati nelle newsletter di "
                "modelcarswholesale.com (MCWS).")

    with st.container(border=True):
        st.markdown(
            "**Come funziona**\n"
            "- Legge le newsletter di MCWS (es. *24-09-2026 - BURAGO*).\n"
            "- Tiene solo i **marchi che vendi** e che hanno un **ricarico** impostato.\n"
            "- Crea le schede su Shopify come **bozze**: i clienti non le vedono finché non le "
            "pubblichi tu.\n"
            "- I prodotti che sono **già nel negozio vengono saltati**: puoi rifarlo senza rischi.")

    creds = ctl.credentials_status()
    running = ctl.newsletter_running()

    # ── 1. Quali newsletter ──────────────────────────────────────────────────
    step(1, "Quali newsletter?")
    scope = st.radio("Quali newsletter?", ["some", "all"], label_visibility="collapsed",
                     format_func=lambda o: ("Una o più newsletter precise" if o == "some"
                                            else "Tutte le newsletter recenti  (ci vuole di più)"),
                     key="nl_scope", disabled=running)
    ids = ""
    if scope == "some":
        raw = st.text_input(
            "Numero della newsletter", placeholder="es. 15538", key="nl_ids", disabled=running,
            help="È il numero alla fine del link della newsletter: "
                 "modelcarswholesale.com/it/newsletter/15538 → 15538. "
                 "Per più newsletter separale con una virgola: 15538, 15540")
        ids = _ids_from_form()
        if raw and not ids:
            st.warning("Scrivi solo il numero, ad esempio 15538.")

    # ── 2. Controlla e crea ──────────────────────────────────────────────────
    step(2, "Controlla, poi crea")
    if not creds["mcws"]:
        st.warning("Mancano nome utente e password di MCWS.")
        st.button("🔑 Inserisci le password", on_click=go, args=("impostazioni",), key="nl_to_settings")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.button("🔍  Controlla  (non crea niente)", type="primary", use_container_width=True,
                  on_click=_start, args=(False,), key="nl_check",
                  disabled=running or not creds["mcws"])
        st.caption("Ti mostra quali prodotti verrebbero creati. Fallo sempre per primo.")
    with c2:
        st.button("✅  Crea le bozze su Shopify", use_container_width=True,
                  on_click=_start, args=(True,), key="nl_apply",
                  disabled=running or not (creds["mcws"] and creds["shopify"]))
        st.caption("Crea davvero le schede (come bozze)." if creds["shopify"] else
                   "Serve la chiave Shopify: inseriscila nelle Impostazioni.")

    if "nl_error" in st.session_state:
        st.error(st.session_state.pop("nl_error"))

    # ── 3. Risultato ─────────────────────────────────────────────────────────
    if running or ctl.newsletter_logfile():
        step(3, "Risultato")
        _progress()
