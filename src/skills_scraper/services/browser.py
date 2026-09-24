import os
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from skills_scraper.config import WEBDRIVER_BROWSER, WEBDRIVER_OPTIONS_HEADLESS, WEBDRIVER_PROFILE_FOLDER_NAME

# Chromium flags shared by Chrome and Edge: quiet, no first-run noise, and
# not announcing itself as automation (the site is happier that way).
BROWSER_ARGUMENTS = [
    "--disable-extensions",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-client-side-phishing-detection",
    "--disable-default-apps",
    "--disable-hang-monitor",
    "--disable-popup-blocking",
    "--disable-prompt-on-repost",
    "--disable-renderer-backgrounding",
    "--disable-sync",
    "--disable-translate",
    "--metrics-recording-only",
    "--no-first-run",
    "--safebrowsing-disable-auto-update",
    "--password-store=basic",
    "--use-mock-keychain",
    "--disable-blink-features=AutomationControlled",
    "log-level=3",
]

BROWSERS = {
    "chrome": (ChromeOptions, ChromeService, webdriver.Chrome),
    "edge": (EdgeOptions, EdgeService, webdriver.Edge),
}


def launch_browser(profile_folder=WEBDRIVER_PROFILE_FOLDER_NAME,
                   headless: bool = WEBDRIVER_OPTIONS_HEADLESS,
                   browser: str = WEBDRIVER_BROWSER):
    """
    Launch a Selenium WebDriver (Chrome or Edge) on a persistent profile.

    The profile folder keeps the signed-in session between runs, so the
    sign-in prompt shows up once, not every time. Pass profile_folder=None
    for a throwaway profile. Defaults come from config.yaml.
    """
    try:
        options_class, service_class, driver_class = BROWSERS[browser.lower()]
    except KeyError:
        raise ValueError(f"Unsupported browser: {browser} (chrome or edge)")

    options = options_class()
    for argument in BROWSER_ARGUMENTS:
        options.add_argument(argument)
    options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])

    # The "new" headless mode is the one that behaves like a real window.
    if headless:
        options.add_argument("--headless=new")

    if profile_folder:
        options.add_argument(f"user-data-dir={os.path.abspath(profile_folder)}")

    return driver_class(service=service_class(), options=options)


def ensure_authenticated(driver, url: str, what: str = "") -> bool:
    """
    If the page redirected to sign-in, ask the user to sign in (in the visible
    browser window) and retry until the page loads or the user gives up.
    Returns True when the requested page is showing.
    """
    if not driver:
        return False

    while "sign_in" in driver.current_url:
        suffix = f" for {what}" if what else ""
        print(f"\n\033[93m[!] Authentication required{suffix}.\033[0m")
        print("Please sign in to the browser window if you haven't.")
        try:
            input("Press Enter after you have signed in and the page is loaded... ")
        except (KeyboardInterrupt, EOFError):
            print("\n\033[91mAborted authentication.\033[0m")
            return False
        driver.get(url)

        if "sign_in" in driver.current_url:
            print("\n\033[91m[!] Still on the sign-in page. Finish signing in before pressing Enter.\033[0m")
    return True


def open_page(driver, url: str, what: str = "") -> bool:
    """
    Navigate the browser to url, dealing with the sign-in redirect.
    Returns False when there is no browser or the user aborted the sign-in.
    """
    if not driver:
        print(f"(open_page) A signed-in browser is required{' for ' + what if what else ''}.")
        return False
    driver.get(url)
    return ensure_authenticated(driver, url, what)


def get_page(driver, url: str, what: str = "") -> BeautifulSoup | None:
    """
    open_page(), then hand back the rendered page as BeautifulSoup.
    """
    if not open_page(driver, url, what):
        return None
    return BeautifulSoup(driver.page_source, "html.parser")
