"""Intake JSON schemas: the full intake (Muse Spark 1.3, which alone decides a safety refusal) and the short
classification the open-weights model gives as a second opinion."""
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "customer_type": {"type": "string", "enum": ["consumer", "repair_shop"]},
        "language": {"type": "string"},
        "appliance": {"type": "object", "additionalProperties": False, "properties": {
            "kind": {"type": "string"}, "brand": {"type": "string"}, "model": {"type": "string"}, "serial_or_enr": {"type": "string"}},
            "required": ["kind", "brand", "model", "serial_or_enr"]},
        "part": {"type": "object", "additionalProperties": False, "properties": {
            "name_en": {"type": "string"}, "name_fr": {"type": "string"}, "name_user": {"type": "string"}, "part_number": {"type": "string"},
            "quantity": {"type": "integer"}, "condition": {"type": "string", "enum": ["broken", "missing", "worn", "other"]},
            "failure": {"type": "string"}},
            "required": ["name_en", "name_fr", "name_user", "part_number", "quantity", "condition", "failure"]},
        "environment": {"type": "object", "additionalProperties": False, "properties": {
            "max_temp_c": {"type": "number"}, "wet": {"type": "boolean"}, "food_contact": {"type": "boolean"}, "load": {"type": "string"}},
            "required": ["max_temp_c", "wet", "food_contact", "load"]},
        "material": {"type": "string", "enum": ["PLA", "PETG", "ASA", "TPU"]},
        "urgency": {"type": "string", "enum": ["normal", "today", "this_week"]},
        "refuse": {"type": "boolean"},
        "reason": {"type": "string"},
        "ip_flags": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["customer_type", "language", "appliance", "part", "environment", "material", "urgency", "refuse", "reason", "ip_flags", "questions", "notes"],
}

CATEGORIES = ["appliance", "furniture", "automotive", "electronics", "plumbing", "toy", "tool", "garden", "other"]

CLASSIFY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "safety_critical": {"type": "boolean"},
        "why": {"type": "string"},
        "title_en": {"type": "string"},
        "title_ru": {"type": "string"},
        "title_fr": {"type": "string"},
    },
    "required": ["category", "safety_critical", "why", "title_en", "title_ru", "title_fr"],
}
