import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
import time

def main():
    print("Testing Selenium configuration...")
    try:
        options = webdriver.ChromeOptions()
        # Enable headless mode to avoid popping up windows unless needed
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        driver = webdriver.Chrome(options=options)
        print("Chrome WebDriver initialized successfully!")
        
        url = "https://www.whoscored.com/matches/1953854/live/international-fifa-world-cup-2026"
        print(f"Navigating to: {url}")
        driver.get(url)
        time.sleep(5)
        print("Page title:", driver.title)
        
        # Check if layout-wrapper script exists
        scripts = driver.find_elements(By.XPATH, '//*[@id="layout-wrapper"]/script[1]')
        if scripts:
            print("Found script element!")
            content = scripts[0].get_attribute('innerHTML')
            print("Length of script content:", len(content))
            if "matchId" in content:
                print("Found matchId inside script tag!")
            else:
                print("matchId NOT found in script tag.")
        else:
            print("Could not find script element.")
            
        driver.quit()
    except Exception as e:
        print("Error occurred:", str(e))

if __name__ == '__main__':
    main()
