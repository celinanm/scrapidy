#!/usr/bin/env python3
"""
YC Founders Scraper Runner
Wrapper script to run YC scraper from the organized structure
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from yc_founders_scraper import YCFoundersScraper

def main():
    """Run the YC Founders scraper"""
    scraper = YCFoundersScraper(headless=False)
    data = scraper.scrape_founders()
    scraper.save_to_csv(data)

if __name__ == "__main__":
    main()