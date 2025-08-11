from datetime import time

WORKERS = [
    {"id": "w1", "name": "Ayu"},
    {"id": "w2", "name": "Budi"},
    {"id": "w3", "name": "Citra"},
    {"id": "w4", "name": "Dewa"},
]

SERVICES = [
    {"id": "svc_thai", "name": "Thai Massage", "duration_min": 60},
    {"id": "svc_deep", "name": "Deep Tissue", "duration_min": 120},
    {"id": "svc_sweed", "name": "Swedish Massage", "duration_min": 60},
    {"id": "svc_hot", "name": "Hot Stone", "duration_min": 90},
    {"id": "svc_facial", "name": "Facial Treatment", "duration_min": 45},
    {"id": "svc_reflex", "name": "Reflexology", "duration_min": 30},
]

DAY_START = time(9, 0)
DAY_END   = time(17, 0)
SLOT_MIN  = 15
