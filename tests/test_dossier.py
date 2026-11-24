import base64
from copy import deepcopy
import json
import sqlite3
import unittest

from platform_core import dossier

TODAY = "2026-11-24"
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR42mNk2GfDwMDAxMDAwMDAAAALpgD+jGO7GwAAAABJRU5ErkJggg=="
JPEG = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAT/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAABQf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCUAEmj/9k="
OWNER = {"id": "o", "kind": "owner", "displayName": "业主", "permissions": []}
NURSE = {
    "id": "n",
    "kind": "staff",
    "displayName": "护士一",
    "permissions": ["medical", "medical.write"],
}
INTAKE = {
    "id": "i",
    "kind": "staff",
    "displayName": "接待一",
    "permissions": ["intake", "residents"],
}
KIN_STAFF = {
    "id": "q",
    "kind": "staff",
    "displayName": "亲属联络员",
    "permissions": ["relatives"],
}
FAMILY = {
    "id": "f1",
    "kind": "family",
    "displayName": "亲属一",
    "permissions": [],
    "residentId": "r1",
}
DOCUMENT = {
    "residentId": "r1",
    "requestId": "sample-1",
    "eventDate": "2025-02-03",
    "source": "演示门诊",
    "category": "CT",
    "imageBase64": PNG,
    "description": "逐项抄录文书原文",
    "pending": "第二页待补充",
}


class DossierTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        dossier.init(self.db)
        self.state = {
            "residents": [
                {"id": "r1", "name": "演示长者", "age": 71},
                {"id": "r2", "name": "另一个案"},
            ]
        }

    def save(self, action, fields, user=OWNER):
        with self.db:
            return dossier.apply(
                self.db, self.state, "dossier." + action, fields, user, TODAY
            )

    def view(self, user=OWNER, day=TODAY):
        return dossier.project(self.db, deepcopy(self.state), user, day)

    def test_photo_bytes_and_summary_are_immutable_and_read_requires_medical(self):
        self.save("document", DOCUMENT, NURSE)
        doc = self.view(NURSE)["medicalDocuments"][0]
        self.assertEqual(doc["summary"]["sourceFacts"], DOCUMENT["description"])
        self.assertEqual(doc["summary"]["reviewerId"], NURSE["id"])
        self.assertEqual(
            dossier.photo(self.db, doc["id"], NURSE),
            (base64.b64decode(PNG), "image/png"),
        )
        self.assertNotIn(PNG, json.dumps(self.view(NURSE)))
        self.assertEqual(self.view(INTAKE)["medicalDocuments"], [])
        for user in (INTAKE, FAMILY):
            with self.assertRaises(PermissionError):
                dossier.photo(self.db, doc["id"], user)
        for sql in (
            "UPDATE dossier_documents SET original=X'00'",
            "DELETE FROM dossier_documents",
        ):
            with self.db, self.assertRaises(sqlite3.IntegrityError):
                self.db.execute(sql)
        with self.assertRaises(FileNotFoundError):
            dossier.photo(self.db, "undefined", NURSE)

    def test_retry_reuses_one_summary_and_conflicting_reuse_is_rejected(self):
        self.save("document", DOCUMENT)
        expected = self.view()["medicalDocuments"]
        self.save("document", DOCUMENT, NURSE)
        self.save("document", {**DOCUMENT, "requestId": "retry-with-new-key"}, NURSE)
        self.assertEqual(self.view()["medicalDocuments"], expected)
        with self.assertRaises(ValueError):
            self.save("document", {**DOCUMENT, "description": "同一原件的新描述"})
        with self.assertRaises(ValueError):
            self.save("document", {**DOCUMENT, "imageBase64": JPEG})
        self.assertEqual(self.view()["medicalDocuments"], expected)

    def test_image_validation_chronology_and_manual_history(self):
        self.save("document", DOCUMENT)
        self.save(
            "document",
            {
                **DOCUMENT,
                "requestId": "jpeg",
                "eventDate": "2025-12-25",
                "imageBase64": JPEG,
            },
        )
        self.save(
            "document",
            {
                **DOCUMENT,
                "requestId": "history",
                "category": "病史补录",
                "imageBase64": "",
                "eventDate": "2023-01-01",
            },
        )
        docs = self.view()["medicalDocuments"]
        self.assertEqual(
            [r["eventDate"] for r in docs], ["2025-12-25", "2025-02-03", "2023-01-01"]
        )
        self.assertEqual(dossier.photo(self.db, docs[0]["id"], NURSE)[1], "image/jpeg")
        self.assertFalse(docs[-1]["hasImage"])
        for wrong in (
            {"imageBase64": "XY<"},
            {"imageBase64": base64.b64encode(b"fake jpeg").decode()},
            {"mime": "image/gif"},
            {"imageBase64": ""},
            {"eventDate": "2038-01-01"},
            {"imageBase64": JPEG[:-40]},
            {
                "imageBase64": "",
                "category": "病史补录",
                "method": "人工核对的 OCR 转录",
            },
        ):
            with self.assertRaises(ValueError):
                self.save("document", {**DOCUMENT, **wrong, "requestId": "broken"})

    def test_age_and_household_visibility_follow_permissions(self):
        data = {
            "residentId": "r1",
            "name": "新名",
            "age": "17",
            "birthDate": "1955-12-20",
            "nativePlace": "上海",
            "children": "两位子女轮流照护",
            "economicNotes": "家属分摊",
        }
        self.save("profile", data)
        self.assertEqual(self.view()["residents"][0]["age"], 70)
        self.assertEqual(self.view(day="2026-12-20")["residents"][0]["age"], 71)
        self.assertEqual(self.view(INTAKE)["dossierProfiles"][0]["nativePlace"], "上海")
        self.assertNotIn("children", self.view(INTAKE)["dossierProfiles"][0])
        self.assertNotIn("nativePlace", self.view(KIN_STAFF)["dossierProfiles"][0])
        self.assertEqual(
            self.view(KIN_STAFF)["dossierProfiles"][0]["economicNotes"], "家属分摊"
        )
        self.save(
            "profile", {"residentId": "r1", "name": "新名", "address": "新址"}, INTAKE
        )
        self.assertEqual(self.view()["dossierProfiles"][0]["economicNotes"], "家属分摊")
        with self.assertRaises(PermissionError):
            self.save("profile", data, INTAKE)
        with self.assertRaises(ValueError):
            self.save("profile", {**data, "birthDate": "2099-01-01"})
        with self.assertRaises(ValueError):
            self.save("profile", {**data, "name": ""})

    def test_relatives_self_scope_and_identity_mask(self):
        # Construct a synthetic checksum fixture and use no real person's number.
        digits = "99999919800101000"
        weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
        number = (
            digits
            + "10X98765432"[sum(int(d) * v for d, v in zip(digits, weights)) % 11]
        )
        payload = {
            "name": "测试亲属",
            "phone": "010-00000000",
            "relationship": "子女",
            "idNumber": number,
            "address": "演示路",
            "wechat": "demo-contact",
        }
        self.save("relative", payload, FAMILY)
        for malicious in ({"residentId": "r2"}, {"accountId": "another"}):
            with self.assertRaises(PermissionError):
                self.save("relative", {**payload, **malicious}, FAMILY)
        with self.assertRaises(PermissionError):
            self.save("relative", payload, KIN_STAFF)
        self.assertEqual(self.view(FAMILY)["relativeProfiles"][0]["idNumber"], number)
        self.assertIn("*", self.view(KIN_STAFF)["relativeProfiles"][0]["idNumber"])
        self.assertEqual(self.view(NURSE)["relativeProfiles"], [])
        self.assertEqual(self.view({**FAMILY, "id": "other"})["relativeProfiles"], [])
        self.assertEqual(
            self.view({**FAMILY, "residentId": "r2"})["relativeProfiles"], []
        )
        with self.assertRaises(ValueError):
            self.save("relative", {**payload, "idNumber": "123"}, FAMILY)
