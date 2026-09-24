import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from typing import Optional
from bs4 import BeautifulSoup
from skills_scraper.config import WEBDRIVER_PROFILE_FOLDER_NAME


# Launch a browser with the specified profile and headless mode
def launch_browser(profile_folder: Optional[str] = None,
                   headless=True,
                   browser="chrome" or None):
    """
    Launches a Selenium WebDriver instance with the specified browser and profile path.
    A default browser profile will be set to ./webdriver_profiles/ if no profile path is provided.
    """

    # Launch Chrome browser
    if browser.lower() == "chrome":
        options = Options()
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-client-side-phishing-detection")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-first-run")
        options.add_argument("--safebrowsing-disable-auto-update")
        options.add_argument("--enable-automation")
        options.add_argument("--password-store=basic")
        options.add_argument("--use-mock-keychain")
        options.add_argument('log-level=3')
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])

        # Set the headless mode, default is True
        if headless:
            options.add_argument("--headless")

        # Set the profile folder, default is None
        if profile_folder:
            webdriver_profile_path = os.path.join(os.getcwd(), profile_folder)
            options.add_argument(f"user-data-dir={webdriver_profile_path}")

        service = ChromeService()
        driver = webdriver.Chrome(service=service, options=options)

    # Launch Edge browser
    elif browser.lower() == "edge":
        options = EdgeOptions()
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-client-side-phishing-detection")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-sync")
        options.add_argument("--disable-translate")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-first-run")
        options.add_argument("--safebrowsing-disable-auto-update")
        options.add_argument("--enable-automation")
        options.add_argument("--password-store=basic")
        options.add_argument("--use-mock-keychain")
        options.add_argument('log-level=3')
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])

        if headless:
            options.add_argument("--headless")

        if profile_folder:
            webdriver_profile_path = os.path.join(os.getcwd(), profile_folder)
            options.add_argument(f"user-data-dir={webdriver_profile_path}")

        service = EdgeService()
        driver = webdriver.Edge(service=service, options=options)

    else:
        raise ValueError("Unsupported browser: {}".format(browser))

    return driver


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
