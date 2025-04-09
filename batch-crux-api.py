import requests
import json
import pandas as pd
import time
from google.colab import files
import concurrent.futures
import threading
import math
from tqdm.notebook import tqdm
import re

# Constants
API_KEY = 'YOUR_API_KEY'  # Replace with your actual API key
API_URL = 'https://chromeuxreport.googleapis.com/v1/records:queryRecord'

# Ask user how to collect URLs
print("How would you like to collect URLs for analysis?")
print("1. Fetch URLs from a website's sitemap")
print("2. Upload a text file with URLs (one URL per line)")
url_source_choice = input("Enter your choice (1 or 2): ")

urls = []
domain = None

if url_source_choice == '1':
    # Get domain for sitemap
    domain = input("\nEnter the domain to analyze (e.g., https://www.example.com): ")
    if not domain.startswith(('http://', 'https://')):
        domain = 'https://' + domain
    
    print(f"\nFetching sitemap from {domain}...")
    
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
    
    # Get URLs from sitemap
    urls = get_urls_from_sitemap(domain)
    
    # If sitemap approach fails, ask for manual input
    if not urls:
        print("\nCouldn't get URLs from sitemap. You have two options:")
        print("1. Try a different sitemap URL")
        print("2. Switch to file upload method")
        fallback_choice = input("Enter your choice (1 or 2): ")
        
        if fallback_choice == '1':
            custom_sitemap = input("Enter the full sitemap URL: ")
            try:
                response = requests.get(custom_sitemap, timeout=30)
                if response.status_code == 200:
                    urls = re.findall(r'<loc>(.*?)</loc>', response.text)
                    print(f"Found {len(urls)} URLs in the custom sitemap.")
                else:
                    print(f"Failed to fetch custom sitemap: {response.status_code}")
            except Exception as e:
                print(f"Error fetching custom sitemap: {e}")
        
        if fallback_choice == '2' or not urls:
            print("\nSwitching to file upload method...")
            url_source_choice = '2'  # Switch to file upload method

if url_source_choice == '2' or not urls:
    # Upload file with URLs
    print("\nPlease upload a text file containing URLs (one URL per line):")
    uploaded = files.upload()
    
    if not uploaded:
        print("No file was uploaded. Please run the script again.")
        raise SystemExit
    
    # Get the filename and content
    file_name = list(uploaded.keys())[0]
    file_content = uploaded[file_name]
    
    # Read URLs from the file
    urls = [line.strip() for line in file_content.decode('utf-8').split('\n') if line.strip()]
    print(f"Found {len(urls)} URLs in {file_name}")

# Check if we have URLs to process
if not urls:
    print("No URLs found. Please run the script again.")
    raise SystemExit

# Limit URLs if needed
max_urls = input("\nEnter maximum number of URLs to analyze (leave blank for all): ")
if max_urls.strip() and max_urls.isdigit():
    max_urls = int(max_urls)
    if max_urls < len(urls):
        print(f"Limiting analysis to {max_urls} URLs out of {len(urls)} found.")
        urls = urls[:max_urls]

# Form factor selection with detailed descriptions
print("\nSelect form factor for CrUX data:")
print("1. All form factors - Combined data from all device types (phones, desktops, tablets)")
print("2. Mobile only (PHONE) - Data from mobile phones only")
print("3. Desktop only (DESKTOP) - Data from desktop computers only")
print("4. Tablet only (TABLET) - Data from tablet devices only")

form_factor_choice = input("Enter your choice (1-4): ")

# Set form factor based on user choice with detailed feedback
if form_factor_choice == '1':
    FORM_FACTOR = None
    print("\nSelected: All form factors")
    print("Description: This will retrieve combined data across all device types.")
    print("Use this option to see overall performance across your entire user base.")
elif form_factor_choice == '2':
    FORM_FACTOR = 'PHONE'
    print("\nSelected: Mobile phones only (PHONE)")
    print("Description: This will retrieve data only from mobile phone users.")
    print("Use this option to analyze mobile-specific performance issues.")
