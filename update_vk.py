import os
import json
import tempfile
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

POSTS_COUNT = 60


def init_firebase():
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    print(f"DEBUG: FIREBASE_SERVICE_ACCOUNT задан: {service_account_json is not None}")
    print(f"DEBUG: VK_TOKEN задан: {os.environ.get('VK_TOKEN') is not None}")
    print(f"DEBUG: VK_GROUP_ID = {os.environ.get('VK_GROUP_ID')}")

    if service_account_json:
        service_account_dict = json.loads(service_account_json)
    else:
        with open("serviceAccountKey.json", "r", encoding="utf-8") as f:
            service_account_dict = json.load(f)

    cred = credentials.Certificate(service_account_dict)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def extract_image_url(attachments):
    if not attachments:
        return None
    for att in attachments:
        if att.get("type") == "photo":
            sizes = att.get("photo", {}).get("sizes", [])
            if sizes:
                return sizes[-1]["url"]
    return None


def fetch_vk_posts():
    vk_token = os.environ["VK_TOKEN"]
    vk_group_id = os.environ["VK_GROUP_ID"]

    url = "https://api.vk.com/method/wall.get"
    params = {
        "access_token": vk_token,
        "owner_id": vk_group_id,
        "v": "5.199",
        "count": POSTS_COUNT,
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def save_to_firestore(db, posts):
    batch = db.batch()

    for post in posts:
        doc_ref = db.collection("news").document(str(post["id"]))
        batch.set(
            doc_ref,
            {
                "id": post["id"],
                "text": post.get("text", ""),
                "date": post.get("date", 0),
                "image_url": extract_image_url(post.get("attachments", [])),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )

    batch.commit()
    print(f"Сохранено {len(posts)} постов")


def main():
    print("Запуск обновления VK...")

    db = init_firebase()
    print("Firebase подключён")

    data = fetch_vk_posts()
    if "response" not in data:
        print(f"Ошибка VK: {data}")
        return

    posts = data["response"]["items"]
    print(f"Получено {len(posts)} постов из VK")

    save_to_firestore(db, posts)
    print("Готово!")


if __name__ == "__main__":
    main()