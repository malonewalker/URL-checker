import requests
import pandas as pd
import streamlit as st
import time
from io import StringIO
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Utility Functions ---
def check_link_status(url):
    try:
        session = requests.Session()
        retries = Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        response = session.get(url, allow_redirects=True, timeout=10)
        redirect_chain = [resp.url for resp in response.history] + [response.url]
        return response.status_code, redirect_chain, response.text
    except requests.RequestException as e:
        return None, [url], str(e)

def is_soft_404(content):
    soft_404_phrases = [
        "404 not found", "page not found", "this page does not exist",
        "we're sorry, the page", "not available", "content has been removed"
    ]
    content_lower = content.lower()
    return any(phrase in content_lower for phrase in content_lower.splitlines()[:20] for phrase in soft_404_phrases)

# --- Streamlit App ---
st.title("🔗 Soft 404 URL Checker")
st.markdown("Upload a `.txt` or `.csv` file containing a list of URLs.")

uploaded_file = st.file_uploader("Upload file", type=["txt", "csv"])
rate_limit = st.slider("Delay between requests (seconds)", min_value=0.0, max_value=5.0, value=1.0, step=0.1)

if uploaded_file is not None:
    # --- Parse File ---
    if uploaded_file.name.endswith(".txt"):
        content = uploaded_file.read().decode("utf-8")
        links = [line.strip() for line in content.splitlines() if line.strip()]
    elif uploaded_file.name.endswith(".csv"):
        df_csv = pd.read_csv(uploaded_file)
        st.write("CSV preview:")
        st.dataframe(df_csv.head())
        url_column = st.selectbox("Select the column containing URLs", df_csv.columns)
        links = df_csv[url_column].dropna().astype(str).tolist()

    if not links:
        st.warning("No valid URLs found.")
    else:
        st.info(f"✅ {len(links)} links loaded. Starting check...")

        # --- Check Links ---
        progress_bar = st.progress(0)
        status_placeholder = st.empty()
        results = []

        for i, link in enumerate(links, start=1):
            status, path, content_or_error = check_link_status(link)
            time.sleep(rate_limit)

            final_url = path[-1] if status else ""
            full_path = " > ".join(path)

            if status is None:
                notes = content_or_error
                status_display = "ERROR"
            elif 300 <= status < 400:
                notes = f"Redirect {status}"
                status_display = status
            elif status == 200 and is_soft_404(content_or_error):
                notes = "Soft 404 detected in page content"
                status_display = status
            elif status == 200:
                notes = "OK"
                status_display = status
            else:
                notes = f"Error status {status}"
                status_display = status

            results.append({
                "Original Link": link,
                "Status": status_display,
                "Final URL": final_url,
                "Redirect Path": full_path,
                "Notes": notes
            })

            # Update UI
            progress_bar.progress(i / len(links))
            status_placeholder.text(f"Checked {i}/{len(links)}")

        # --- Show Results ---
        st.success("✅ Done checking all links.")
        df_results = pd.DataFrame(results)
        st.dataframe(df_results)

        csv = df_results.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download Results as CSV", csv, "link_report.csv", "application/octet-stream")
