import requests
import json
import pandas as pd
import time
from google.colab import files
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

if url_source_choice == '2':
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
    
    # Try to determine domain from first URL for naming the output file
    if urls:
        try:
            domain_parts = urls[0].replace('https://', '').replace('http://', '').split('/')
            domain = domain_parts[0]
        except:
            domain = "custom"
else:
    # Default to option 1 (sitemap) if anything else is entered
    # Get domain for sitemap
    domain = input("\nEnter the domain to analyze (e.g., https://www.example.com): ")
    if not domain.startswith(('http://', 'https://')):
        domain = 'https://' + domain
    
    print(f"\nFetching sitemap from {domain}...")
    
    # Get URLs from sitemap
    try:
        sitemap_url = f"{domain}/sitemap.xml"
        response = requests.get(sitemap_url)
        if response.status_code == 200:
            # Extract URLs using regex (simple approach)
            urls = re.findall(r'<loc>(.*?)</loc>', response.text)
            print(f"Found {len(urls)} URLs in sitemap.")
        else:
            print(f"Failed to fetch sitemap: {response.status_code}")
    except Exception as e:
        print(f"Error fetching sitemap: {e}")
    
    # If sitemap approach fails, use a few known pages
    if not urls:
        print("Couldn't get URLs from sitemap. Using domain and some common paths.")
        urls = [
            domain,
            f"{domain}/about",
            f"{domain}/contact",
            f"{domain}/services",
            f"{domain}/blog"
        ]

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

# Form factor selection
print("\nSelect form factor for CrUX data:")
print("1. All form factors (Default)")
print("2. Mobile only (PHONE)")
print("3. Desktop only (DESKTOP)")
print("4. Tablet only (TABLET)")

form_factor_choice = input("Enter your choice (1-4): ").strip()

# Set form factor based on user choice
if form_factor_choice == '2':
    FORM_FACTOR = 'PHONE'
    print("Selected: Mobile phones only")
elif form_factor_choice == '3':
    FORM_FACTOR = 'DESKTOP'
    print("Selected: Desktop computers only")
elif form_factor_choice == '4':
    FORM_FACTOR = 'TABLET'
    print("Selected: Tablet devices only")
elif form_factor_choice == '' or form_factor_choice == '1':
    FORM_FACTOR = None
    print("Selected: All form factors")
else:
    # For any other invalid input
    FORM_FACTOR = None
    print("Invalid choice. Defaulting to: All form factors")

# Function to get data from CrUX API for a specific URL
def get_crux_data(url):
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    # Create payload based on form factor selection
    if FORM_FACTOR:
        data = {
            'url': url,
            'formFactor': FORM_FACTOR
        }
    else:
        data = {
            'url': url
        }
    
    # Debug info for first request
    if not hasattr(get_crux_data, 'counter'):
        get_crux_data.counter = 0
    
    if get_crux_data.counter == 0:
        print(f"\nDebug - API Request payload: {json.dumps(data)}")
        print(f"Debug - Form factor selected: {FORM_FACTOR if FORM_FACTOR else 'ALL'}")
    
    response = requests.post(f"{API_URL}?key={API_KEY}", headers=headers, json=data)
    
    if get_crux_data.counter == 0:
        print(f"Debug - API Response status: {response.status_code}")
        print(f"Debug - API Response preview: {response.text[:300]}...")
        get_crux_data.counter += 1
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching data for {url}: {response.status_code}")
        if get_crux_data.counter <= 2:
            print(f"Error response: {response.text}")
            get_crux_data.counter += 1
        return None

