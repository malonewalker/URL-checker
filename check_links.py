import streamlit as st
import pandas as pd
import time
import re
import httpx
import asyncio
from urllib.parse import urlparse
from datetime import datetime, timedelta
import hashlib
import json

# --- AUTHENTICATION ---
st.title("🔍 URL Redirect Checker with Authentication")
password = st.text_input("Enter password:", type="password")
if password != "BPRFSR":
    st.warning("Please enter the correct password to continue.")
    st.stop()

# --- SESSION STATE CONTROL ---
if "run_check" not in st.session_state:
    st.session_state.run_check = False

# --- FILE UPLOAD ---
uploaded_file = st.file_uploader("Upload a file with URLs (.txt, .csv, .xlsx)", type=["txt", "csv", "xlsx"])

# --- URL HELPERS ---
URL_REGEX = re.compile(r"""(?i)\b((?:https?://|www\.)[^\s<>"]+|(?:https?://|www\.)\S+)""")

def normalize_url(u: str) -> str:
    u = u.strip()
    if not u:
        return u
    # Add scheme if missing (e.g., "www.example.com")
    if u.lower().startswith("www."):
        u = "https://" + u
    # Basic validation
    try:
        parsed = urlparse(u)
        if not parsed.scheme:
            u = "https://" + u
    except Exception:
        pass
    return u

def extract_urls_from_cell(value) -> list:
    """Return all URLs found in a cell (string)."""
    if pd.isna(value):
        return []
    s = str(value)
    matches = URL_REGEX.findall(s)
    return [normalize_url(m) for m in matches]

def dataframe_from_file(file) -> pd.DataFrame:
    """Read the uploaded file into a DataFrame, keeping all columns."""
    if file.name.endswith(".txt"):
        # Treat each line as a URL; preserve in a single-column DF
        lines = file.read().decode().splitlines()
        return pd.DataFrame({"URL": [normalize_url(l) for l in lines if l.strip()]})
    elif file.name.endswith(".csv"):
        return pd.read_csv(file)
    elif file.name.endswith(".xlsx"):
        return pd.read_excel(file)
    else:
        return pd.DataFrame()

