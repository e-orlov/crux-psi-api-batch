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
API_URL = 'https://www.googleapis.com/pagespeedonline/v5/runPagespeed'

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

# Ask user to select device type
print("\nSelect device type for PageSpeed Insights analysis:")
print("1. Mobile - Simulates a mobile device with mobile network conditions")
print("2. Desktop - Simulates a desktop device with faster network")
device_choice = input("Enter your choice (1 or 2): ")

if device_choice == '2':
    STRATEGY = 'desktop'
    print("\nSelected: Desktop device simulation")
    print("This will analyze performance as experienced on desktop computers.")
else:
    STRATEGY = 'mobile'  # Default to mobile
    print("\nSelected: Mobile device simulation")
    print("This will analyze performance as experienced on mobile phones.")

# Rate limiting constants
RATE_LIMIT_QUERIES = 20  # PSI API has a limit of ~20 queries per minute
RATE_LIMIT_WINDOW = 60   # 60 seconds window
MAX_CONCURRENT_REQUESTS = min(5, RATE_LIMIT_QUERIES // 4)  # Set concurrency conservatively

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
def get_psi_data(url, rate_limiter):
    # Wait if needed to respect rate limits
    rate_limiter.wait_if_needed()
    
    # Prepare request parameters
    params = {
        'url': url,
        'key': API_KEY,
        'strategy': STRATEGY,
        'category': 'performance',
    }
    
    try:
        response = requests.get(API_URL, params=params, timeout=60)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 429:  # Rate limit exceeded
            time.sleep(5)  # Wait a bit longer before retry
            return get_psi_data(url, rate_limiter)  # Retry
        else:
            return None
    except Exception as e:
        return None

# Function to process a single URL and return the result
def process_url(url, rate_limiter, pbar=None):
    data = get_psi_data(url, rate_limiter)
    
    if pbar:
        pbar.update(1)
        
    if data and 'lighthouseResult' in data:
        try:
            # Extract overall performance score
            performance_score = data['lighthouseResult']['categories']['performance']['score'] * 100
            
            # Extract Core Web Vitals metrics from lab data
            audits = data['lighthouseResult']['audits']
            
            # Extract LCP
            lcp_value = None
            lcp_score = None
            if 'largest-contentful-paint' in audits:
                lcp_value = audits['largest-contentful-paint'].get('numericValue')
                lcp_score = audits['largest-contentful-paint'].get('score')
            
            # Extract CLS
            cls_value = None
            cls_score = None
            if 'cumulative-layout-shift' in audits:
                cls_value = audits['cumulative-layout-shift'].get('numericValue')
                cls_score = audits['cumulative-layout-shift'].get('score')
            
            # Extract FCP
            fcp_value = None
            fcp_score = None
            if 'first-contentful-paint' in audits:
                fcp_value = audits['first-contentful-paint'].get('numericValue')
                fcp_score = audits['first-contentful-paint'].get('score')
            
            # Extract TBT (Total Blocking Time)
            tbt_value = None
            tbt_score = None
            if 'total-blocking-time' in audits:
                tbt_value = audits['total-blocking-time'].get('numericValue')
                tbt_score = audits['total-blocking-time'].get('score')
            
            # Extract TTI (Time to Interactive)
            tti_value = None
            tti_score = None
            if 'interactive' in audits:
                tti_value = audits['interactive'].get('numericValue')
                tti_score = audits['interactive'].get('score')
            
            # Extract Speed Index
            si_value = None
            si_score = None
            if 'speed-index' in audits:
                si_value = audits['speed-index'].get('numericValue')
                si_score = audits['speed-index'].get('score')
            
            # Get field data if available
            field_lcp = field_cls = field_fid = None
            field_lcp_status = field_cls_status = field_fid_status = "no data"
            
            if 'loadingExperience' in data and 'metrics' in data['loadingExperience']:
                field_metrics = data['loadingExperience']['metrics']
                
                if 'LARGEST_CONTENTFUL_PAINT_MS' in field_metrics:
                    field_lcp = field_metrics['LARGEST_CONTENTFUL_PAINT_MS']['percentile']
                    field_lcp_status = field_metrics['LARGEST_CONTENTFUL_PAINT_MS']['category']
                
                if 'CUMULATIVE_LAYOUT_SHIFT_SCORE' in field_metrics:
                    field_cls = field_metrics['CUMULATIVE_LAYOUT_SHIFT_SCORE']['percentile'] / 100  # Convert to decimal
                    field_cls_status = field_metrics['CUMULATIVE_LAYOUT_SHIFT_SCORE']['category']
                
                if 'FIRST_INPUT_DELAY_MS' in field_metrics:
                    field_fid = field_metrics['FIRST_INPUT_DELAY_MS']['percentile']
                    field_fid_status = field_metrics['FIRST_INPUT_DELAY_MS']['category']
            
            # Format values for better readability
            lcp_value_formatted = format_ms(lcp_value) if lcp_value else None
            fcp_value_formatted = format_ms(fcp_value) if fcp_value else None
            tbt_value_formatted = format_ms(tbt_value) if tbt_value else None
            tti_value_formatted = format_ms(tti_value) if tti_value else None
            si_value_formatted = format_ms(si_value) if si_value else None
            cls_value_formatted = format_cls(cls_value) if cls_value is not None else None
            
            field_lcp_formatted = format_ms(field_lcp) if field_lcp else None
            field_cls_formatted = format_cls(field_cls) if field_cls is not None else None
            field_fid_formatted = format_ms(field_fid) if field_fid else None
            
            # Determine Core Web Vitals pass/fail status based on lab data
            lab_cwv_status = check_lab_cwv_status(lcp_score, cls_score, tbt_score)
            
            # Determine Core Web Vitals pass/fail status based on field data
            field_cwv_status = check_field_cwv_status(field_lcp_status, field_cls_status, field_fid_status)
            
            return {
                "url": url,
                "strategy": STRATEGY,
                "performance_score": round(performance_score, 1),
                
                # Lab data
                "lab_cwv_status": lab_cwv_status,
                
                "lab_lcp_score": score_to_text(lcp_score),
                "lab_lcp_value": lcp_value_formatted,
                
                "lab_cls_score": score_to_text(cls_score),
                "lab_cls_value": cls_value_formatted,
                
                "lab_fcp_score": score_to_text(fcp_score),
                "lab_fcp_value": fcp_value_formatted,
                
                "lab_tbt_score": score_to_text(tbt_score),
                "lab_tbt_value": tbt_value_formatted,
                
                "lab_tti_score": score_to_text(tti_score),
                "lab_tti_value": tti_value_formatted,
                
                "lab_si_score": score_to_text(si_score),
                "lab_si_value": si_value_formatted,
                
                # Field data
                "field_cwv_status": field_cwv_status,
                
                "field_lcp_status": format_field_status(field_lcp_status),
                "field_lcp_value": field_lcp_formatted,
                
                "field_cls_status": format_field_status(field_cls_status),
                "field_cls_value": field_cls_formatted,
                
                "field_fid_status": format_field_status(field_fid_status),
                "field_fid_value": field_fid_formatted
            }
        except Exception as e:
            # Return a row with error information
            return {
                "url": url,
                "strategy": STRATEGY,
                "performance_score": None,
                
                "lab_cwv_status": "error",
                "lab_lcp_score": "error", "lab_lcp_value": None,
                "lab_cls_score": "error", "lab_cls_value": None,
                "lab_fcp_score": "error", "lab_fcp_value": None,
                "lab_tbt_score": "error", "lab_tbt_value": None,
                "lab_tti_score": "error", "lab_tti_value": None,
                "lab_si_score": "error", "lab_si_value": None,
                
                "field_cwv_status": "error",
                "field_lcp_status": "error", "field_lcp_value": None,
                "field_cls_status": "error", "field_cls_value": None,
                "field_fid_status": "error", "field_fid_value": None
            }
    
    # Return a row for URLs that failed to fetch data
    return {
        "url": url,
        "strategy": STRATEGY,
        "performance_score": None,
        
        "lab_cwv_status": "no data",
        "lab_lcp_score": "no data", "lab_lcp_value": None,
        "lab_cls_score": "no data", "lab_cls_value": None,
        "lab_fcp_score": "no data", "lab_fcp_value": None,
        "lab_tbt_score": "no data", "lab_tbt_value": None,
        "lab_tti_score": "no data", "lab_tti_value": None,
        "lab_si_score": "no data", "lab_si_value": None,
        
        "field_cwv_status": "no data",
        "field_lcp_status": "no data", "field_lcp_value": None,
        "field_cls_status": "no data", "field_cls_value": None,
        "field_fid_status": "no data", "field_fid_value": None
    }

# Helper functions for formatting and categorization
def format_ms(value):
    """Format milliseconds to nearest integer"""
    if value is None:
        return None
    return round(value)

def format_cls(value):
    """Format CLS to 2 decimal places"""
    if value is None:
        return None
    return round(value, 2)

def score_to_text(score):
    """Convert Lighthouse score to text category"""
    if score is None:
        return "no data"
    if score >= 0.9:
        return "good"
    elif score >= 0.5:
        return "needs improvement"
    else:
        return "poor"

def format_field_status(status):
    """Format field data status"""
    if status == "GOOD":
        return "good"
    elif status == "NEEDS_IMPROVEMENT":
        return "needs improvement"
    elif status == "POOR":
        return "poor"
    else:
        return "no data"

def check_lab_cwv_status(lcp_score, cls_score, tbt_score):
    """Check Core Web Vitals status based on lab data"""
    # For lab data, we use TBT as a proxy for FID
    if lcp_score is None or cls_score is None or tbt_score is None:
        return "insufficient data"
    
    if lcp_score >= 0.9 and cls_score >= 0.9 and tbt_score >= 0.9:
        return "passed"
    else:
        return "failed"

def check_field_cwv_status(lcp_status, cls_status, fid_status):
    """Check Core Web Vitals status based on field data"""
    if lcp_status == "no data" or cls_status == "no data" or fid_status == "no data":
        return "insufficient data"
    
    if lcp_status == "GOOD" and cls_status == "GOOD" and fid_status == "GOOD":
        return "passed"
    else:
        return "failed"

# Main process - Now we have URLs either from sitemap or uploaded file
print(f"Processing {len(urls)} URLs...")

# Display device selection summary
print(f"\nAnalyzing URLs using device type: {STRATEGY}")

print(f"Rate limit: {RATE_LIMIT_QUERIES} queries per {RATE_LIMIT_WINDOW} seconds")
print(f"Using {MAX_CONCURRENT_REQUESTS} concurrent requests")

# Prepare data structure
results = []

# Initialize rate limiter
rate_limiter = RateLimiter(RATE_LIMIT_QUERIES, RATE_LIMIT_WINDOW)

# Calculate estimated time (PSI is slower than CrUX)
estimated_time = len(urls) * 5  # Rough estimate: 5 seconds per URL
print(f"Estimated processing time: {estimated_time:.1f} seconds ({estimated_time/60:.1f} minutes)")
print("Note: PageSpeed Insights runs full page analysis and may take longer than estimated.")

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
                    "strategy": STRATEGY,
                    "performance_score": None,
                    
                    "lab_cwv_status": "error",
                    "lab_lcp_score": "error", "lab_lcp_value": None,
                    "lab_cls_score": "error", "lab_cls_value": None,
                    "lab_fcp_score": "error", "lab_fcp_value": None,
                    "lab_tbt_score": "error", "lab_tbt_value": None,
                    "lab_tti_score": "error", "lab_tti_value": None,
                    "lab_si_score": "error", "lab_si_value": None,
                    
                    "field_cwv_status": "error",
                    "field_lcp_status": "error", "field_lcp_value": None,
                    "field_cls_status": "error", "field_cls_value": None,
                    "field_fid_status": "error", "field_fid_value": None
                })

