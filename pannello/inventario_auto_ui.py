"""
inventario_auto_ui.py — "Aggiorna l'inventario" in automatico (solo Mac, serve la chiave Shopify).
Niente export da caricare: i prodotti li legge pannello/inventario_sync.py da Shopify, il
listino MCWS è quello del catalogo automatico (o uno scaricato al momento), le giacenze BBR
sono l'ultimo file caricato. Prima un controllo (non cambia niente), poi "Applica su Shopify".
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from pannello import controller as ctl
from pannello.ui_common import go, job_error, num, step, when

FULL, PRICES = "full", "prices"
MODES = {
    FULL: ("Disponibilità, costi e prezzi  (consigliato)",
           "Segna come esauriti i prodotti che i fornitori non hanno più, rimette disponibili "
           "quelli tornati in magazzino e aggiorna costi e prezzi di vendita."),
    PRICES: ("Solo i prezzi",
             "Ricalcola i prezzi di vendita con i ricarichi attuali, senza toccare la "
             "disponibilità. Non servono listini."),
}
STEPS = {
    1: "Preparo i listini dei fornitori",
    2: "Leggo i prodotti dal negozio Shopify",
    3: "Confronto con i listini e i ricarichi",
    4: "Scrivo le modifiche su Shopify",
}


def _started(log: Path | None) -> datetime | None:
    m = re.search(r"inventario_(\d{4}-\d{2}-\d{2})_(\d{6})", log.name) if log else None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H%M%S") if m else None


# ─────────────────────────── Avvio ───────────────────────────────────────────
def _start_check() -> None:
    """Callback di «Controlla»: legge le scelte dal modulo al momento del click."""
    ss = st.session_state
    full = ss.get("inva_mode", FULL) == FULL
    try:
        ctl.start_inventory(prices_only=not full, apply=False,
                            mcws_fresh=full and ss.get("inva_mcws") == "fresh",
                            use_bbr=full and ss.get("inva_bbr", True))
    except Exception as e:
        ss["inva_error"] = str(e)


def _start_apply() -> None:
    """Callback di «Applica»: rifà il lavoro dell'ultimo controllo con gli STESSI listini
    (niente nuovo download) e prodotti Shopify riletti adesso, poi scrive."""
    s = ctl.inventory_summary(ctl.inventory_logfile())
    info = ctl.inventory_info()
    try:
        ctl.start_inventory(prices_only=info.get("prices_only", False), apply=True,
                            mcws=s["mcws_file"], bbr=s["bbr_file"],
                            use_bbr=info.get("use_bbr", True),
                            force=st.session_state.get("inva_force", False))
    except Exception as e:
        st.session_state["inva_error"] = str(e)


# ─────────────────────────── Listini ─────────────────────────────────────────
def _mcws_block(creds: dict, running: bool) -> bool:
    """Scelta del listino MCWS. Ritorna True se c'è un listino utilizzabile."""
    st.markdown("**Listino MCWS**")
    auto = ctl.latest_mcws_stocklist()
    options = (["last"] if auto else []) + (["fresh"] if creds["mcws"] else [])
    if not options:
        st.warning("Non c'è ancora nessun listino MCWS e manca la password di MCWS per scaricarlo.")
        st.button("🔑 Inserisci le password", on_click=go, args=("impostazioni",), key="inva_to_settings")
        return False
    age = (datetime.now() - auto["mtime"]).days if auto else None
    default = "fresh" if "fresh" in options and (age is None or age >= 1) else options[0]
    choice = st.radio(
        "Listino MCWS", options, index=options.index(default), key="inva_mcws",
        label_visibility="collapsed", disabled=running,
        format_func=lambda o: (f"Usa l'ultimo scaricato ({when(auto['mtime'])})" if o == "last"
                               else "Scaricane uno nuovo adesso  (2-3 minuti in più, si apre Chrome)"))
    if choice == "last" and age is not None and age >= 3:
        st.warning(f"Questo listino ha {age} giorni: meglio scaricarne uno nuovo.")
    return True


