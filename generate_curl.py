import csv
import json
import os

from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.environ["BRIGHTDATA_API_KEY"]
DATASET_ID = "gd_m7aof0k82r803d5bjm"
URL = "https://chatgpt.com/"
API_URL = f"https://api.brightdata.com/datasets/v3/scrape?dataset_id={DATASET_ID}&notify=false&include_errors=true"
OUTPUT_FILE = "brightdata_curl.txt"
PROMPTS_FILE = "prompts.csv"

inputs = []
with open(PROMPTS_FILE, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        inputs.append({
            "url": URL,
            "prompt": row["prompt"],
            "country": "",
            "web_search": True,
            "additional_prompt": ""
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