def build_long_url_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scan every column for URLs. Return a *long* DF where each found URL becomes a row,
    preserving all original columns, plus 'Source Column' and 'URL'.
    """
    if df.empty:
        return df

    # If it's a TXT-derived DF with just 'URL', keep as-is
    if list(df.columns) == ["URL"]:
        out = df.copy()
        out["Source Column"] = "URL"
        return out

    rows = []
    for idx, row in df.iterrows():
        found = False
        for col in df.columns:
            urls = extract_urls_from_cell(row[col])
            for u in urls:
                found = True
                base = row.to_dict()
                base["Source Column"] = col
                base["URL"] = u
                rows.append(base)
        # If no URLs in the row, skip it entirely (we only check URLs)
    if not rows:
        return pd.DataFrame(columns=list(df.columns) + ["Source Column", "URL"])
    return pd.DataFrame(rows)

# --- CACHING ---
@st.cache_data(ttl=timedelta(hours=24))
def get_cached_results():
    """Initialize or return the cache dictionary."""
    return {}

def cache_key(url: str) -> str:
    """Generate a cache key for a URL."""
    return hashlib.md5(url.encode()).hexdigest()

# --- URL CHECKING ---
async def check_redirects_async(client: httpx.AsyncClient, url: str, semaphore: asyncio.Semaphore) -> tuple:
    """Check a single URL with concurrency control. Returns (url, result_dict)."""
    async with semaphore:
        # Add small delay for politeness (50-200ms jitter)
        await asyncio.sleep(0.05 + (0.00015 * (hash(url) % 1000)))
        
        # Retry logic for transient failures
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                response = await client.get(url, follow_redirects=True, timeout=20.0)
                
                # Build redirect chain
                history_urls = [str(r.url) for r in response.history]
                final_url = str(response.url)

                if history_urls:
                    full_chain = [url] + history_urls
                    if final_url != history_urls[-1]:
                        full_chain.append(final_url)
                else:
                    full_chain = [url, final_url]

                # Detect soft 404s (redirects to homepage/generic pages)
                original_parsed = urlparse(url)
                final_parsed = urlparse(final_url)
                
                # Only flag as soft 404 if:
                # 1. Same domain AND
                # 2. Path changed significantly (not just protocol/www/trailing slash)
                # 3. Final path is suspiciously short (likely homepage or error page)
                same_domain = original_parsed.netloc.replace('www.', '') == final_parsed.netloc.replace('www.', '')
                original_path = original_parsed.path.rstrip('/')
                final_path = final_parsed.path.rstrip('/')
                
                # Soft 404 if path changed AND final path is just "/" or very short
                path_changed_significantly = (original_path != final_path and 
                                             original_path != '' and 
                                             len(final_path) <= 1)
                homepage_redirect = same_domain and path_changed_significantly

                result = {
                    "Final URL": final_url,
                    "Status Code": response.status_code,
                    "Redirect Chain": " → ".join(full_chain),
                    "Soft 404 Suspected": homepage_redirect,
                    "Error Flag": homepage_redirect or (response.status_code not in [200, 201, 202, 203, 204]),
                }
                return url, result  # Success, return immediately
                
            except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                # Retry on timeout errors
                if attempt < max_retries:
                    await asyncio.sleep(1.0 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    result = {
                        "Final URL": "Timeout",
                        "Status Code": "Timeout",
                        "Redirect Chain": f"Request timed out after {max_retries + 1} attempts",
                        "Soft 404 Suspected": False,
                        "Error Flag": True,
                    }
            except Exception as e:
                # Other errors - don't retry
                result = {
                    "Final URL": "Error",
                    "Status Code": "Error",
                    "Redirect Chain": str(e),
                    "Soft 404 Suspected": False,
                    "Error Flag": True,
                }
                break
        
        return url, result

async def check_urls_concurrent(unique_urls: list, max_concurrent: int = 10) -> dict:
    """Check multiple URLs concurrently with a limit. Returns dict mapping url -> result."""
    semaphore = asyncio.Semaphore(max_concurrent)
    
    # Configure client with better settings for reliability
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    limits = httpx.Limits(max_keepalive_connections=max_concurrent, max_connections=max_concurrent * 2)
    
    async with httpx.AsyncClient(timeout=20.0, headers=headers, limits=limits, follow_redirects=True) as client:
        tasks = [check_redirects_async(client, url, semaphore) for url in unique_urls]
        results = await asyncio.gather(*tasks)
    
    # Convert list of tuples to dict
    return dict(results)

def check_urls_with_cache(unique_urls: list, progress_callback=None) -> dict:
    """
    Check unique URLs, using cache when available.
    Returns dict mapping url -> result.
    """
    cache = get_cached_results()
    
    # Separate cached and uncached URLs
    cached_results = {}
    urls_to_check = []
    
    for url in unique_urls:
        key = cache_key(url)
        if key in cache:
            cached_results[url] = cache[key]
        else:
            urls_to_check.append(url)
    
    st.write(f"📊 Found {len(cached_results)} cached results, checking {len(urls_to_check)} new URLs...")
    
    # Check uncached URLs
    if urls_to_check:
        new_results = asyncio.run(check_urls_concurrent(urls_to_check, max_concurrent=10))
        
        # Update cache
        for url, result in new_results.items():
            cache[cache_key(url)] = result
    else:
        new_results = {}
    
    # Combine results
    all_results = {**cached_results, **new_results}
    return all_results

# --- RUN CHECK BUTTON ---
if uploaded_file and st.button("Run URL Check"):
    st.session_state.run_check = True

# --- MAIN LOGIC ---
if uploaded_file and st.session_state.run_check:
    try:
        st.write("📂 Processing file...")
        source_df = dataframe_from_file(uploaded_file)
        st.write(f"✅ Loaded {len(source_df)} rows from file")
        
        urls_long_df = build_long_url_df(source_df)
        st.write(f"✅ Extracted URLs from file")

        if urls_long_df.empty:
            st.info("No URLs were detected in the uploaded file.")
            st.session_state.run_check = False
            st.stop()

        results = []
        # Get unique URLs to check
        unique_urls = urls_long_df["URL"].unique().tolist()
        
        st.write(f"✅ Found {len(urls_long_df)} URL occurrence(s), checking {len(unique_urls)} unique URL(s)...")
        progress_bar = st.progress(0)

        # Check unique URLs with caching and concurrency
        st.write("🔍 Starting URL checks...")
        url_results = check_urls_with_cache(unique_urls)
        st.write(f"✅ Completed checking {len(url_results)} URLs")
    
        progress_bar.progress(1.0)

        # Merge results back onto the long dataframe
        st.write("📊 Merging results...")
        results = []
        for i, row in urls_long_df.reset_index(drop=True).iterrows():
            url = row["URL"]
            result = url_results.get(url, {
                "Final URL": "Error",
                "Status Code": "Error",
                "Redirect Chain": "URL not checked",
                "Soft 404 Suspected": False,
                "Error Flag": True,
            })
            # merge original row (all columns) + results; also include Original URL for clarity
            merged = {**row.to_dict(), "Original URL": url, **result}
            results.append(merged)

        results_df = pd.DataFrame(results)

        # Reorder columns: original columns first, then metadata/results
        original_cols = [c for c in source_df.columns if c in results_df.columns]
        ordered_cols = original_cols + [c for c in ["Source Column", "URL", "Original URL", "Final URL",
                                                    "Status Code", "Redirect Chain",
                                                    "Soft 404 Suspected", "Error Flag"]
                                        if c in results_df.columns]
        results_df = results_df[ordered_cols]
        st.session_state.results_df = results_df
        st.session_state.run_check = False  # Reset to prevent re-running
        st.success("🎉 URL checking complete!")
        st.rerun()  # Force rerun to display results
        
    except Exception as e:
        st.error(f"❌ Error occurred: {str(e)}")
        st.exception(e)
        st.session_state.run_check = False

# --- RESULTS DISPLAY ---
if "results_df" in st.session_state:
    show_errors_only = st.checkbox("Show only error/redirect issues")
    display_df = st.session_state.results_df[st.session_state.results_df["Error Flag"]] if show_errors_only else st.session_state.results_df
    st.dataframe(display_df, use_container_width=True)

    # --- DOWNLOAD ---
    csv_download = st.session_state.results_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download Full Results as CSV", data=csv_download, file_name="url_check_results.csv", mime="text/csv")