def _bbr_block(running: bool) -> bool:
    """Giacenze BBR: l'ultimo file caricato viene ricordato. Ritorna True se tutto ok."""
    st.markdown("**Magazzino BBR Models**")
    use_bbr = st.toggle("Considera anche le giacenze **BBR Models**", value=True, key="inva_bbr",
                        disabled=running,
                        help="Se è acceso, i prodotti BBR vengono controllati sulle giacenze BBR "
                             "(disponibilità e costi). Se è spento, li controllo sul listino MCWS.")
    if not use_bbr:
        return True
    up = st.file_uploader("Carica un file BBR nuovo (CSV o Excel)", type=["csv", "xls", "xlsx"],
                          key="inva_bbr_up", disabled=running)
    if up is not None and st.session_state.get("inva_bbr_saved") != up.file_id:
        ctl.save_bbr(up.name, up.getvalue())
        st.session_state["inva_bbr_saved"] = up.file_id
    last = ctl.latest_bbr()
    if not last:
        st.warning("**Manca il file delle giacenze BBR Models**: caricalo qui sopra (basta una "
                   "volta, le prossime volte lo ritrovi qui). Se per ora non ti serve, spegni "
                   "l'interruttore «Considera anche le giacenze BBR Models».")
        return False
    age = (datetime.now() - last["mtime"]).days
    msg = f"Uso le giacenze BBR caricate {when(last['mtime'])}."
    if age >= 3:
        st.warning(f"{msg} Hanno {age} giorni: se ne hai di più recenti caricale qui sopra.")
    else:
        st.caption(f"✔️ {msg} Ricarica un file solo quando ne hai uno più recente.")
    return True


