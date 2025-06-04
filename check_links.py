import requests
import csv

def read_links_from_file(filename):
    with open(filename, "r") as file:
        return [line.strip() for line in file if line.strip()]

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

def main():
    input_file = "links.txt"
    output_csv = "link_report.csv"
    links = read_links_from_file(input_file)

    print(f"🔍 Checking {len(links)} links...\n")

    # Prepare CSV file
    with open(output_csv, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["Original Link", "Status", "Final URL", "Redirect Path", "Notes"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for link in links:
            status, path, content_or_error = check_link_status(link)

            if status is None:
                print(f"[🚫 EXCEPTION] {link} → {content_or_error}")
                writer.writerow({
                    "Original Link": link,
                    "Status": "ERROR",
                    "Final URL": "",
                    "Redirect Path": " > ".join(path),
                    "Notes": content_or_error
                })
                continue

            final_url = path[-1]
            full_path = " > ".join(path)

            if 300 <= status < 400:
                print(f"[↪️ REDIRECT {status}] {link} → {final_url}")
                notes = f"Redirect {status}"
            elif status == 200 and is_soft_404(content_or_error):
                print(f"[❌ SOFT 404] {link} → {final_url}")
                notes = "Soft 404 detected in page content"
            elif status == 200:
                print(f"[✅ OK] {link} → {final_url}")
                notes = "OK"
            else:
                print(f"[❌ ERROR {status}] {link} → {final_url}")
                notes = f"Error status {status}"

            writer.writerow({
                "Original Link": link,
                "Status": status,
                "Final URL": final_url,
                "Redirect Path": full_path,
                "Notes": notes
            })

    print(f"\n✅ Finished! Results saved to: {output_csv}")

if __name__ == "__main__":
    main()