# Function to determine if Core Web Vitals are passed
def check_cwv_status(lcp_status, cls_status, inp_status):
    if lcp_status == "good" and cls_status == "good" and inp_status == "good":
        return "passed"
    elif lcp_status == "unknown" or cls_status == "unknown" or inp_status == "unknown":
        return "no data"
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
        return {
            'lcp_value': None,
            'lcp_good_pct': None,
            'lcp_ni_pct': None,
            'lcp_poor_pct': None,
            
            'cls_value': None,
            'cls_good_pct': None,
            'cls_ni_pct': None,
            'cls_poor_pct': None,
            
            'fcp_value': None,
            'fcp_good_pct': None,
            'fcp_ni_pct': None,
            'fcp_poor_pct': None,
            
            'fid_value': None,
            'fid_good_pct': None,
            'fid_ni_pct': None,
            'fid_poor_pct': None,
            
            'inp_value': None,
            'inp_good_pct': None,
            'inp_ni_pct': None,
            'inp_poor_pct': None,
            
            'ttfb_value': None,
            'ttfb_good_pct': None,
            'ttfb_ni_pct': None,
            'ttfb_poor_pct': None
        }
    
    metrics = data['record']['metrics']
    results = {}
    
    # Extract LCP
    if 'largest_contentful_paint' in metrics:
        lcp_metric = metrics['largest_contentful_paint']
        results['lcp_value'] = lcp_metric.get('percentiles', {}).get('p75')
        
        # Distribution
        if 'histogram' in lcp_metric:
            lcp_hist = lcp_metric['histogram']
            results['lcp_good_pct'] = lcp_hist[0].get('density', 0) * 100
            results['lcp_ni_pct'] = lcp_hist[1].get('density', 0) * 100
            results['lcp_poor_pct'] = lcp_hist[2].get('density', 0) * 100
        else:
            results['lcp_good_pct'] = None
            results['lcp_ni_pct'] = None
            results['lcp_poor_pct'] = None
    else:
        results['lcp_value'] = None
        results['lcp_good_pct'] = None
        results['lcp_ni_pct'] = None
        results['lcp_poor_pct'] = None
    
    # Extract CLS
    if 'cumulative_layout_shift' in metrics:
        cls_metric = metrics['cumulative_layout_shift']
        results['cls_value'] = cls_metric.get('percentiles', {}).get('p75')
        
        # Distribution
        if 'histogram' in cls_metric:
            cls_hist = cls_metric['histogram']
            results['cls_good_pct'] = cls_hist[0].get('density', 0) * 100
            results['cls_ni_pct'] = cls_hist[1].get('density', 0) * 100
            results['cls_poor_pct'] = cls_hist[2].get('density', 0) * 100
        else:
            results['cls_good_pct'] = None
            results['cls_ni_pct'] = None
            results['cls_poor_pct'] = None
    else:
        results['cls_value'] = None
        results['cls_good_pct'] = None
        results['cls_ni_pct'] = None
        results['cls_poor_pct'] = None
    
    # Extract FCP
    if 'first_contentful_paint' in metrics:
        fcp_metric = metrics['first_contentful_paint']
        results['fcp_value'] = fcp_metric.get('percentiles', {}).get('p75')
        
        # Distribution
        if 'histogram' in fcp_metric:
            fcp_hist = fcp_metric['histogram']
            results['fcp_good_pct'] = fcp_hist[0].get('density', 0) * 100
            results['fcp_ni_pct'] = fcp_hist[1].get('density', 0) * 100
            results['fcp_poor_pct'] = fcp_hist[2].get('density', 0) * 100
        else:
            results['fcp_good_pct'] = None
            results['fcp_ni_pct'] = None
            results['fcp_poor_pct'] = None
    else:
        results['fcp_value'] = None
        results['fcp_good_pct'] = None
        results['fcp_ni_pct'] = None
        results['fcp_poor_pct'] = None
    
    # Extract FID
    if 'first_input_delay' in metrics:
        fid_metric = metrics['first_input_delay']
        results['fid_value'] = fid_metric.get('percentiles', {}).get('p75')
        
        # Distribution
        if 'histogram' in fid_metric:
            fid_hist = fid_metric['histogram']
            results['fid_good_pct'] = fid_hist[0].get('density', 0) * 100
            results['fid_ni_pct'] = fid_hist[1].get('density', 0) * 100
            results['fid_poor_pct'] = fid_hist[2].get('density', 0) * 100
        else:
            results['fid_good_pct'] = None
            results['fid_ni_pct'] = None
            results['fid_poor_pct'] = None
    else:
        results['fid_value'] = None
        results['fid_good_pct'] = None
        results['fid_ni_pct'] = None
        results['fid_poor_pct'] = None
    
    # Extract INP
    if 'interaction_to_next_paint' in metrics:
        inp_metric = metrics['interaction_to_next_paint']
        results['inp_value'] = inp_metric.get('percentiles', {}).get('p75')
        
        # Distribution
        if 'histogram' in inp_metric:
            inp_hist = inp_metric['histogram']
            results['inp_good_pct'] = inp_hist[0].get('density', 0) * 100
            results['inp_ni_pct'] = inp_hist[1].get('density', 0) * 100
            results['inp_poor_pct'] = inp_hist[2].get('density', 0) * 100
        else:
            results['inp_good_pct'] = None
            results['inp_ni_pct'] = None
            results['inp_poor_pct'] = None
    else:
        results['inp_value'] = None
        results['inp_good_pct'] = None
        results['inp_ni_pct'] = None
        results['inp_poor_pct'] = None
    
    # Extract TTFB
    if 'experimental_time_to_first_byte' in metrics:
        ttfb_metric = metrics['experimental_time_to_first_byte']
        results['ttfb_value'] = ttfb_metric.get('percentiles', {}).get('p75')
        
        # Distribution
        if 'histogram' in ttfb_metric:
            ttfb_hist = ttfb_metric['histogram']
            results['ttfb_good_pct'] = ttfb_hist[0].get('density', 0) * 100
            results['ttfb_ni_pct'] = ttfb_hist[1].get('density', 0) * 100
            results['ttfb_poor_pct'] = ttfb_hist[2].get('density', 0) * 100
        else:
            results['ttfb_good_pct'] = None
            results['ttfb_ni_pct'] = None
            results['ttfb_poor_pct'] = None
    else:
        results['ttfb_value'] = None
        results['ttfb_good_pct'] = None
        results['ttfb_ni_pct'] = None
        results['ttfb_poor_pct'] = None
    
    return results