# ─────────────────────────── Risultato ───────────────────────────────────────
def _report(s: dict, applied: bool) -> None:
    path = s["report"]
    if not path or not path.exists():
        return
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except Exception:
        return
    if df.empty:
        return
    from pannello.inventario_ui import TEXT_FORCED_COLUMNS, dataframe_to_excel_bytes
    cols = (["Esito"] if applied else []) + ["Title", "Variant SKU", "Change Log", "Su Shopify"]
    view = df[cols].rename(columns={"Title": "Prodotto", "Variant SKU": "Codice",
                                    "Change Log": "Cosa cambia"})
    st.dataframe(view, use_container_width=True, hide_index=True,
                 column_config={"Su Shopify": st.column_config.LinkColumn(display_text="apri")})
    st.download_button("⬇️ Scarica l'elenco delle modifiche (Excel)",
                       dataframe_to_excel_bytes(df, TEXT_FORCED_COLUMNS),
                       f"{path.stem}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       key="inva_download")


def _result(log: Path) -> None:
    s = ctl.inventory_summary(log)
    info = ctl.inventory_info()
    applied = info.get("apply", False)
    st.markdown(f"**Ultimo lavoro:** {'applicazione su Shopify' if applied else 'controllo'} — "
                f"{when(_started(log))}")
    started = _started(log)
    if started and started.date() < datetime.now().date():
        # Un risultato vecchio sembra un errore di adesso: lo diciamo chiaramente.
        st.info(f"ℹ️ Questo è il risultato dell'ultimo lavoro fatto ({when(started)}), "
                "non di oggi. Per vedere com'è la situazione adesso premi **Controlla** qui sopra.")

    if s["errors"] and not s["report"]:
        job_error(s["errors"], key="inva_err_settings", log=log)
        with st.expander("🔎 Dettaglio tecnico (registro completo)"):
            st.code(ctl.tail_log(log, 400) or "—", language="text")
        return

    if s["mcws_fallback"]:
        st.warning("⚠️ Non sono riuscito a scaricare un listino MCWS nuovo: ho usato l'ultimo già "
                   "scaricato.")
    sources = [f"Listino MCWS: {s['mcws_line']}" if s["mcws_line"] else "",
               f"Giacenze BBR: {s['bbr_line']}" if s["bbr_line"] else ""]
    if any(sources):
        st.caption(" · ".join(x for x in sources if x))

    prices_only = info.get("prices_only", False)
    cols = st.columns(2 if prices_only else 4)
    cols[0].metric("Prodotti controllati", num(s["read"]))
    if prices_only:
        cols[1].metric("Prezzi da cambiare", num(s["prices"]))
    else:
        cols[1].metric("Tornano disponibili", num(s["back"]))
        cols[2].metric("Diventano esauriti", num(s["out"]))
        cols[3].metric("Prezzi cambiati", num(s["prices"]), help=f"Costi cambiati: {num(s['costs'])}")

    if s["too_many"]:
        st.warning(f"⚠️ **{num(s['out'])} prodotti** su {num(s['available'])} disponibili "
                   "diventerebbero esauriti: sono tanti. Forse il listino è incompleto. "
                   "Guarda l'elenco qui sotto prima di applicare.")

    if not applied or s["blocked"]:
        if s["to_update"] == 0:
            st.success("✅ **Non c'è niente da aggiornare**: il negozio è già allineato ai listini.")
        else:
            if s["blocked"]:
                st.error("Non ho applicato niente perché sarebbero diventati esauriti troppi prodotti.")
            else:
                st.info(f"🔍 Controllo fatto: **{num(s['to_update'])} prodotti da aggiornare**. "
                        "Su Shopify non è cambiato niente.")
            force = True
            if s["too_many"]:
                force = st.checkbox("Ho controllato l'elenco: applica lo stesso", key="inva_force")
            st.button(f"✅  Applica queste {num(s['to_update'])} modifiche su Shopify", type="primary",
                      on_click=_start_apply, key="inva_apply", disabled=not force)
            st.caption("Rilegge i prodotti da Shopify e usa gli stessi listini di questo controllo.")
    elif not s["applied_done"]:
        st.success("✅ **Non c'era niente da aggiornare**: il negozio è già allineato ai listini.")
    else:
        st.success(f"✅ **{num(s['applied'])} prodotti aggiornati** su Shopify.")
        if s["apply_errors"]:
            st.error(f"{num(s['apply_errors'])} prodotti non sono stati aggiornati per un errore: "
                     "li vedi nella tabella (colonna Esito). Puoi rilanciare: rifà solo quello che manca.")

    _report(s, applied and s["applied_done"])
    with st.expander("🔎 Dettaglio tecnico (registro completo)"):
        st.code(ctl.tail_log(log, 400) or "—", language="text")


def _progress() -> None:
    running = ctl.inventory_running()

    @st.fragment(run_every=2 if running else None)
    def area():
        log = ctl.inventory_logfile()
        if running and not ctl.inventory_running():
            st.rerun()          # finito: ridisegna tutta la pagina (riattiva i pulsanti)
        if running:
            s = ctl.inventory_summary(log)
            with st.container(border=True):
                st.markdown("### ⏳ Sto lavorando…")
                if s["step"]:
                    st.progress(s["step"] / 4, text=f"Passo {s['step']} di 4: {STEPS[s['step']]}")
                if s["step"] <= 1 and "listino da modelcarswholesale" in ctl.tail_log(log, 20):
                    st.markdown("Si apre una finestra di **Chrome** per scaricare il listino MCWS: "
                                "**non chiuderla**.")
                st.caption("Puoi anche chiudere questa pagina: il lavoro continua lo stesso.")
                st.button("⏹  Interrompi", on_click=ctl.stop_inventory, key="inva_stop")
                with st.expander("🔎 Dettaglio tecnico (registro)"):
                    st.code(ctl.tail_log(log, 80) or "(avvio…)", language="text")
        elif log and Path(log).exists():
            _result(Path(log))

    area()


# ─────────────────────────── Pagina ──────────────────────────────────────────
def render_auto() -> None:
    creds = ctl.credentials_status()
    running = ctl.inventory_running()

    with st.container(border=True):
        st.markdown(
            "**Come funziona**\n"
            "- **Non devi caricare l'export di Shopify**: leggo io i prodotti dal negozio.\n"
            "- Il **listino MCWS** è quello scaricato in automatico (o ne scarico uno nuovo).\n"
            "- Prima **controllo** e ti mostro cosa cambierebbe; poi, se ti va bene, "
            "**applico** le modifiche direttamente su Shopify. Niente file da importare.")

    step(1, "Cosa vuoi aggiornare?")
    mode = st.radio("Cosa vuoi aggiornare?", list(MODES), label_visibility="collapsed",
                    format_func=lambda m: MODES[m][0], captions=[MODES[m][1] for m in MODES],
                    key="inva_mode", disabled=running)

    ready = True
    n = 2
    if mode == FULL:
        step(n, "Listini dei fornitori")
        n += 1
        with st.container(border=True):
            ready = _mcws_block(creds, running)
            st.divider()
            ready = _bbr_block(running) and ready

    step(n, "Controlla, poi applica")
    st.button("🔍  Controlla  (non cambia niente su Shopify)", type="primary",
              on_click=_start_check, key="inva_check", disabled=running or not ready)
    if not ready:
        st.warning("⬆️ Il pulsante **Controlla** si attiva quando i listini qui sopra sono a "
                   "posto: segui il messaggio giallo nel riquadro «Listini dei fornitori».")
    else:
        st.caption("Ti mostro cosa cambierebbe. Poi decidi tu se applicarlo.")

    if "inva_error" in st.session_state:
        st.error(st.session_state.pop("inva_error"))

    if running or ctl.inventory_logfile():
        step(n + 1, "Risultato")
        _progress()
