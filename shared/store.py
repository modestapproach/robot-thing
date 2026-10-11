"""Persistence layer: one canonical MongoDB database, with an in-memory fallback.

Set ``MONGODB_URI`` to use Atlas (PRD §5.4). Unset, the store is an in-process
dict-backed implementation with the same semantics so every test and the whole
demo loop run offline. Both implement conditional updates needed for atomic
promotion (PRD §8.8) and append-only finalized experiments (PRD §13.4).
"""
from __future__ import annotations

import copy
import os
import threading
from typing import Any, Iterable, Optional

from pydantic import BaseModel

COLLECTIONS = [
    "robots",
    "twin_versions",
    "harness_versions",
    "experiments",
    "experiment_campaigns",
    "hardware_commands",
    "mutation_proposals",
    "evaluation_results",
    "audit_log",
    "agent_traces",
    "sim_trajectories",
]

INDEXES: dict[str, list[tuple[list[tuple[str, int]], dict[str, Any]]]] = {
    "hardware_commands": [([("idempotency_key", 1)], {"unique": True})],
    "experiments": [
        ([("campaign_id", 1), ("started_at", 1)], {}),
        ([("harness_version_id", 1), ("scenario_id", 1)], {}),
    ],
    "harness_versions": [([("status", 1), ("version", 1)], {})],
    "mutation_proposals": [([("status", 1), ("created_at", 1)], {})],
    "evaluation_results": [([("candidate_version_id", 1)], {})],
    "experiment_campaigns": [([("status", 1), ("updated_at", 1)], {})],
    "agent_traces": [([("started", -1)], {})],
    "sim_trajectories": [([("created_at", -1)], {}), ([("command_id", 1)], {})],
}


def _dump(doc: BaseModel | dict) -> dict:
    if isinstance(doc, BaseModel):
        return doc.model_dump(by_alias=True, mode="python")
    return dict(doc)


class DuplicateKeyError(Exception):
    pass


class ImmutableDocumentError(Exception):
    pass


class Store:
    """Interface. ``_id`` is the primary key everywhere."""

    def insert(self, coll: str, doc: BaseModel | dict) -> str: ...
    def get(self, coll: str, id: str) -> Optional[dict]: ...
    def find(self, coll: str, query: dict | None = None, sort: list[tuple[str, int]] | None = None, limit: int = 0) -> list[dict]: ...
    def update(self, coll: str, id: str, patch: dict) -> bool: ...
    def conditional_update(self, coll: str, query: dict, patch: dict) -> bool: ...
    def count(self, coll: str, query: dict | None = None) -> int: ...
    def audit(self, event: str, **fields: Any) -> None: ...


def _matches(doc: dict, query: dict) -> bool:
    for k, v in query.items():
        cur: Any = doc
        for part in k.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if isinstance(v, dict) and any(op.startswith("$") for op in v):
            for op, arg in v.items():
                if op == "$in" and cur not in arg:
                    return False
                if op == "$ne" and cur == arg:
                    return False
                if op == "$gte" and not (cur is not None and cur >= arg):
                    return False
                if op == "$lte" and not (cur is not None and cur <= arg):
                    return False
                if op == "$exists" and (cur is not None) != bool(arg):
                    return False
        elif cur != v:
            return False
    return True


