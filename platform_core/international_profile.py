"""International name and postal address components shared by registration workflows."""
import unicodedata

NAME_KEYS = ("given", "middle", "family")
ADDRESS_FIELDS = {
    "street": 100, "unit": 60, "locality": 60, "region": 60, "postalCode": 24, "country": 60,
}


def _line(value, maximum, label):
    if not isinstance(value, str) or len(value) > maximum or any(unicodedata.category(ch) in ("Cc", "Cs") for ch in value):
        raise ValueError(f"Invalid {label}")
    return " ".join(unicodedata.normalize("NFC", value).split())


def name_parts(raw):
    if not isinstance(raw, dict) or set(raw) - {*NAME_KEYS, "single"}:
        raise ValueError("Enter given and family names, or a single name.")
    parts = {k: clean for k in (*NAME_KEYS, "single") if (clean := _line(raw.get(k, ""), 60, "name"))}
    if "single" in parts:
        if len(parts) != 1:
            raise ValueError("Use one name format.")
    elif not (parts.get("given") and parts.get("family")):
        raise ValueError("Both given name and family name are required. You can also use a single name.")
    display = " ".join(parts.values())
    if len(display) > 60:
        raise ValueError("Display name exceeds 60 characters.")
    return display, parts


def address(raw):
    if not isinstance(raw, dict) or set(raw) - ADDRESS_FIELDS.keys():
        raise ValueError("Invalid postal address fields.")
    parts = {key: cleaned for key, limit in ADDRESS_FIELDS.items()
             if (cleaned := _line(raw.get(key, ""), limit, key))}
    display = ", ".join(parts.values())
    if len(display) > 300:
        raise ValueError("Postal address exceeds 300 characters.")
    return display, parts


def merge_name(record, change, previous_name):
    if "nameParts" in change:
        display, parts = name_parts(change["nameParts"])
        if display != record["name"]:
            raise ValueError("Display name must match its name fields.")
        record["nameParts"] = parts
    elif record["name"] != previous_name:
        record.pop("nameParts", None)


def merge_address(record, change):
    if "internationalAddress" in change:
        if "addressRegion" in change or "address" in change:
            raise ValueError("Choose one address format.")
        record["address"], parts = address(change["internationalAddress"])
        if parts:
            record["internationalAddress"] = parts
        else:
            record.pop("internationalAddress", None)
        record.pop("addressRegion", None)
    elif "addressRegion" in change or ("address" in change and "internationalAddress" in record and
                                       record.get("address") != address(record["internationalAddress"])[0]):
        record.pop("internationalAddress", None)
