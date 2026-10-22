import time
import src.utils.config as cfg

orig = cfg._load_yaml


def setcap(cap):
    def _load(name):
        d = orig(name)
        if name == "app.yaml":
            d = {**d, "workflow": {**(d.get("workflow") or {}), "regulation_dedup_per_doc": cap}}
        return d

    cfg._load_yaml = _load


from src.services.review_service import execute_review  # noqa: E402

for tid, cap in ((987655366, 0), (987655367, 1)):
    setcap(cap)
    t0 = time.time()
    try:
        execute_review(tid)
        print("DONE", tid, "cap=", cap, round(time.time() - t0, 1), "s", flush=True)
    except Exception as exc:  # noqa: BLE001
        print("ERR", tid, "cap=", cap, type(exc).__name__, str(exc)[:120], flush=True)
