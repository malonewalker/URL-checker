import requests
import pandas as pd
import streamlit as st
import time
from io import StringIO

# --- Utility Functions ---
def check_link_status(url):
    try:
        session = requests.Session()
        response = session.get(url, allow_redirects=True, timeout=10)
        redirect_chain = [resp.url for resp in response.history] + [response.url]
        return response.status_code, redirect_chain, response.text
    except requests.RequestException as e:
        return None, [url], str(e)

def is_soft_404(content):
    soft_404_phrases = ["page not found", "404", "sorry", "doesn't exist", "not available"]
    content_lower = content.lower()
    return any(phrase in content_lower for phrase in soft_404_phrases)

# --- Streamlit App ---
st.title("🔗 Soft 404 URL Checker")
st.markdown("Upload a `.txt` or `.csv` file with one URL per line or column.")

uploaded_file = st.file_uploader("Upload file", type=["txt", "csv"])

rate_limit = st.slider("Delay between requests (seconds)", min_value=0.0, max_value=5.0, value=1.0, step=0.1)

if uploaded_file is not None:
    # Parse file
    if uploaded_file.name.endswith(".txt"):
        content = uploaded_file.read().decode("utf-8")
        links = [line.strip() for line in content.splitlines() if line.strip()]
    elif uploaded_file.name.endswith(".csv"):
        df_input = pd.read_csv(uploaded_file)
        links = df_input.iloc[:, 0].dropna().astype(str).tolist()

    st.info(f"✅ {len(links)} links loaded. Checking...")

    # Set up progress UI
    progress_bar = st.progress(0)
    status_text = st.empty()

    results = []

    for i, link in enumerate(links, start=1):
        status, path, content_or_error = check_link_status(link)
        time.sleep(rate_limit)  # ⏱️ Rate limiting

        if status is None:
            notes = content_or_error
            final_url = ""
            full_path = " > ".join(path)
            status_display = "ERROR"
        else:
            final_url = path[-1]
            full_path = " > ".join(path)

            if 300 <= status < 400:
                notes = f"Redirect {status}"
            elif status == 200 and is_soft_404(content_or_error):
                notes = "Soft 404 detected in page content"
            elif status == 200:
                notes = "OK"
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

        # Update progress
        progress = i / len(links)
        progress_bar.progress(progress)
        status_text.text(f"Checked {i} of {len(links)} links")

    st.success("✅ Done checking all links.")
    df = pd.DataFrame(results)
    st.dataframe(df)

    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download Results as CSV", csv, "link_report.csv", "text/csv")
