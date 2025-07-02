import streamlit as st
import pandas as pd
import time
import requests
from urllib.parse import urlparse

# --- AUTHENTICATION ---
st.title("🔍 URL Redirect Checker with Authentication")
password = st.text_input("Enter password:", type="password")
if password != "BPRFSR":
    st.warning("Please enter the correct password to continue.")
    st.stop()

# --- SESSION STATE CONTROL ---
if "run_check" not in st.session_state:
    st.session_state.run_check = False

# --- FILE UPLOAD AND TOGGLE ---
uploaded_file = st.file_uploader("Upload a file with URLs (.txt, .csv, .xlsx)", type=["txt", "csv", "xlsx"])
delay_toggle = st.toggle("Add 1 second delay between URL checks")

# --- URL PARSING ---
def extract_urls(file):
    if file.name.endswith('.txt'):
        urls = file.read().decode().splitlines()
    elif file.name.endswith('.csv'):
        df = pd.read_csv(file)
        urls = df.iloc[:, 0].dropna().tolist()
    elif file.name.endswith('.xlsx'):
        df = pd.read_excel(file)
        urls = df.iloc[:, 0].dropna().tolist()
    else:
        urls = []
    return list(set(urls))  # Remove duplicates

# --- URL CHECKING ---
def check_redirects(url):
    try:
        response = requests.get(url, allow_redirects=True, timeout=10)
        history_urls = [resp.url for resp in response.history]
        final_url = response.url

        if history_urls:
            full_chain = [url] + history_urls
            if final_url != history_urls[-1]:
                full_chain.append(final_url)
        else:
            full_chain = [url, final_url]

        original_netloc = urlparse(url).netloc
        final_netloc = urlparse(final_url).netloc
        homepage_redirect = (original_netloc == final_netloc and url != final_url)

        return {
            "Original URL": url,
            "Final URL": final_url,
            "Status Code": response.status_code,
            "Redirect Chain": " → ".join(full_chain),
            "Soft 404 Suspected": homepage_redirect,
            "Error Flag": homepage_redirect or (response.status_code != 200)
        }
    except Exception as e:
        return {
            "Original URL": url,
            "Final URL": "Error",
            "Status Code": "Error",
            "Redirect Chain": str(e),
            "Soft 404 Suspected": False,
            "Error Flag": True
        }

# --- RUN CHECK BUTTON ---
if uploaded_file and st.button("Run URL Check"):
    st.session_state.run_check = True

# --- MAIN LOGIC ---
if uploaded_file and st.session_state.run_check:
    urls = extract_urls(uploaded_file)
    results = []

    st.write(f"✅ Checking {len(urls)} URLs...")
    progress_bar = st.progress(0)

    for i, url in enumerate(urls):
        result = check_redirects(url)
        results.append(result)
        if delay_toggle:
            time.sleep(1)
        progress_bar.progress((i + 1) / len(urls))

    results_df = pd.DataFrame(results)
    st.session_state.results_df = results_df
    st.success("🎉 URL checking complete.")

# --- RESULTS DISPLAY ---
if "results_df" in st.session_state:
    show_errors_only = st.checkbox("Show only error/redirect issues")
    display_df = st.session_state.results_df[st.session_state.results_df["Error Flag"]] if show_errors_only else st.session_state.results_df
    st.dataframe(display_df)

    # --- DOWNLOAD ---
    csv_download = st.session_state.results_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download Full Results as CSV", data=csv_download, file_name="url_check_results.csv", mime="text/csv")