# Main process
print(f"\nStarting CrUX data collection for {len(urls)} URLs")

# Prepare data structure
results = []
successful_urls = 0

# Process each URL
for i, url in enumerate(urls):
    print(f"Processing {i+1}/{len(urls)}: {url}")
    
    # Debug output for first URL to confirm form factor setting
    if i == 0:
        print(f"Using form factor: {FORM_FACTOR if FORM_FACTOR else 'ALL'}")
    
    data = get_crux_data(url)
    if data and 'record' in data and 'metrics' in data['record']:
        successful_urls += 1
        metrics_data = extract_metrics(data)
        
        # Categorize metrics
        lcp_status = categorize_metric(metrics_data['lcp_value'], "LCP")
        cls_status = categorize_metric(metrics_data['cls_value'], "CLS")
        fcp_status = categorize_metric(metrics_data['fcp_value'], "FCP")
        fid_status = categorize_metric(metrics_data['fid_value'], "FID")
        inp_status = categorize_metric(metrics_data['inp_value'], "INP")
        ttfb_status = categorize_metric(metrics_data['ttfb_value'], "TTFB")
        
        # Determine Core Web Vitals status (using INP instead of FID as per 2024 CWV)
        cwv_status = check_cwv_status(lcp_status, cls_status, inp_status)
        
        # Get form factor from response or use selected form factor
        form_factor = data.get('record', {}).get('key', {}).get('formFactor', FORM_FACTOR if FORM_FACTOR else "ALL")
        
        results.append({
            "url": url,
            "form_factor": form_factor,
            "core_web_vitals_status": cwv_status,
            
            "lcp_status": lcp_status,
            "lcp_value_ms": metrics_data['lcp_value'],
            "lcp_good_pct": metrics_data['lcp_good_pct'],
            "lcp_ni_pct": metrics_data['lcp_ni_pct'],
            "lcp_poor_pct": metrics_data['lcp_poor_pct'],
            
            "cls_status": cls_status,
            "cls_value": metrics_data['cls_value'],
            "cls_good_pct": metrics_data['cls_good_pct'],
            "cls_ni_pct": metrics_data['cls_ni_pct'],
            "cls_poor_pct": metrics_data['cls_poor_pct'],
            
            "fcp_status": fcp_status,
            "fcp_value_ms": metrics_data['fcp_value'],
            "fcp_good_pct": metrics_data['fcp_good_pct'],
            "fcp_ni_pct": metrics_data['fcp_ni_pct'],
            "fcp_poor_pct": metrics_data['fcp_poor_pct'],
            
            "fid_status": fid_status,
            "fid_value_ms": metrics_data['fid_value'],
            "fid_good_pct": metrics_data['fid_good_pct'],
            "fid_ni_pct": metrics_data['fid_ni_pct'],
            "fid_poor_pct": metrics_data['fid_poor_pct'],
            
            "inp_status": inp_status,
            "inp_value_ms": metrics_data['inp_value'],
            "inp_good_pct": metrics_data['inp_good_pct'],
            "inp_ni_pct": metrics_data['inp_ni_pct'],
            "inp_poor_pct": metrics_data['inp_poor_pct'],
            
            "ttfb_status": ttfb_status,
            "ttfb_value_ms": metrics_data['ttfb_value'],
            "ttfb_good_pct": metrics_data['ttfb_good_pct'],
            "ttfb_ni_pct": metrics_data['ttfb_ni_pct'],
            "ttfb_poor_pct": metrics_data['ttfb_poor_pct']
        })
    else:
        # Add a row for URLs that failed to fetch data
        results.append({
            "url": url,
            "form_factor": FORM_FACTOR if FORM_FACTOR else "ALL",
            "core_web_vitals_status": "no data",
            
            "lcp_status": "no data",
            "lcp_value_ms": None,
            "lcp_good_pct": None,
            "lcp_ni_pct": None,
            "lcp_poor_pct": None,
            
            "cls_status": "no data",
            "cls_value": None,
            "cls_good_pct": None,
            "cls_ni_pct": None,
            "cls_poor_pct": None,
            
            "fcp_status": "no data",
            "fcp_value_ms": None,
            "fcp_good_pct": None,
            "fcp_ni_pct": None,
            "fcp_poor_pct": None,
            
            "fid_status": "no data",
            "fid_value_ms": None,
            "fid_good_pct": None,
            "fid_ni_pct": None,
            "fid_poor_pct": None,
            
            "inp_status": "no data",
            "inp_value_ms": None,
            "inp_good_pct": None,
            "inp_ni_pct": None,
            "inp_poor_pct": None,
            
            "ttfb_status": "no data",
            "ttfb_value_ms": None,
            "ttfb_good_pct": None,
            "ttfb_ni_pct": None,
            "ttfb_poor_pct": None
        })
    
    # Add a small delay to avoid rate limiting
    time.sleep(1)
    
    # Provide progress update every 10 URLs
    if (i + 1) % 10 == 0:
        print(f"Progress: {i+1}/{len(urls)} URLs processed. Found {successful_urls} URLs in CrUX database.")

