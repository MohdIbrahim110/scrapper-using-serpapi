
import csv
import hashlib
import os
import re
import time
from io import BytesIO
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError

# =========================================
# CONFIGURATION
# =========================================

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "keywords.csv"
OUTPUT_DIR = BASE_DIR / "downloaded_images"

MAX_IMAGES_PER_KEYWORD = 200
MAX_SEARCH_PAGES = 10
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MIN_WIDTH = 200
MIN_HEIGHT = 200

API_URL = "https://serpapi.com/search.json"

load_dotenv(BASE_DIR / ".env")
API_KEY = os.getenv("SERPAPI_KEY")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

session = requests.Session()
session.headers.update({
    "User-Agent": "RoadGarbageImageCollector/1.0"
})

# Prevent saving identical image content twice.
seen_hashes = set()


def read_keywords():
    with CSV_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames or "keyword" not in reader.fieldnames:
            raise ValueError(
                "keywords.csv must have a 'keyword' column"
            )

        return [
            row["keyword"].strip()
            for row in reader
            if row.get("keyword", "").strip()
        ]


def safe_folder_name(keyword):
    name = re.sub(r"[^a-zA-Z0-9_-]+", "_", keyword)
    return name.strip("_")[:80] or "images"


def search_google_images(keyword, page_number=0):
    params = {
        "engine": "google_images",
        "q": keyword,
        "api_key": API_KEY,
        "ijn": page_number,
        "hl": "en",
        "gl": "in",
    }

    response = session.get(
        API_URL,
        params=params,
        timeout=60,
    )
    response.raise_for_status()

    data = response.json()

    if data.get("error"):
        raise RuntimeError(data["error"])

    return data.get("images_results", [])


def download_image(image_url, keyword, folder):
    try:
        with session.get(
            image_url,
            timeout=25,
            stream=True,
        ) as response:
            response.raise_for_status()

            content = bytearray()

            for chunk in response.iter_content(65536):
                content.extend(chunk)

                if len(content) > MAX_IMAGE_BYTES:
                    print("  Skipped: image exceeds size limit")
                    return False

        image = Image.open(BytesIO(content))
        image.verify()

        image = Image.open(BytesIO(content))
        image.load()

        if image.width < MIN_WIDTH or image.height < MIN_HEIGHT:
            print("  Skipped: image resolution too small")
            return False

        formats = {
            "JPEG": "jpg",
            "PNG": "png",
            "WEBP": "webp",
        }

        extension = formats.get(image.format)

        if not extension:
            print("  Skipped: unsupported image format")
            return False

        digest = hashlib.sha256(content).hexdigest()

        if digest in seen_hashes:
            print("  Skipped: duplicate image")
            return False

        seen_hashes.add(digest)

        filename = f"{digest[:16]}.{extension}"
        output_path = folder / filename

        output_path.write_bytes(content)

        print(f"  Saved: {output_path.name}")
        return True

    except (
        requests.RequestException,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as error:
        print(f"  Download failed: {error}")
        return False


def main():
    if not API_KEY:
        raise RuntimeError(
            "SERPAPI_KEY is missing. Add it to your .env file."
        )

    keywords = read_keywords()
    total_downloaded = 0

    for keyword in keywords:
        print(f"\nSearching Google Images for: {keyword}")

        folder = OUTPUT_DIR / safe_folder_name(keyword)
        folder.mkdir(parents=True, exist_ok=True)

        downloaded_for_keyword = 0
        seen_urls = set()

        for page_number in range(MAX_SEARCH_PAGES):
            if downloaded_for_keyword >= MAX_IMAGES_PER_KEYWORD:
                break

            try:
                results = search_google_images(
                    keyword, page_number
                )
            except (
                requests.RequestException,
                RuntimeError,
            ) as error:
                print(f"  Search failed: {error}")
                break

            if not results:
                print("  No more results.")
                break

            for item in results:
                if downloaded_for_keyword >= MAX_IMAGES_PER_KEYWORD:
                    break

                image_url = item.get("original")

                if not image_url or image_url in seen_urls:
                    continue

                seen_urls.add(image_url)

                if download_image(image_url, keyword, folder):
                    downloaded_for_keyword += 1
                    total_downloaded += 1

                time.sleep(0.5)

            time.sleep(1)

        print(
            f"Finished '{keyword}': "
            f"{downloaded_for_keyword} images saved"
        )

    session.close()

    print(f"\nComplete! Total new images: {total_downloaded}")
    print(f"Image folder: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
