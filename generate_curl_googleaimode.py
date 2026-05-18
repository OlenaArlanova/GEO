import csv
import json
import os

from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.environ["BRIGHTDATA_API_KEY"]
DATASET_ID = "gd_mcswdt6z2elth3zqr2"
URL = "https://google.com/aimode"
API_URL = f"https://api.brightdata.com/datasets/v3/scrape?dataset_id={DATASET_ID}&notify=false&include_errors=true"
OUTPUT_FILE = "brightdata_curl_googleaimode.txt"
PROMPTS_FILE = "prompts.csv"

inputs = []
with open(PROMPTS_FILE, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        inputs.append({
            "url": URL,
            "prompt": row["prompt"],
            "country": "",
        })

payload = json.dumps({"input": inputs})

curl_cmd = (
    f"curl -H \"Authorization: Bearer {API_TOKEN}\" "
    f"-H \"Content-Type: application/json\" "
    f"-d '{payload}' "
    f"\"{API_URL}\""
)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(curl_cmd)

print(f"Done. {len(inputs)} prompts written to {OUTPUT_FILE}")
