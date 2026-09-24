import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from typing import Optional
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
