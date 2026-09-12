import os
import json
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()


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


def cleanup_image_url(db):
    docs = db.collection("news").stream()
    deleted = 0

    for doc in docs:
        data = doc.to_dict()
        if "image_url" in data:
            doc.reference.update({"image_url": firestore.DELETE_FIELD})
            deleted += 1
            print(f"  Удалено image_url из {doc.id}")

    print(f"Всего удалено: {deleted}")


def main():
    print("Очистка старых полей...")
    db = init_firebase()
    print("Firebase подключён")
    cleanup_image_url(db)
    print("Готово!")


if __name__ == "__main__":
    main()