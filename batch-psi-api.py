import requests
import json
import pandas as pd
import time
from google.colab import files
import re
import concurrent.futures
import threading
import math
from tqdm.notebook import tqdm

# Constants
API_KEY = 'YOUR_API_KEY'  # Replace with your actual API key
API_URL = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'
DOMAIN = "YOUR_DOMAIN"

# Rate limiting constants
RATE_LIMIT_QUERIES = 60  # 60 queries per 100 seconds
RATE_LIMIT_WINDOW = 100  # 100 seconds window
MAX_CONCURRENT_REQUESTS = min(10, RATE_LIMIT_QUERIES // 2)  # Set concurrency based on rate limit

# Thread-safe counter and rate limiter
class RateLimiter:
    def __init__(self, max_queries, time_window):
        self.lock = threading.Lock()
        self.max_queries = max_queries
        self.time_window = time_window
        self.query_times = []
        self.counter = 0
    
    def increment(self):
        with self.lock:
            self.counter += 1
            return self.counter
    
    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            
            # Remove timestamps older than the time window
            self.query_times = [t for t in self.query_times if now - t < self.time_window]
            
            # If we're at the limit, wait until we can make another request
            if len(self.query_times) >= self.max_queries:
                oldest = min(self.query_times)
                sleep_time = oldest + self.time_window - now
                if sleep_time > 0:
                    time.sleep(sleep_time)
            
            # Add current timestamp and return
            self.query_times.append(time.time())

# Function to get data from PageSpeed Insights API for a specific URL
def get_pagespeed_data(url, rate_limiter):
    # Wait if needed to respect rate limits
    rate_limiter.wait_if_needed()
    
    params = {
        'url': url,
        'key': API_KEY,
        'strategy': 'mobile',  # You can change to 'desktop' if needed
        'category': 'performance',
    }
    
    try:
        response = requests.get(API_URL, params=params, timeout=60)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:  # Rate limit exceeded
            # Don't print to avoid cluttering the output
            time.sleep(10)  # Wait a bit longer before retry
            return get_pagespeed_data(url, rate_limiter)  # Retry
        else:
            # Don't print to avoid cluttering the output
            return None
    except Exception as e:
        # Don't print to avoid cluttering the output
        return None

# Function to process a single URL and return the result
def process_url(url, rate_limiter, pbar=None):
    data = get_pagespeed_data(url, rate_limiter)
    
    if pbar:
        pbar.update(1)
        
    if data:
        try:
            lcp_value, cls_value, fcp_value, ttfb_value = extract_metrics(data)
            
            # Categorize metrics
            lcp_status = categorize_metric(lcp_value, "LCP")
            cls_status = categorize_metric(cls_value, "CLS")
            fcp_status = categorize_metric(fcp_value, "FCP")
            ttfb_status = categorize_metric(ttfb_value, "TTFB")
            
            # Determine Core Web Vitals status
            cwv_status = check_cwv_status(lcp_status, cls_status, fcp_status)
            
            # Get performance score
            performance_score = None
            if 'lighthouseResult' in data and 'categories' in data['lighthouseResult'] and 'performance' in data['lighthouseResult']['categories']:
                performance_score = data['lighthouseResult']['categories']['performance']['score'] * 100
            
            return {
                "url": url,
                "performance_score": f"{performance_score:.0f}" if performance_score is not None else "unknown",
                "core_web_vitals_status": cwv_status,
                "lcp": lcp_status,
                "cls": cls_status,
                "fcp": fcp_status,
                "ttfb": ttfb_status
            }
        except Exception as e:
            # Return a row with error information
            return {
                "url": url,
                "performance_score": "error",
                "core_web_vitals_status": "error",
                "lcp": "error",
                "cls": "error", 
                "fcp": "error",
                "ttfb": "error"
            }
    
    # Return a row for URLs that failed to fetch data
    return {
        "url": url,
        "performance_score": "failed",
        "core_web_vitals_status": "failed",
        "lcp": "unknown",
        "cls": "unknown",
        "fcp": "unknown",
        "ttfb": "unknown"
    }

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

# Function to extract metrics from PageSpeed Insights data
def extract_metrics(data):
    if not data or 'lighthouseResult' not in data or 'audits' not in data['lighthouseResult']:
        return None, None, None, None
    
    audits = data['lighthouseResult']['audits']
    
    # Extract LCP
    lcp = None
    if 'largest-contentful-paint' in audits and 'numericValue' in audits['largest-contentful-paint']:
        lcp = audits['largest-contentful-paint']['numericValue']
    
    # Extract CLS
    cls = None
    if 'cumulative-layout-shift' in audits and 'numericValue' in audits['cumulative-layout-shift']:
        cls = audits['cumulative-layout-shift']['numericValue']
    
    # Extract FCP
    fcp = None
    if 'first-contentful-paint' in audits and 'numericValue' in audits['first-contentful-paint']:
        fcp = audits['first-contentful-paint']['numericValue']
    
    # Extract TTFB
    ttfb = None
    if 'server-response-time' in audits and 'numericValue' in audits['server-response-time']:
        ttfb = audits['server-response-time']['numericValue']
    
    return lcp, cls, fcp, ttfb

# Function to get URLs from the sitemap
def get_urls_from_sitemap(domain):
    try:
        sitemap_url = f"{domain}/sitemap.xml"
        response = requests.get(sitemap_url, timeout=30)
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
print("Starting PageSpeed Insights data collection for", DOMAIN)
print(f"Rate limit: {RATE_LIMIT_QUERIES} queries per {RATE_LIMIT_WINDOW} seconds")
print(f"Using {MAX_CONCURRENT_REQUESTS} concurrent requests")

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

# Initialize rate limiter
rate_limiter = RateLimiter(RATE_LIMIT_QUERIES, RATE_LIMIT_WINDOW)

# Calculate estimated time
estimated_time = math.ceil(len(urls) / MAX_CONCURRENT_REQUESTS) * (RATE_LIMIT_WINDOW / RATE_LIMIT_QUERIES) * len(urls) / MAX_CONCURRENT_REQUESTS
print(f"Estimated processing time: {estimated_time:.1f} seconds ({estimated_time/60:.1f} minutes)")

start_time = time.time()

# Create a progress bar
with tqdm(total=len(urls), desc="Processing URLs") as pbar:
    # Use ThreadPoolExecutor for parallel processing
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
        # Submit all tasks
        future_to_url = {executor.submit(process_url, url, rate_limiter, pbar): url for url in urls}
        
        # Process results as they complete
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as exc:
                # Add a failure entry
                results.append({
                    "url": url,
                    "performance_score": "error",
                    "core_web_vitals_status": "error",
                    "lcp": "error",
                    "cls": "error", 
                    "fcp": "error",
                    "ttfb": "error"
                })

end_time = time.time()
elapsed_time = end_time - start_time

# Create DataFrame
if results:
    df = pd.DataFrame(results)
    
    # Create a CSV version with just the required columns
    expected_columns = ["url", "performance_score", "core_web_vitals_status", "lcp", "cls", "fcp", "ttfb"]
    
    # Check if all expected columns exist
    missing_columns = [col for col in expected_columns if col not in df.columns]
    if missing_columns:
        print(f"Warning: Missing columns in results: {missing_columns}")
        # Add missing columns with default values
        for col in missing_columns:
            df[col] = "unknown"
    
    csv_df = df[expected_columns]
    
    # Save to CSV
    csv_filename = "pagespeed_data.csv"
    csv_df.to_csv(csv_filename, index=False)
    
    # Download the CSV file
    files.download(csv_filename)
    
    print(f"\nProcessed {len(results)} URLs from {DOMAIN}")
    print(f"Successful: {len(df[df['performance_score'] != 'failed'])}")
    print(f"Failed: {len(df[df['performance_score'] == 'failed'])}")
    print(f"Actual processing time: {elapsed_time:.1f} seconds ({elapsed_time/60:.1f} minutes)")
    print(f"CSV file '{csv_filename}' has been downloaded.")
else:
    print("\nNo valid results were obtained. Please check the API key and try again.")