elif form_factor_choice == '3':
    FORM_FACTOR = 'DESKTOP'
    print("\nSelected: Desktop computers only (DESKTOP)")
    print("Description: This will retrieve data only from desktop computer users.")
    print("Use this option to analyze desktop-specific performance issues.")
elif form_factor_choice == '4':
    FORM_FACTOR = 'TABLET'
    print("\nSelected: Tablet devices only (TABLET)")
    print("Description: This will retrieve data only from tablet users.")
    print("Use this option to analyze tablet-specific performance issues.")
    print("Note: Some sites may have limited tablet data available.")
else:
    FORM_FACTOR = None
    print("\nInvalid selection. Defaulting to all form factors.")
    print("Description: This will retrieve combined data across all device types.")
    print("Use this option to see overall performance across your entire user base.")

# Rate limiting constants
RATE_LIMIT_QUERIES = 60  # CrUX API has higher limits than PageSpeed Insights
RATE_LIMIT_WINDOW = 60   # 60 seconds window
MAX_CONCURRENT_REQUESTS = min(20, RATE_LIMIT_QUERIES // 2)  # Set concurrency based on rate limit

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

# Function to get data from CrUX API for a specific URL
def get_crux_data(url, rate_limiter):
    # Wait if needed to respect rate limits
    rate_limiter.wait_if_needed()
    
    # Prepare request payload
    payload = {
        "url": url,
        "metrics": ["largest_contentful_paint", "cumulative_layout_shift", "first_contentful_paint", "first_input_delay", "interaction_to_next_paint"]
    }
    
    # Add form factor if specified
    if FORM_FACTOR:
        payload["formFactor"] = FORM_FACTOR
    
    headers = {
        "Content-Type": "application/json"
    }
    
    params = {
        "key": API_KEY
    }
    
    try:
        response = requests.post(API_URL, params=params, headers=headers, json=payload, timeout=30)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:  # Rate limit exceeded
            time.sleep(5)  # Wait a bit longer before retry
            return get_crux_data(url, rate_limiter)  # Retry
        else:
            return None
    except Exception as e:
        return None

# Function to process a single URL and return the result
def process_url(url, rate_limiter, pbar=None):
    data = get_crux_data(url, rate_limiter)
    
    if pbar:
        pbar.update(1)
        
    if data and 'record' in data and 'metrics' in data['record']:
        try:
            metrics = data['record']['metrics']
            
            # Extract LCP
            lcp_value = None
            lcp_status = "unknown"
            lcp_good = lcp_ni = lcp_poor = None
            if 'largest_contentful_paint' in metrics:
                if 'percentiles' in metrics['largest_contentful_paint']:
                    lcp_value = metrics['largest_contentful_paint']['percentiles']['p75']
                    lcp_status = categorize_metric(lcp_value, "LCP")
                if 'histogram' in metrics['largest_contentful_paint']:
                    histogram = metrics['largest_contentful_paint']['histogram']
                    lcp_good = histogram[0]['density'] * 100 if len(histogram) > 0 else None
                    lcp_ni = histogram[1]['density'] * 100 if len(histogram) > 1 else None
                    lcp_poor = histogram[2]['density'] * 100 if len(histogram) > 2 else None
            
            # Extract CLS
            cls_value = None
            cls_status = "unknown"
            cls_good = cls_ni = cls_poor = None
            if 'cumulative_layout_shift' in metrics:
                if 'percentiles' in metrics['cumulative_layout_shift']:
                    cls_value = metrics['cumulative_layout_shift']['percentiles']['p75']
                    cls_status = categorize_metric(cls_value, "CLS")
                if 'histogram' in metrics['cumulative_layout_shift']:
                    histogram = metrics['cumulative_layout_shift']['histogram']
                    cls_good = histogram[0]['density'] * 100 if len(histogram) > 0 else None
                    cls_ni = histogram[1]['density'] * 100 if len(histogram) > 1 else None
                    cls_poor = histogram[2]['density'] * 100 if len(histogram) > 2 else None
            
            # Extract FCP
            fcp_value = None
            fcp_status = "unknown"
            fcp_good = fcp_ni = fcp_poor = None
            if 'first_contentful_paint' in metrics:
                if 'percentiles' in metrics['first_contentful_paint']:
                    fcp_value = metrics['first_contentful_paint']['percentiles']['p75']
                    fcp_status = categorize_metric(fcp_value, "FCP")
                if 'histogram' in metrics['first_contentful_paint']:
                    histogram = metrics['first_contentful_paint']['histogram']
                    fcp_good = histogram[0]['density'] * 100 if len(histogram) > 0 else None
                    fcp_ni = histogram[1]['density'] * 100 if len(histogram) > 1 else None
                    fcp_poor = histogram[2]['density'] * 100 if len(histogram) > 2 else None
            
            # Extract FID
            fid_value = None
            fid_status = "unknown"
            fid_good = fid_ni = fid_poor = None
            if 'first_input_delay' in metrics:
                if 'percentiles' in metrics['first_input_delay']:
                    fid_value = metrics['first_input_delay']['percentiles']['p75']
                    fid_status = categorize_metric(fid_value, "FID")
                if 'histogram' in metrics['first_input_delay']:
                    histogram = metrics['first_input_delay']['histogram']
                    fid_good = histogram[0]['density'] * 100 if len(histogram) > 0 else None
                    fid_ni = histogram[1]['density'] * 100 if len(histogram) > 1 else None
                    fid_poor = histogram[2]['density'] * 100 if len(histogram) > 2 else None
            
            # Extract INP (Interaction to Next Paint)
            inp_value = None
            inp_status = "unknown"
            inp_good = inp_ni = inp_poor = None
            if 'interaction_to_next_paint' in metrics:
                if 'percentiles' in metrics['interaction_to_next_paint']:
                    inp_value = metrics['interaction_to_next_paint']['percentiles']['p75']
                    inp_status = categorize_metric(inp_value, "INP")
                if 'histogram' in metrics['interaction_to_next_paint']:
                    histogram = metrics['interaction_to_next_paint']['histogram']
                    inp_good = histogram[0]['density'] * 100 if len(histogram) > 0 else None
                    inp_ni = histogram[1]['density'] * 100 if len(histogram) > 1 else None
                    inp_poor = histogram[2]['density'] * 100 if len(histogram) > 2 else None
            
            # Determine Core Web Vitals status
            # For 2024, use LCP, CLS, and INP (replacing FID)
            cwv_status = check_cwv_status(lcp_status, cls_status, inp_status)
            
            # Get form factor from response
            form_factor = data['record'].get('key', {}).get('formFactor', 'ALL')
            
            return {
                "url": url,
                "form_factor": form_factor,
                "core_web_vitals_status": cwv_status,
                
                # LCP data
                "lcp_status": lcp_status,
                "lcp_value_ms": format_value(lcp_value, "ms"),
                "lcp_good_pct": format_value(lcp_good, "%"),
                "lcp_ni_pct": format_value(lcp_ni, "%"),
                "lcp_poor_pct": format_value(lcp_poor, "%"),
                
                # CLS data
                "cls_status": cls_status,
                "cls_value": format_value(cls_value),
                "cls_good_pct": format_value(cls_good, "%"),
                "cls_ni_pct": format_value(cls_ni, "%"),
                "cls_poor_pct": format_value(cls_poor, "%"),
                
                # FCP data
                "fcp_status": fcp_status,
                "fcp_value_ms": format_value(fcp_value, "ms"),
                "fcp_good_pct": format_value(fcp_good, "%"),
                "fcp_ni_pct": format_value(fcp_ni, "%"),
                "fcp_poor_pct": format_value(fcp_poor, "%"),
                
                # FID data
                "fid_status": fid_status,
                "fid_value_ms": format_value(fid_value, "ms"),
                "fid_good_pct": format_value(fid_good, "%"),
                "fid_ni_pct": format_value(fid_ni, "%"),
                "fid_poor_pct": format_value(fid_poor, "%"),
                
                # INP data
                "inp_status": inp_status,
                "inp_value_ms": format_value(inp_value, "ms"),
                "inp_good_pct": format_value(inp_good, "%"),
                "inp_ni_pct": format_value(inp_ni, "%"),
                "inp_poor_pct": format_value(inp_poor, "%")
            }
        except Exception as e:
            # Return a row with error information
            return {
                "url": url,
                "form_factor": FORM_FACTOR if FORM_FACTOR else "ALL",
                "core_web_vitals_status": "error",
                "lcp_status": "error", "lcp_value_ms": None, "lcp_good_pct": None, "lcp_ni_pct": None, "lcp_poor_pct": None,
                "cls_status": "error", "cls_value": None, "cls_good_pct": None, "cls_ni_pct": None, "cls_poor_pct": None,
                "fcp_status": "error", "fcp_value_ms": None, "fcp_good_pct": None, "fcp_ni_pct": None, "fcp_poor_pct": None,
                "fid_status": "error", "fid_value_ms": None, "fid_good_pct": None, "fid_ni_pct": None, "fid_poor_pct": None,
                "inp_status": "error", "inp_value_ms": None, "inp_good_pct": None, "inp_ni_pct": None, "inp_poor_pct": None
            }
    
    # Return a row for URLs that failed to fetch data
    return {
        "url": url,
        "form_factor": FORM_FACTOR if FORM_FACTOR else "ALL",
        "core_web_vitals_status": "no data",
        "lcp_status": "no data", "lcp_value_ms": None, "lcp_good_pct": None, "lcp_ni_pct": None, "lcp_poor_pct": None,
        "cls_status": "no data", "cls_value": None, "cls_good_pct": None, "cls_ni_pct": None, "cls_poor_pct": None,
        "fcp_status": "no data", "fcp_value_ms": None, "fcp_good_pct": None, "fcp_ni_pct": None, "fcp_poor_pct": None,
        "fid_status": "no data", "fid_value_ms": None, "fid_good_pct": None, "fid_ni_pct": None, "fid_poor_pct": None,
        "inp_status": "no data", "inp_value_ms": None, "inp_good_pct": None, "inp_ni_pct": None, "inp_poor_pct": None
    }

# Helper function to format values with appropriate units
def format_value(value, unit=None):
    if value is None:
        return None
    
    if unit == "ms":
        # Format milliseconds with no decimal places
        return round(value)
    elif unit == "%":
        # Format percentages with one decimal place
        return round(value, 1)
    else:
        # For CLS (unitless), use 2 decimal places
        return round(value, 2)

# Function to determine if Core Web Vitals are passed
def check_cwv_status(lcp_status, cls_status, inp_status):
    # For 2024, Core Web Vitals are LCP, CLS, and INP (replacing FID)
    if lcp_status == "good" and cls_status == "good" and inp_status == "good":
        return "passed"
    elif lcp_status == "no data" or cls_status == "no data" or inp_status == "no data":
        return "insufficient data"
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
        return "no data"
    
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
    elif metric_type == "FID":
        if metric_value <= 100:
            return "good"
        elif metric_value <= 300:
            return "needs improvement"
        else:
            return "poor"
    elif metric_type == "INP":
        if metric_value <= 200:
            return "good"
        elif metric_value <= 500:
            return "needs improvement"
        else:
            return "poor"
    return "unknown"

# Main process - Now we have URLs either from sitemap or uploaded file
print(f"Processing {len(urls)} URLs...")

# Display form factor selection summary
form_factor_display = FORM_FACTOR if FORM_FACTOR else "ALL (mixed data)"
print(f"\nAnalyzing URLs using form factor: {form_factor_display}")

print(f"Rate limit: {RATE_LIMIT_QUERIES} queries per {RATE_LIMIT_WINDOW} seconds")
print(f"Using {MAX_CONCURRENT_REQUESTS} concurrent requests")

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
                # Add a failure entry with all columns
                results.append({
                    "url": url,
                    "form_factor": FORM_FACTOR if FORM_FACTOR else "ALL",
                    "core_web_vitals_status": "error",
                    "lcp_status": "error", "lcp_value_ms": None, "lcp_good_pct": None, "lcp_ni_pct": None, "lcp_poor_pct": None,
                    "cls_status": "error", "cls_value": None, "cls_good_pct": None, "cls_ni_pct": None, "cls_poor_pct": None,
                    "fcp_status": "error", "fcp_value_ms": None, "fcp_good_pct": None, "fcp_ni_pct": None, "fcp_poor_pct": None,
                    "fid_status": "error", "fid_value_ms": None, "fid_good_pct": None, "fid_ni_pct": None, "fid_poor_pct": None,
                    "inp_status": "error", "inp_value_ms": None, "inp_good_pct": None, "inp_ni_pct": None, "inp_poor_pct": None
                })

end_time = time.time()
elapsed_time = end_time - start_time

# Create DataFrame
if results:
    df = pd.DataFrame(results)
    
    # Create a CSV version
    form_factor_file = FORM_FACTOR if FORM_FACTOR else "ALL"
    site_name = domain.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0] if domain else "custom"
    output_filename = f"crux_results_{site_name}_{form_factor_file}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(output_filename, index=False)
    
    # Download the CSV file
    files.download(output_filename)
    
    # Calculate statistics
    total_urls = len(results)
    passed_urls = len(df[df['core_web_vitals_status'] == 'passed'])
    failed_urls = len(df[df['core_web_vitals_status'] == 'failed'])
    no_data_urls = len(df[df['core_web_vitals_status'] == 'insufficient data'])
    error_urls = len(df[df['core_web_vitals_status'] == 'error'])
    
    print(f"\n===== CrUX Analysis Results =====")
    print(f"Total URLs processed: {total_urls}")
    print(f"Form factor: {form_factor_display}")
    print(f"\nCore Web Vitals Status:")
    print(f"✅ Passed: {passed_urls} ({passed_urls/total_urls*100:.1f}%)")
    print(f"❌ Failed: {failed_urls} ({failed_urls/total_urls*100:.1f}%)")
    print(f"ℹ️ Insufficient data: {no_data_urls} ({no_data_urls/total_urls*100:.1f}%)")
    print(f"⚠️ Errors: {error_urls} ({error_urls/total_urls*100:.1f}%)")
    
    # Add metric-specific stats
    print(f"\nIndividual Metrics (Good/Needs Improvement/Poor/No Data):")
    for metric in ['lcp_status', 'cls_status', 'inp_status']:  # Updated to use INP instead of FID for 2024
        metric_name = metric.split('_')[0].upper()
        good = len(df[df[metric] == 'good'])
        needs_improvement = len(df[df[metric] == 'needs improvement'])
        poor = len(df[df[metric] == 'poor'])
        no_data = len(df[df[metric] == 'no data'])
        
        print(f"{metric_name}: {good}/{needs_improvement}/{poor}/{no_data} " +
              f"({good/total_urls*100:.1f}%/{needs_improvement/total_urls*100:.1f}%/{poor/total_urls*100:.1f}%/{no_data/total_urls*100:.1f}%)")
    
    print(f"\nProcessing time: {elapsed_time:.1f} seconds ({elapsed_time/60:.1f} minutes)")
    print(f"CSV file '{output_filename}' has been downloaded.")
    print("=====================================")
else:
    print("\nNo valid results were obtained. Please check the API key and try again.")
