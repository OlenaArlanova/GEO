import os

import requests


def _slack(token, method, **kwargs):
    resp = requests.post(
        f"https://slack.com/api/{method}",
        headers={"Authorization": f"Bearer {token}"},
        **kwargs,
    )
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Slack {method} failed: {result.get('error')}")
    return result


def post_image(image_path, date_str):
    token = os.environ["SLACK_BOT_TOKEN"]
    channel = os.environ["SLACK_CHANNEL"]

    file_size = os.path.getsize(image_path)

    result = _slack(token, "files.getUploadURLExternal", data={
        "filename": "dashboard.png",
        "length": file_size,
    })
    upload_url = result["upload_url"]
    file_id = result["file_id"]

    with open(image_path, "rb") as f:
        requests.post(upload_url, data=f).raise_for_status()

    _slack(token, "files.completeUploadExternal", json={
        "files": [{"id": file_id}],
        "channel_id": channel,
        "initial_comment": f"Warmy GEO Daily — {date_str}",
    })
