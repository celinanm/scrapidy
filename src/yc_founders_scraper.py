#!/usr/bin/env python3
"""
YC Founders Scraper with Google Drive Upload
Scrapes founder information from Y Combinator's founders page and uploads to Google Drive
"""

import time
import csv
import re
import os
import json
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.service_account import Credentials
from datetime import datetime


class YCFoundersScraper:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self.driver = None
        self.founders_data = []
        
    def setup_driver(self):
        """Initialize Chrome WebDriver with options"""
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Set Chrome binary path - comment out for default system detection
        # chrome_options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        
        try:
            # Try to use ChromeDriverManager first
            driver_path = ChromeDriverManager().install()
            print(f"Downloaded driver to: {driver_path}")
            
            # Check if the driver is actually executable
            import os
            if os.path.exists(driver_path):
                # Make sure it's executable
                os.chmod(driver_path, 0o755)
                service = Service(driver_path)
                self.driver = webdriver.Chrome(service=service, options=chrome_options)
            else:
                raise Exception("Driver not found after download")
                
        except Exception as e:
            print(f"ChromeDriverManager failed: {e}")
            print("Trying to use system Chrome driver...")
            # Fallback to system chromedriver if available
            try:
                self.driver = webdriver.Chrome(options=chrome_options)
            except Exception as e2:
                print(f"System Chrome driver also failed: {e2}")
                raise Exception("Could not initialize Chrome WebDriver. Please ensure Chrome and chromedriver are installed.")
        
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
    def scroll_to_load_all_founders(self):
        """Load all founders by clicking 'Show more' and scrolling"""
        print("Loading all founders...")
        
        # First try to click the "Show 1,000+ founders" button
        try:
            show_button = self.driver.find_element(By.CSS_SELECTOR, "._showResults_i9oky_169 button")
            if show_button and show_button.is_displayed():
                print("Clicking 'Show founders' button...")
                show_button.click()
                time.sleep(5)  # Wait for results to load
        except Exception as e:
            print(f"Could not find or click show button, continuing with scroll: {e}")
        
        # Now scroll to load any additional content
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        founders_loaded = 0
        no_change_count = 0
        
        while True:
            # Scroll down to bottom
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            # Wait for new content to load
            time.sleep(3)
            
            # Calculate new scroll height and compare with last scroll height
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            
            # Count current founders to show progress
            current_founders = len(self.driver.find_elements(By.CSS_SELECTOR, "a._company_i9oky_355"))
            if current_founders > founders_loaded:
                print(f"Loaded {current_founders} founders...")
                founders_loaded = current_founders
                no_change_count = 0
            else:
                no_change_count += 1
            
            if new_height == last_height:
                no_change_count += 1
                if no_change_count >= 3:  # No changes for 3 attempts
                    break
                # Try scrolling a bit more
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight + 1000);")
                time.sleep(2)
            else:
                no_change_count = 0
                    
            last_height = new_height
            
        print(f"Finished loading. Total founders found: {founders_loaded}")
        
    def extract_founder_overview_data(self) -> List[Dict]:
        """Extract founder data from the main founders page"""
        print("Extracting founder overview data...")
        
        # Use the specific selector we found for founder cards
        founder_selector = "a._company_i9oky_355"
        founders_elements = self.driver.find_elements(By.CSS_SELECTOR, founder_selector)
        
        print(f"Found {len(founders_elements)} founders using selector: {founder_selector}")
        
        if not founders_elements:
            print("No founders found with primary selector, trying fallback...")
            founders_elements = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/founders/']")
            print(f"Found {len(founders_elements)} founders with fallback selector")
        
        founders_data = []
        
        # Remove limit for full scraping, add back [:10] for testing
        for i, element in enumerate(founders_elements):
            try:
                # Extract href (profile URL)
                href = element.get_attribute('href')
                
                # Extract text content
                text_content = element.text.strip()
                
                print(f"Processing founder {i+1}: {text_content[:50]}...")
                
                # Parse the text content to extract founder info
                founder_info = self.parse_founder_text(text_content)
                founder_info['profile_url'] = href
                
                founders_data.append(founder_info)
                
            except Exception as e:
                print(f"Error processing founder element {i+1}: {str(e)}")
                continue
                
        return founders_data
    
    def parse_founder_text(self, text: str) -> Dict:
        """Parse founder text to extract structured data from YC directory format"""
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        founder_info = {
            'first_name': '',
            'last_name': '',
            'current_role': '',
            'current_company': '',
            'batch': '',
            'linkedin_url': ''
        }
        
        if not lines:
            return founder_info
            
        # First line is the founder's name
        if lines:
            name_parts = lines[0].split()
            if len(name_parts) >= 2:
                founder_info['first_name'] = name_parts[0]
                founder_info['last_name'] = ' '.join(name_parts[1:])
            elif len(name_parts) == 1:
                founder_info['first_name'] = name_parts[0]
        
        # Look for role and company info
        for line in lines[1:]:
            # Check for "Role at Company" pattern (bolded text in original)
            if ' at ' in line and any(indicator in line for indicator in ['CEO', 'CTO', 'Founder', 'Co-founder', 'President', 'VP', 'Chief', 'Director']):
                parts = line.split(' at ', 1)
                if len(parts) == 2:
                    founder_info['current_role'] = parts[0].strip()
                    founder_info['current_company'] = parts[1].strip()
                continue
            
            # Check for batch info (format like "S21", "W22", "F24", "X25")
            batch_match = re.search(r'[SWFX]\d{2}', line)
            if batch_match and not founder_info['batch']:
                founder_info['batch'] = batch_match.group()
                continue
            
            # Look for other role patterns if we haven't found one yet
            role_indicators = ['CEO', 'CTO', 'Founder', 'Co-founder', 'President', 'VP', 'Chief', 'Director']
            if not founder_info['current_role'] and any(indicator in line for indicator in role_indicators):
                founder_info['current_role'] = line
                continue
        
        # Clean up extracted data
        if founder_info['current_role']:
            # Remove any "**" markdown formatting that might be present
            founder_info['current_role'] = founder_info['current_role'].replace('**', '').strip()
        
        if founder_info['current_company']:
            founder_info['current_company'] = founder_info['current_company'].replace('**', '').strip()
        
        return founder_info
    
    def extract_linkedin_url(self, profile_url: str) -> Optional[str]:
        """Navigate to founder's profile page and extract personal LinkedIn URL"""
        if not profile_url:
            return None
            
        try:
            print(f"Navigating to profile: {profile_url}")
            self.driver.get(profile_url)
            
            # Wait for page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Find all LinkedIn links on the page
            linkedin_elements = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='linkedin.com']")
            
            personal_linkedin_urls = []
            company_linkedin_urls = []
            
            for element in linkedin_elements:
                try:
                    linkedin_url = element.get_attribute('href')
                    if not linkedin_url or 'linkedin.com' not in linkedin_url:
                        continue
                    
                    # Categorize LinkedIn URLs
                    if '/in/' in linkedin_url:
                        # Personal LinkedIn profile (linkedin.com/in/username)
                        personal_linkedin_urls.append(linkedin_url)
                        print(f"Found personal LinkedIn: {linkedin_url}")
                    elif '/company/' in linkedin_url:
                        # Company LinkedIn page (linkedin.com/company/companyname)
                        company_linkedin_urls.append(linkedin_url)
                        print(f"Found company LinkedIn: {linkedin_url}")
                    elif '/pub/' in linkedin_url:
                        # Alternative personal LinkedIn format
                        personal_linkedin_urls.append(linkedin_url)
                        print(f"Found personal LinkedIn (pub): {linkedin_url}")
                        
                except Exception as e:
                    print(f"Error processing LinkedIn element: {e}")
                    continue
            
            # Prioritize personal LinkedIn URLs
            if personal_linkedin_urls:
                # Try to find the most relevant personal LinkedIn URL
                # Extract founder's name from the profile URL for matching
                founder_name_from_url = ""
                if "/founders/" in profile_url:
                    # Extract name from URL like "/founders/38677-andy-fang"
                    url_parts = profile_url.split("/founders/")[-1].split("-")
                    if len(url_parts) > 1:
                        founder_name_from_url = "-".join(url_parts[1:]).lower()
                
                # Try to find LinkedIn URL that matches the founder's name
                best_match = None
                for linkedin_url in personal_linkedin_urls:
                    linkedin_username = linkedin_url.split("/in/")[-1].split("/")[0].lower()
                    
                    # Check if LinkedIn username contains parts of founder's name
                    if founder_name_from_url and any(name_part in linkedin_username for name_part in founder_name_from_url.split("-") if len(name_part) > 2):
                        best_match = linkedin_url
                        print(f"Found name match for {founder_name_from_url}: {linkedin_url}")
                        break
                
                # Use the best match, or fall back to the first one
                selected_url = best_match or personal_linkedin_urls[0]
                print(f"Selected personal LinkedIn URL: {selected_url}")
                return selected_url
            elif company_linkedin_urls:
                # Fallback to company LinkedIn if no personal profile found
                selected_url = company_linkedin_urls[0]
                print(f"No personal LinkedIn found, using company LinkedIn: {selected_url}")
                return selected_url
            else:
                print("No LinkedIn URLs found on this page")
                return None
            
        except TimeoutException:
            print(f"Timeout loading profile page: {profile_url}")
            return None
        except Exception as e:
            print(f"Error extracting LinkedIn URL: {str(e)}")
            return None
    
    def setup_google_drive_service(self):
        """Set up Google Drive API service using service account credentials"""
        try:
            # Try to get credentials from environment variable (for GitHub Actions)
            credentials_json = os.getenv('GOOGLE_SERVICE_ACCOUNT_KEY')
            
            if credentials_json:
                # Parse JSON credentials from environment variable
                credentials_info = json.loads(credentials_json)
                credentials = Credentials.from_service_account_info(
                    credentials_info,
                    scopes=['https://www.googleapis.com/auth/drive.file']
                )
            else:
                # Fallback to local credentials file (for local development)
                credentials = Credentials.from_service_account_file(
                    'service-account-key.json',
                    scopes=['https://www.googleapis.com/auth/drive.file']
                )
            
            service = build('drive', 'v3', credentials=credentials)
            return service
            
        except Exception as e:
            print(f"Error setting up Google Drive service: {str(e)}")
            return None
    
    def upload_to_google_drive(self, filename: str, folder_id: str = None):
        """Upload CSV file to Google Drive"""
        try:
            service = self.setup_google_drive_service()
            if not service:
                print("Failed to set up Google Drive service")
                return False
            
            # Create timestamp for unique filename
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            drive_filename = f"yc_founders_{timestamp}.csv"
            
            # File metadata
            file_metadata = {
                'name': drive_filename
            }
            
            # If folder_id is provided, set the parent folder
            if folder_id:
                file_metadata['parents'] = [folder_id]
            
            # Upload file
            media = MediaFileUpload(filename, mimetype='text/csv')
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,webViewLink'
            ).execute()
            
            print(f"✅ File uploaded to Google Drive successfully!")
            print(f"📁 File name: {file.get('name')}")
            print(f"🔗 File ID: {file.get('id')}")
            print(f"🌐 View link: {file.get('webViewLink')}")
            
            return True
            
        except Exception as e:
            print(f"❌ Error uploading to Google Drive: {str(e)}")
            return False
    
    def scrape_founders(self) -> List[Dict]:
        """Main scraping method"""
        try:
            print("Starting YC Founders scraper...")
            self.setup_driver()
            
            # Navigate to founders page
            print("Navigating to YC founders page...")
            self.driver.get("https://www.ycombinator.com/companies/founders")
            
            # Wait for page to load
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Scroll to load all founders
            self.scroll_to_load_all_founders()
            
            # Extract founder overview data
            founders_data = self.extract_founder_overview_data()
            
            # Extract LinkedIn URLs for each founder
            print("Extracting LinkedIn URLs...")
            for i, founder in enumerate(founders_data):
                print(f"Processing founder {i+1}/{len(founders_data)}: {founder.get('first_name', '')} {founder.get('last_name', '')}")
                
                if founder.get('profile_url'):
                    linkedin_url = self.extract_linkedin_url(founder['profile_url'])
                    founder['linkedin_url'] = linkedin_url or ''
                
                # Add small delay between requests
                time.sleep(2)
            
            return founders_data
            
        except Exception as e:
            print(f"Error during scraping: {str(e)}")
            return []
        finally:
            if self.driver:
                self.driver.quit()
    
    def save_to_csv(self, data: List[Dict], filename: str = "yc_founders.csv"):
        """Save founder data to CSV file"""
        if not data:
            print("No data to save")
            return
            
        # Define CSV columns
        columns = ['first_name', 'last_name', 'current_role', 'current_company', 'batch', 'linkedin_url', 'profile_url']
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=columns)
            writer.writeheader()
            
            for founder in data:
                # Ensure all required columns exist
                row = {col: founder.get(col, '') for col in columns}
                writer.writerow(row)
        
        print(f"Data saved to {filename}")
        print(f"Total founders saved: {len(data)}")


