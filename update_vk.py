import os
import json
from datetime import datetime, timedelta
import requests
import firebase_admin
from firebase_admin import credentials, firestore

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

POSTS_COUNT = 60
WEEKS_BACK = 3
BATCH_LIMIT = 500  # лимит операций в одном батче Firestore


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


def has_video(post):
    """True, если в посте есть хотя бы одно видео (обычное или клип)."""
    return any(att.get("type") == "video" for att in post.get("attachments", []))


def extract_images(attachments):
    images = []
    for att in attachments or []:
        if att.get("type") != "photo":
            continue
        photo = att.get("photo", {})
        sizes = photo.get("sizes", [])
        if not sizes:
            continue
        best = next((s.get("url") for s in sizes if s.get("type") in ("w", "z")), None)
        if not best:
            best = sizes[-1].get("url")
        images.append({
            "url": best,
            "text": photo.get("text", ""),
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
        })
    return images


def extract_docs(attachments):
    docs = []
    for att in attachments or []:
        if att.get("type") != "doc":
            continue
        doc = att.get("doc", {})
        docs.append({
            "title": doc.get("title", ""),
            "ext": doc.get("ext", ""),
            "size": doc.get("size", 0),
            "url": doc.get("url", ""),
        })
    return docs


def extract_links(attachments):
    links = []
    for att in attachments or []:
        if att.get("type") != "link":
            continue
        link = att.get("link", {})
        preview_images = link.get("image", [])
        preview = preview_images[-1].get("url") if preview_images else None
        links.append({
            "url": link.get("url", ""),
            "title": link.get("title", ""),
            "description": link.get("description", ""),
            "preview": preview,
        })
    return links


def fetch_vk_posts():
    url = "https://api.vk.com/method/wall.get"
    params = {
        "access_token": os.environ["VK_TOKEN"],
        "owner_id": os.environ["VK_GROUP_ID"],
        "v": "5.199",
        "count": POSTS_COUNT,
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def save_to_firestore(db, posts):
    batch = db.batch()
    ops = 0
    saved = 0
    skipped_ads = 0
    skipped_video = 0
    skipped_empty = 0

    for post in posts:
        if is_advertisement(post):
            skipped_ads += 1
            continue

        # Видео-пост пропускаем целиком.
        if has_video(post):
            skipped_video += 1
            continue

        attachments = post.get("attachments", [])
        has_useful = any(a.get("type") in ("photo", "doc", "link") for a in attachments)
        has_text = bool(post.get("text", "").strip())
        if not has_useful and not has_text:
            skipped_empty += 1
            continue

        doc_ref = db.collection("news").document(str(post["id"]))
        # merge=True создаёт новый или обновляет существующий (подхватывает правки из VK).
        batch.set(
            doc_ref,
            {
                "id": post["id"],
                "text": post.get("text", ""),
                "date": post.get("date", 0),
                "images": extract_images(attachments),
                "docs": extract_docs(attachments),
                "links": extract_links(attachments),
            },
            merge=True,
        )
        saved += 1
        ops += 1

        if ops >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            ops = 0

    if ops > 0:
        batch.commit()

    print(f"Сохранено/обновлено: {saved}, реклама: {skipped_ads}, "
          f"видео: {skipped_video}, пустые: {skipped_empty}")


def delete_old_posts(db, weeks_back=WEEKS_BACK):
    cutoff = int((datetime.now() - timedelta(weeks=weeks_back)).timestamp())
    old_posts = db.collection("news").where(
        filter=firestore.FieldFilter("date", "<", cutoff)
    ).stream()

    batch = db.batch()
    ops = 0
    deleted = 0

    for post in old_posts:
        batch.delete(post.reference)
        ops += 1
        deleted += 1
        if ops >= BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            ops = 0

    if ops > 0:
        batch.commit()

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
