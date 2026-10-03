"""
inventario_precedente/app.py — "Aggiorna inventario" nella VERSIONE PRECEDENTE (temporanea).

È la pagina online com'era prima della nuova interfaccia: "Sync inventario" con la sua copia
della logica di calcolo (logic.py, logic_v03.py in questa cartella); marchi e ricarichi
restano quelli condivisi in config/.

Il link Streamlit Cloud principale (app.py) per ora mostra già questa pagina. Questo file
serve solo per avviarla da sola:  streamlit run inventario_precedente/app.py

Quando la nuova funzione è sistemata: si toglie il rimando in app.py e questa cartella.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # logic/logic_v03/sync_ui di questa cartella

from pagina import render

render()
