import requests
import json
import pandas as pd
import time
from google.colab import files
import re

# Constants
API_KEY = 'YOUR_API_KEY'  # Replace with your actual API key
API_URL = 'https://chromeuxreport.googleapis.com/v1/records:queryRecord'
DOMAIN = "YOUR_DOMAIN"

# Function to get data from CrUX API for a specific URL
def get_crux_data(url):
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    data = {
        'url': url
    }
    response = requests.post(f"{API_URL}?key={API_KEY}", headers=headers, json=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching data for {url}: {response.status_code}")
        return None

# Function to determine if Core Web Vitals are passed
def check_cwv_status(lcp_status, cls_status, fcp_status):
    if lcp_status == "good" and cls_status == "good" and fcp_status == "good":
        return "passed"
    else:
        return "failed"

# Function to categorize metrics as good, needs improvement, or poor
def categorize_metric(metric_value, metric_type):
    # Convert metric_value to float if it's not None
    if metric_value is not None:
        try:
            metric_value = float(metric_value)
        except (ValueError, TypeError):
            return "unknown"
    else:
        return "unknown"
    
    if metric_type == "LCP":
        if metric_value <= 2500:
            return "good"
        elif metric_value <= 4000:
            return "needs improvement"
        else:
            return "poor"
    elif metric_type == "CLS":
        if metric_value <= 0.1:
            return "good"
        elif metric_value <= 0.25:
            return "needs improvement"
        else:
            return "poor"
    elif metric_type == "FCP":
        if metric_value <= 1800:
            return "good"
        elif metric_value <= 3000:
            return "needs improvement"
        else:
            return "poor"
    elif metric_type == "TTFB":
        if metric_value <= 800:
            return "good"
        elif metric_value <= 1800:
            return "needs improvement"
        else:
            return "poor"
    return "unknown"

# Function to extract metrics from CrUX data
def extract_metrics(data):
    if not data or 'record' not in data or 'metrics' not in data['record']:
        return None, None, None, None
    
    metrics = data['record']['metrics']
    
    # Extract LCP
    lcp = None
    if 'largest_contentful_paint' in metrics and 'percentiles' in metrics['largest_contentful_paint']:
        lcp = metrics['largest_contentful_paint']['percentiles']['p75']
    
    # Extract CLS
    cls = None
    if 'cumulative_layout_shift' in metrics and 'percentiles' in metrics['cumulative_layout_shift']:
        cls = metrics['cumulative_layout_shift']['percentiles']['p75']
    
    # Extract FCP
    fcp = None
    if 'first_contentful_paint' in metrics and 'percentiles' in metrics['first_contentful_paint']:
        fcp = metrics['first_contentful_paint']['percentiles']['p75']
    
    # Extract TTFB
    ttfb = None
    if 'experimental_time_to_first_byte' in metrics and 'percentiles' in metrics['experimental_time_to_first_byte']:
        ttfb = metrics['experimental_time_to_first_byte']['percentiles']['p75']
    
    return lcp, cls, fcp, ttfb

# Function to get URLs from the sitemap
def get_urls_from_sitemap(domain):
    try:
        sitemap_url = f"{domain}/sitemap.xml"
        response = requests.get(sitemap_url)
        if response.status_code == 200:
            # Extract URLs using regex (simple approach)
            urls = re.findall(r'<loc>(.*?)</loc>', response.text)
            return urls
        else:
            print(f"Failed to fetch sitemap: {response.status_code}")
            return []
    except Exception as e:
        print(f"Error fetching sitemap: {e}")
        return []

# Main process
print("Starting CrUX data collection for", DOMAIN)

# Get URLs from sitemap
urls = get_urls_from_sitemap(DOMAIN)

# If sitemap approach fails, use a few known pages
if not urls:
    print("Couldn't get URLs from sitemap. Using domain and some common paths.")
    urls = [
        DOMAIN,
        f"{DOMAIN}/about",
        f"{DOMAIN}/contact",
        f"{DOMAIN}/services",
        f"{DOMAIN}/blog"
    ]

print(f"Processing {len(urls)} URLs from sitemap")

# Prepare data structure
results = []
successful_urls = 0

# Process each URL
for i, url in enumerate(urls):
    print(f"Processing {i+1}/{len(urls)}: {url}")
    
    data = get_crux_data(url)
    if data:
        successful_urls += 1
        lcp_value, cls_value, fcp_value, ttfb_value = extract_metrics(data)
        
        # Categorize metrics
        lcp_status = categorize_metric(lcp_value, "LCP")
        cls_status = categorize_metric(cls_value, "CLS")
        fcp_status = categorize_metric(fcp_value, "FCP")
        ttfb_status = categorize_metric(ttfb_value, "TTFB")
        
        # Determine Core Web Vitals status
        cwv_status = check_cwv_status(lcp_status, cls_status, fcp_status)
        
        results.append({
            "url": url,
            "core_web_vitals_status": cwv_status,
            "lcp": lcp_status,
            "cls": cls_status,
            "fcp": fcp_status,
            "ttfb": ttfb_status
        })
    
    # Add a small delay to avoid rate limiting
    time.sleep(1)
    
    # Provide progress update every 100 URLs
    if (i + 1) % 100 == 0:
        print(f"Progress: {i+1}/{len(urls)} URLs processed. Found {successful_urls} URLs in CrUX database.")

# Create DataFrame
df = pd.DataFrame(results)

# Save to CSV
csv_filename = "crux_data.csv"
df.to_csv(csv_filename, index=False)

# Download the CSV file
files.download(csv_filename)

print(f"\nProcessing complete!")
print(f"Processed {len(urls)} URLs from sitemap")
print(f"Found {successful_urls} URLs in CrUX database")
print(f"CSV file '{csv_filename}' has been downloaded.")