def main():
    """Main execution function"""
    scraper = YCFoundersScraper(headless=False)  # Set to True to run headless
    
    # Scrape founders data
    founders_data = scraper.scrape_founders()
    
    # Save to CSV
    if founders_data:
        filename = "yc_founders.csv"
        scraper.save_to_csv(founders_data, filename)
        
        # Upload to Google Drive
        print("\n🚀 Uploading to Google Drive...")
        
        # Optional: Specify a folder ID where you want to upload the file
        # Get this from your Google Drive URL: https://drive.google.com/drive/folders/YOUR_FOLDER_ID
        folder_id = os.getenv('GOOGLE_DRIVE_FOLDER_ID')  # Set this as environment variable
        
        upload_success = scraper.upload_to_google_drive(filename, folder_id)
        
        if upload_success:
            print("✅ Complete! CSV has been uploaded to Google Drive.")
        else:
            print("❌ Upload failed, but CSV file is saved locally.")
        
        # Print summary
        print("\nScraping Summary:")
        print(f"Total founders scraped: {len(founders_data)}")
        
        with_linkedin = sum(1 for f in founders_data if f.get('linkedin_url'))
        print(f"Founders with LinkedIn URLs: {with_linkedin}")
        
        # Show first few entries
        print("\nFirst 3 entries:")
        for i, founder in enumerate(founders_data[:3]):
            print(f"{i+1}. {founder.get('first_name', '')} {founder.get('last_name', '')}")
            print(f"   Role: {founder.get('current_role', 'N/A')}")
            print(f"   Company: {founder.get('current_company', 'N/A')}")
            print(f"   Batch: {founder.get('batch', 'N/A')}")
            print(f"   LinkedIn: {founder.get('linkedin_url', 'N/A')}")
            print()
    else:
        print("No founders data was scraped. Please check the page structure and selectors.")


if __name__ == "__main__":
    main()