# Create DataFrame
df = pd.DataFrame(results)

# Save to CSV
form_factor_str = FORM_FACTOR if FORM_FACTOR else "ALL"
domain_name = domain.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0] if domain else "custom"
csv_filename = f"crux_data_{domain_name}_{form_factor_str}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
df.to_csv(csv_filename, index=False)

# Download the CSV file
files.download(csv_filename)

print(f"\nProcessing complete!")
print(f"Processed {len(urls)} URLs")
print(f"Found {successful_urls} URLs in CrUX database")
print(f"CSV file '{csv_filename}' has been downloaded.")
print(f"Form factor used: {FORM_FACTOR if FORM_FACTOR else 'ALL'}")

# Print summary of results
if successful_urls > 0:
    passed = len(df[df['core_web_vitals_status'] == 'passed'])
    failed = len(df[df['core_web_vitals_status'] == 'failed'])
    no_data = len(df[df['core_web_vitals_status'] == 'no data'])
    
    print("\nCore Web Vitals Summary:")
    print(f"Passed: {passed} ({passed/len(urls)*100:.1f}%)")
    print(f"Failed: {failed} ({failed/len(urls)*100:.1f}%)")
    print(f"No data: {no_data} ({no_data/len(urls)*100:.1f}%)")
    
    # Print metric-specific summaries
    print("\nMetric Performance Summary:")
    
    # LCP Summary
    lcp_good = df[df['lcp_status'] == 'good'].shape[0]
    lcp_ni = df[df['lcp_status'] == 'needs improvement'].shape[0]
    lcp_poor = df[df['lcp_status'] == 'poor'].shape[0]
    print(f"LCP: {lcp_good} good, {lcp_ni} needs improvement, {lcp_poor} poor")
    
    # CLS Summary
    cls_good = df[df['cls_status'] == 'good'].shape[0]
    cls_ni = df[df['cls_status'] == 'needs improvement'].shape[0]
    cls_poor = df[df['cls_status'] == 'poor'].shape[0]
    print(f"CLS: {cls_good} good, {cls_ni} needs improvement, {cls_poor} poor")
    
    # INP Summary (new Core Web Vital)
    inp_good = df[df['inp_status'] == 'good'].shape[0]
    inp_ni = df[df['inp_status'] == 'needs improvement'].shape[0]
    inp_poor = df[df['inp_status'] == 'poor'].shape[0]
    print(f"INP: {inp_good} good, {inp_ni} needs improvement, {inp_poor} poor")
else:
    print("\nNo URLs with CrUX data were found. Possible reasons:")
    print("1. The URLs may not have enough traffic to be included in CrUX")
    print("2. The selected form factor may not have sufficient data")
    print("3. There might be an issue with the API key or request format")
    
    print("\nTry these solutions:")
    print("- Use 'All form factors' instead of a specific device type")
    print("- Check that your API key has access to the Chrome UX Report API")
    print("- Verify the URLs are publicly accessible and have been for at least 28 days")
    print("- Try more popular URLs from the site that are likely to have more traffic")