class MemoryStore(Store):
    """In-process store. With ``path`` it snapshots to a pickle after every write so a
    killed campaign can resume offline (no Atlas needed for the resume demo)."""

    def __init__(self, path: str | None = None) -> None:
        self._data: dict[str, dict[str, dict]] = {c: {} for c in COLLECTIONS}
        self._lock = threading.RLock()
        self._path = path
        if path and os.path.exists(path):
            import pickle

            with open(path, "rb") as f:
                self._data.update(pickle.load(f))

    def _persist(self) -> None:
        if self._path:
            import pickle

            tmp = self._path + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump(self._data, f)
            os.replace(tmp, self._path)

    def insert(self, coll, doc):
        d = _dump(doc)
        with self._lock:
            if d["_id"] in self._data[coll]:
                raise DuplicateKeyError(d["_id"])
            if coll == "hardware_commands":
                if any(x["idempotency_key"] == d["idempotency_key"] for x in self._data[coll].values()):
                    raise DuplicateKeyError(d["idempotency_key"])
            self._data[coll][d["_id"]] = copy.deepcopy(d)
            self._persist()
        return d["_id"]

    def get(self, coll, id):
        with self._lock:
            d = self._data[coll].get(id)
            return copy.deepcopy(d) if d else None

    def find(self, coll, query=None, sort=None, limit=0):
        with self._lock:
            out = [copy.deepcopy(d) for d in self._data[coll].values() if _matches(d, query or {})]
        for key, direction in reversed(sort or []):
            out.sort(key=lambda d: (d.get(key) is None, d.get(key)), reverse=direction < 0)
        return out[:limit] if limit else out

    def update(self, coll, id, patch):
        return self.conditional_update(coll, {"_id": id}, patch)

    def conditional_update(self, coll, query, patch):
        with self._lock:
            for d in self._data[coll].values():
                if _matches(d, query):
                    if coll == "experiments" and d.get("finalized"):
                        raise ImmutableDocumentError(d["_id"])
                    for k, v in patch.items():
                        cur = d
                        parts = k.split(".")
                        for p in parts[:-1]:
                            cur = cur.setdefault(p, {})
                        cur[parts[-1]] = copy.deepcopy(v)
                    self._persist()
                    return True
        return False

    def count(self, coll, query=None):
        return len(self.find(coll, query))

    def audit(self, event, **fields):
        from shared.ids import new_id
        from shared.schemas import utcnow

        self.insert("audit_log", {"_id": new_id("aud"), "event": event, "at": utcnow(), **fields})


class MongoStore(Store):
    def __init__(self, uri: str, db_name: str) -> None:
        from pymongo import MongoClient

        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self._db = self._client[db_name]
        for coll, idx in INDEXES.items():
            for keys, opts in idx:
                self._db[coll].create_index(keys, **opts)

    def insert(self, coll, doc):
        import pymongo.errors

        d = _dump(doc)
        try:
            self._db[coll].insert_one(d)
        except pymongo.errors.DuplicateKeyError as e:
            raise DuplicateKeyError(str(e)) from e
        return d["_id"]

    def get(self, coll, id):
        return self._db[coll].find_one({"_id": id})

    def find(self, coll, query=None, sort=None, limit=0):
        cur = self._db[coll].find(query or {})
        if sort:
            cur = cur.sort(sort)
        if limit:
            cur = cur.limit(limit)
        return list(cur)

    def update(self, coll, id, patch):
        return self.conditional_update(coll, {"_id": id}, patch)

    def conditional_update(self, coll, query, patch):
        if coll == "experiments":
            if self._db[coll].count_documents({**query, "finalized": True}, limit=1):
                raise ImmutableDocumentError(str(query))
        res = self._db[coll].update_one(query, {"$set": patch})
        return res.matched_count == 1

    def count(self, coll, query=None):
        return self._db[coll].count_documents(query or {})

    def audit(self, event, **fields):
        from shared.ids import new_id
        from shared.schemas import utcnow

        self._db["audit_log"].insert_one({"_id": new_id("aud"), "event": event, "at": utcnow(), **fields})


_default: Optional[Store] = None


def get_store() -> Store:
    """Process-wide store: Mongo when ``MONGODB_URI`` is set, otherwise in-memory."""
    global _default
    if _default is None:
        uri = os.environ.get("MONGODB_URI")
        if uri and "<db_password>" not in uri:
            _default = MongoStore(uri, os.environ.get("AUTOLAB_DB", "autolab"))
        else:
            _default = MemoryStore(os.environ.get("AUTOLAB_STORE_FILE") or None)
    return _default


def set_store(store: Store) -> None:
    global _default
    _default = store
