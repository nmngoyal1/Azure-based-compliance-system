import os
import time
import logging
import requests
import yt_dlp
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("video-indexer")


class VideoIndexerService:
    """
    IMPORTANT:
    - AZURE_VI_ACCOUNT_ID  = Video Indexer Account GUID (used in api.videoindexer.ai URL)
    - AZURE_VI_ACCOUNT_NAME = Azure ARM resource NAME for the Video Indexer account
      (used in management.azure.com .../providers/Microsoft.VideoIndexer/accounts/{NAME})
    """

    def __init__(self):
        # VI API account GUID (used in api.videoindexer.ai endpoint)
        self.account_id = os.getenv("AZURE_VI_ACCOUNT_ID")

        # Azure region/location for Video Indexer API URLs (e.g., "trial", "eastus", "westeurope")
        self.location = os.getenv("AZURE_VI_LOCATION")

        # Azure subscription + resource group where the ARM resource exists
        self.subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
        self.resource_group = os.getenv("AZURE_RESOURCE_GROUP")

        # ARM resource NAME of the Video Indexer account (from Azure Portal)
        self.vi_account_name = os.getenv("AZURE_VI_ACCOUNT_NAME")

        # Better local dev behavior: skip Managed Identity probing on your Mac
        self.credential = DefaultAzureCredential(exclude_managed_identity_credential=True)

        self._validate_config()

    def _validate_config(self):
        missing = []
        for k, v in [
            ("AZURE_VI_ACCOUNT_ID", self.account_id),
            ("AZURE_VI_LOCATION", self.location),
            ("AZURE_SUBSCRIPTION_ID", self.subscription_id),
            ("AZURE_RESOURCE_GROUP", self.resource_group),
            ("AZURE_VI_ACCOUNT_NAME", self.vi_account_name),
        ]:
            if not v:
                missing.append(k)

        if missing:
            raise ValueError(
                "Missing required environment variables: " + ", ".join(missing) +
                "\n\nSet them in your .env, for example:\n"
                "AZURE_RESOURCE_GROUP=brand-guardian-rg\n"
                "AZURE_VI_ACCOUNT_NAME=brand-guardian-rg   # ARM resource name\n"
                "AZURE_VI_ACCOUNT_ID=<GUID>               # VI account GUID\n"
                "AZURE_VI_LOCATION=<trial/eastus/...>\n"
                "AZURE_SUBSCRIPTION_ID=<sub-id>\n"
            )

    def get_access_token(self) -> str:
        """Generates an ARM Access Token for management.azure.com."""
        try:
            token_object = self.credential.get_token("https://management.azure.com/.default")
            return token_object.token
        except Exception as e:
            logger.error(f"Failed to get Azure Token: {e}")
            raise

    def get_account_token(self, arm_access_token: str) -> str:
        """
        Exchanges ARM token for Video Indexer Account Token using ARM generateAccessToken endpoint.
        Uses ARM account resource NAME (AZURE_VI_ACCOUNT_NAME).
        """
        url = (
            f"https://management.azure.com/subscriptions/{self.subscription_id}"
            f"/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.VideoIndexer/accounts/{self.vi_account_name}"
            f"/generateAccessToken?api-version=2024-01-01"
        )
        headers = {"Authorization": f"Bearer {arm_access_token}"}
        payload = {"permissionType": "Contributor", "scope": "Account"}

        response = requests.post(url, headers=headers, json=payload, timeout=60)
        if response.status_code != 200:
            raise Exception(f"Failed to get VI Account Token: {response.text}")

        token = response.json().get("accessToken")
        if not token:
            raise Exception(f"VI Account Token missing in response: {response.text}")

        return token

    # --- Download from YouTube ---
    def download_youtube_video(self, url: str, output_path: str = "temp_video.mp4") -> str:
        """Downloads a YouTube video to a local file."""
        logger.info(f"Downloading YouTube video: {url}")

        ydl_opts = {
            "format": "best",
            "outtmpl": output_path,
            "quiet": False,
            "no_warnings": False,
            "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            logger.info("Download complete.")
            return output_path
        except Exception as e:
            raise Exception(f"YouTube Download Failed: {str(e)}")

    # --- Upload Local File ---
    def upload_video(self, video_path: str, video_name: str) -> str:
        """Uploads a LOCAL FILE to Azure Video Indexer."""
        arm_token = self.get_access_token()
        vi_token = self.get_account_token(arm_token)

        api_url = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos"
        params = {
            "accessToken": vi_token,
            "name": video_name,
            "privacy": "Private",
            "indexingPreset": "Default",
        }

        logger.info(f"Uploading file {video_path} to Azure Video Indexer...")

        with open(video_path, "rb") as video_file:
            files = {"file": video_file}
            response = requests.post(api_url, params=params, files=files, timeout=600)

        if response.status_code != 200:
            raise Exception(f"Azure Upload Failed: {response.text}")

        video_id = response.json().get("id")
        if not video_id:
            raise Exception(f"Upload succeeded but video id missing: {response.text}")

        return video_id

    def wait_for_processing(self, video_id: str):
        """Polls status until complete."""
        logger.info(f"Waiting for video {video_id} to process...")
        while True:
            arm_token = self.get_access_token()
            vi_token = self.get_account_token(arm_token)

            url = f"https://api.videoindexer.ai/{self.location}/Accounts/{self.account_id}/Videos/{video_id}/Index"
            params = {"accessToken": vi_token}
            response = requests.get(url, params=params, timeout=60)

            # If VI returns non-JSON on error, this will throw; surface cleanly
            try:
                data = response.json()
            except Exception:
                raise Exception(f"Failed to read VI status JSON: {response.status_code} {response.text}")

            state = data.get("state")
            if state == "Processed":
                return data
            if state == "Failed":
                raise Exception(f"Video Indexing Failed in Azure: {data}")
            if state == "Quarantined":
                raise Exception("Video Quarantined (Copyright/Content Policy Violation).")

            logger.info(f"Status: {state}... waiting 30s")
            time.sleep(30)

    def extract_data(self, vi_json):
        """Parses the VI JSON into our State format."""
        transcript_lines = []
        for v in vi_json.get("videos", []):
            for insight in v.get("insights", {}).get("transcript", []):
                text = insight.get("text")
                if text:
                    transcript_lines.append(text)

        ocr_lines = []
        for v in vi_json.get("videos", []):
            for insight in v.get("insights", {}).get("ocr", []):
                text = insight.get("text")
                if text:
                    ocr_lines.append(text)

        return {
            "transcript": " ".join(transcript_lines),
            "ocr_text": ocr_lines,
            "video_metadata": {
                "duration": vi_json.get("summarizedInsights", {}).get("duration", {}).get("seconds"),
                "platform": "youtube",
            },
        }