"""
mcws_downloader.py
Login su modelcarswholesale.com con undetected-chromedriver (bypassa Cloudflare),
poi scarica il CSV inventario riutilizzando i cookies di sessione.
Credenziali SOLO da variabili d'ambiente:
  os.environ['MCWS_USERNAME']
  os.environ['MCWS_PASSWORD']

Uso:
  python downloader/mcws_downloader.py
"""

import os
import time
from datetime import datetime
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

LOGIN_URL = "https://www.modelcarswholesale.com/it/login"
DOWNLOAD_URL = "https://www.modelcarswholesale.com/downloadStocklistCsv"
LOGOUT_URL = "https://www.modelcarswholesale.com/logout"


def get_output_file() -> Path:
    ts = os.environ.get("RUN_TIMESTAMP", datetime.now().strftime("%Y-%m-%d_%H%M"))
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    return out_dir / f"mcws_inventory_{ts}.csv"


# Chrome scarica nella directory temporanea del downloader (non output/)
# così wait_for_download trova il file prima del rename
DOWNLOAD_DIR = Path(__file__).parent.resolve()


def wait_for_download(directory: Path, timeout: int = 60) -> Path | None:
    """Attende che compaia un file .csv scaricato nella directory (non in output/)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Solo file nella directory root, non nelle sottocartelle
        files = [f for f in directory.glob("*.csv")
                 if not f.name.endswith(".crdownload")]
        if files:
            return max(files, key=lambda f: f.stat().st_mtime)
        time.sleep(1)
    return None


def main():
    username = os.environ["MCWS_USERNAME"]
    password = os.environ["MCWS_PASSWORD"]
    output_file = get_output_file()

    # Configura Chrome: download automatico nella directory del downloader
    options = uc.ChromeOptions()
    prefs = {
        "download.default_directory": str(DOWNLOAD_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    print("Avvio Chrome (undetected)...")
    driver = uc.Chrome(headless=False, use_subprocess=True, options=options)

    try:
        # Login
        print(f"Navigazione verso {LOGIN_URL}")
        driver.get(LOGIN_URL)

        # Attesa Cloudflare challenge (max 60s)
        for i in range(30):
            time.sleep(2)
            title = driver.title
            if "Just a moment" not in title and "Ci siamo quasi" not in title:
                print(f"Challenge superato ({(i+1)*2}s) — titolo: {title}")
                break
            if (i + 1) % 5 == 0:
                print(f"  Attesa CF... {(i+1)*2}s")
        else:
            raise SystemExit("ERRORE: Cloudflare challenge non risolto dopo 60s")

        # Compila form di login
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located((By.ID, "username")))
        driver.find_element(By.ID, "username").send_keys(username)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button[type=submit], input[type=submit]").click()
        time.sleep(3)
        print(f"Post-login URL: {driver.current_url}")

        if "/login" in driver.current_url or "/signin" in driver.current_url:
            raise SystemExit("ERRORE: login fallito — controlla le credenziali")

        # Download CSV direttamente con Chrome (bypassa CF)
        print(f"Download da {DOWNLOAD_URL}...")
        # Rimuovi eventuali CSV vecchi nella dir root per non confonderli
        for old in DOWNLOAD_DIR.glob("*.csv"):
            old.unlink()

        driver.get(DOWNLOAD_URL)
        time.sleep(2)  # breve pausa per avviare il download

        # Attendi completamento download
        downloaded = wait_for_download(DOWNLOAD_DIR, timeout=60)
        if downloaded:
            downloaded.rename(output_file)
            print(f"Salvato: {output_file} ({output_file.stat().st_size} bytes)")
        else:
            # Fallback: il contenuto potrebbe essere inline (non file)
            page_src = driver.page_source
            if "<!DOCTYPE" not in page_src[:100]:
                output_file.write_text(page_src, encoding="utf-8")
                print(f"Salvato (inline): {output_file}")
            else:
                raise SystemExit("ERRORE: download non completato")

        # Logout
        driver.get(LOGOUT_URL)
        print(f"Logout: {driver.current_url}")

    finally:
        driver.quit()

    # Statistiche CSV
    lines = output_file.read_text(encoding="utf-8", errors="replace").splitlines()
    print(f"\nRighe nel CSV: {len(lines) - 1}")
    print(f"File: {output_file}")


if __name__ == "__main__":
    main()
