import os
import json
from datetime import datetime, timedelta
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

POSTS_COUNT = 60
WEEKS_BACK = 3


def init_firebase():
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT")

    if service_account_json:
        service_account_dict = json.loads(service_account_json)
    else:
        with open("serviceAccountKey.json", "r", encoding="utf-8") as f:
            service_account_dict = json.load(f)

    cred = credentials.Certificate(service_account_dict)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def is_advertisement(post):
    return post.get("marked_as_ads", 0) == 1


def extract_images(attachments):
    if not attachments:
        return []
    images = []
    for att in attachments:
        if att.get("type") == "photo":
            photo = att.get("photo", {})
            sizes = photo.get("sizes", [])
            if sizes:
                best = None
                for size in sizes:
                    if size.get("type") in ("w", "z"):
                        best = size.get("url")
                        break
                if not best:
                    best = sizes[-1].get("url")

                images.append({
                    "url": best,
                    "text": photo.get("text", ""),
                    "width": photo.get("width", 0),
                    "height": photo.get("height", 0),
                })
    return images


def extract_videos(attachments):
    if not attachments:
        return []
    videos = []
    for att in attachments:
        if att.get("type") == "video":
            video = att.get("video", {})
            images = video.get("image", [])
            preview = images[-1].get("url") if images else None

            videos.append({
                "id": video.get("id"),
                "owner_id": video.get("owner_id"),
                "title": video.get("title", ""),
                "description": video.get("description", ""),
                "duration": video.get("duration", 0),
                "preview": preview,
                "player": video.get("player", ""),
                "views": video.get("views", 0),
                "date": video.get("date", 0),
            })
    return videos


def extract_docs(attachments):
    if not attachments:
        return []
    docs = []
    for att in attachments:
        if att.get("type") == "doc":
            doc = att.get("doc", {})
            docs.append({
                "title": doc.get("title", ""),
                "ext": doc.get("ext", ""),
                "size": doc.get("size", 0),
                "url": doc.get("url", ""),
            })
    return docs


def extract_links(attachments):
    if not attachments:
        return []
    links = []
    for att in attachments:
        if att.get("type") == "link":
            link = att.get("link", {})
            images = link.get("image", [])
            preview = images[-1].get("url") if images else None

            links.append({
                "url": link.get("url", ""),
                "title": link.get("title", ""),
                "description": link.get("description", ""),
                "preview": preview,
            })
    return links


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
    saved = 0

    for post in posts:
        if is_advertisement(post):
            print(f"  Пост {post['id']} — реклама, пропускаем")
            continue

        attachments = post.get("attachments", [])

        has_useful_attachments = any(
            att.get("type") in ("photo", "video", "doc", "link")
            for att in attachments
        )
        has_text = bool(post.get("text", "").strip())

        if not has_useful_attachments and not has_text:
            print(f"  Пост {post['id']} — нет полезного контента, пропускаем")
            continue

        doc_ref = db.collection("news").document(str(post["id"]))
        batch.set(
            doc_ref,
            {
                "id": post["id"],
                "text": post.get("text", ""),
                "date": post.get("date", 0),
                "images": extract_images(attachments),
                "videos": extract_videos(attachments),
                "docs": extract_docs(attachments),
                "links": extract_links(attachments),
                "likes": post.get("likes", {}).get("count", 0),
                "views": post.get("views", {}).get("count", 0),
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
        saved += 1

    batch.commit()
    print(f"Сохранено {saved} постов (из {len(posts)})")


def delete_old_posts(db, weeks_back=3):
    cutoff = int((datetime.now() - timedelta(weeks=weeks_back)).timestamp())
    old_posts = db.collection("news").where("date", "<", cutoff).stream()

    deleted = 0
    for post in old_posts:
        post.reference.delete()
        deleted += 1

    print(f"Удалено старых постов: {deleted}")


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
    delete_old_posts(db, WEEKS_BACK)
    print("Готово!")


if __name__ == "__main__":
    main()