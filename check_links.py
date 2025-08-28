import streamlit as st
import pandas as pd
import time
import re
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

# --- URL CHECKING ---
def check_redirects(url: str) -> dict:
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
            "Final URL": final_url,
            "Status Code": response.status_code,
            "Redirect Chain": " → ".join(full_chain),
            "Soft 404 Suspected": homepage_redirect,
            "Error Flag": homepage_redirect or (response.status_code != 200),
        }
    except Exception as e:
        return {
            "Final URL": "Error",
            "Status Code": "Error",
            "Redirect Chain": str(e),
            "Soft 404 Suspected": False,
            "Error Flag": True,
        }

# --- RUN CHECK BUTTON ---
if uploaded_file and st.button("Run URL Check"):
    st.session_state.run_check = True

# --- MAIN LOGIC ---
if uploaded_file and st.session_state.run_check:
    source_df = dataframe_from_file(uploaded_file)
    urls_long_df = build_long_url_df(source_df)

    if urls_long_df.empty:
        st.info("No URLs were detected in the uploaded file.")
        st.stop()

    results = []
    st.write(f"✅ Checking {len(urls_long_df)} URL occurrence(s) across all columns...")
    progress_bar = st.progress(0)

    for i, row in urls_long_df.reset_index(drop=True).iterrows():
        url = row["URL"]
        result = check_redirects(url)
        # merge original row (all columns) + results; also include Original URL for clarity
        merged = {**row.to_dict(), "Original URL": url, **result}
        results.append(merged)

        if delay_toggle:
            time.sleep(1)
        progress_bar.progress((i + 1) / len(urls_long_df))

    results_df = pd.DataFrame(results)

    # Reorder columns: original columns first, then metadata/results
    original_cols = [c for c in source_df.columns if c in results_df.columns]
    ordered_cols = original_cols + [c for c in ["Source Column", "URL", "Original URL", "Final URL",
                                                "Status Code", "Redirect Chain",
                                                "Soft 404 Suspected", "Error Flag"]
                                    if c in results_df.columns]
    results_df = results_df[ordered_cols]
    st.session_state.results_df = results_df
    st.success("🎉 URL checking complete.")

# --- RESULTS DISPLAY ---
if "results_df" in st.session_state:
    show_errors_only = st.checkbox("Show only error/redirect issues")
    display_df = st.session_state.results_df[st.session_state.results_df["Error Flag"]] if show_errors_only else st.session_state.results_df
    st.dataframe(display_df, use_container_width=True)

    # --- DOWNLOAD ---
    csv_download = st.session_state.results_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download Full Results as CSV", data=csv_download, file_name="url_check_results.csv", mime="text/csv")