end_time = time.time()
elapsed_time = end_time - start_time

# Create DataFrame
if results:
    df = pd.DataFrame(results)
    
    # Create a CSV version
    site_name = domain.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0] if domain else "custom"
    output_filename = f"psi_results_{site_name}_{STRATEGY}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(output_filename, index=False)
    
    # Download the CSV file
    files.download(output_filename)
    
    # Calculate statistics
    total_urls = len(results)
    
    # Lab data statistics
    lab_passed = len(df[df['lab_cwv_status'] == 'passed'])
    lab_failed = len(df[df['lab_cwv_status'] == 'failed'])
    lab_no_data = len(df[df['lab_cwv_status'] == 'insufficient data'])
    lab_error = len(df[df['lab_cwv_status'] == 'error'])
    
    # Field data statistics
    field_passed = len(df[df['field_cwv_status'] == 'passed'])
    field_failed = len(df[df['field_cwv_status'] == 'failed'])
    field_no_data = len(df[df['field_cwv_status'] == 'insufficient data'])
    field_error = len(df[df['field_cwv_status'] == 'error'])
    
    # Calculate average performance score
    avg_score = df['performance_score'].mean()
    
    print(f"\n===== PageSpeed Insights Results ({STRATEGY}) =====")
    print(f"Total URLs processed: {total_urls}")
    print(f"Average Performance Score: {avg_score:.1f}/100")
    
    print(f"\nLab Data - Core Web Vitals Status:")
    print(f"✅ Passed: {lab_passed} ({lab_passed/total_urls*100:.1f}%)")
    print(f"❌ Failed: {lab_failed} ({lab_failed/total_urls*100:.1f}%)")
    print(f"ℹ️ Insufficient data: {lab_no_data} ({lab_no_data/total_urls*100:.1f}%)")
    print(f"⚠️ Errors: {lab_error} ({lab_error/total_urls*100:.1f}%)")
    
    print(f"\nField Data - Core Web Vitals Status:")
    print(f"✅ Passed: {field_passed} ({field_passed/total_urls*100:.1f}%)")
    print(f"❌ Failed: {field_failed} ({field_failed/total_urls*100:.1f}%)")
    print(f"ℹ️ Insufficient data: {field_no_data} ({field_no_data/total_urls*100:.1f}%)")
    print(f"⚠️ Errors: {field_error} ({field_error/total_urls*100:.1f}%)")
    
    # Add metric-specific stats for lab data
    print(f"\nLab Metrics (Good/Needs Improvement/Poor/No Data):")
    for metric in ['lab_lcp_score', 'lab_cls_score', 'lab_tbt_score']:
        metric_name = metric.split('_')[1].upper()
        good = len(df[df[metric] == 'good'])
        needs_improvement = len(df[df[metric] == 'needs improvement'])
        poor = len(df[df[metric] == 'poor'])
        no_data = len(df[df[metric] == 'no data'])
        
        print(f"{metric_name}: {good}/{needs_improvement}/{poor}/{no_data} " +
              f"({good/total_urls*100:.1f}%/{needs_improvement/total_urls*100:.1f}%/{poor/total_urls*100:.1f}%/{no_data/total_urls*100:.1f}%)")
    
    print(f"\nProcessing time: {elapsed_time:.1f} seconds ({elapsed_time/60:.1f} minutes)")
    print(f"CSV file '{output_filename}' has been downloaded.")
    print("=================================================")
else:
    print("\nNo valid results were obtained. Please check the API key and try again.")
