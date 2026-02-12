"""
Announcement endpoints for the High School Management System API
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query

from ..database import announcements_collection, teachers_collection

router = APIRouter(
    prefix="/announcements",
    tags=["announcements"]
)

logger = logging.getLogger(__name__)


def _to_utc_datetime(value: str, field_name: str, required: bool = True) -> Optional[datetime]:
    if not value:
        if required:
            raise HTTPException(status_code=400, detail=f"{field_name} is required")
        return None

    try:
        normalized = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError as exc:
        logger.warning("Invalid %s format: %s", field_name, exc)
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format") from exc


def _serialize_announcement(doc: Dict[str, Any]) -> Dict[str, Any]:
    starts_at = doc.get("starts_at")
    expires_at = doc.get("expires_at")
    created_at = doc.get("created_at")
    updated_at = doc.get("updated_at")

    return {
        "id": str(doc["_id"]),
        "message": doc["message"],
        "starts_at": starts_at.isoformat() if starts_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": created_at.isoformat() if created_at else None,
        "updated_at": updated_at.isoformat() if updated_at else None,
    }


def _require_signed_in_user(teacher_username: Optional[str]) -> Dict[str, Any]:
    if not teacher_username:
        raise HTTPException(status_code=401, detail="Authentication required")

    teacher = teachers_collection.find_one({"_id": teacher_username})
    if not teacher:
        raise HTTPException(status_code=401, detail="Authentication required")

    return teacher


@router.get("", response_model=List[Dict[str, Any]])
@router.get("/", response_model=List[Dict[str, Any]])
def get_active_announcements() -> List[Dict[str, Any]]:
    """Get all currently active announcements for display in the header."""
    now = datetime.now(timezone.utc)
    query = {
        "expires_at": {"$gt": now},
        "$or": [
            {"starts_at": None},
            {"starts_at": {"$lte": now}}
        ]
    }

    docs = announcements_collection.find(query).sort("expires_at", 1)
    return [_serialize_announcement(doc) for doc in docs]


@router.get("/manage", response_model=List[Dict[str, Any]])
def list_announcements(teacher_username: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """List all announcements for management view (signed-in users only)."""
    _require_signed_in_user(teacher_username)
    docs = announcements_collection.find({}).sort("created_at", -1)
    return [_serialize_announcement(doc) for doc in docs]


@router.post("", response_model=Dict[str, Any])
@router.post("/", response_model=Dict[str, Any])
def create_announcement(
    message: str,
    expires_at: str,
    starts_at: Optional[str] = None,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Create a new announcement (signed-in users only)."""
    _require_signed_in_user(teacher_username)

    sanitized_message = message.strip()
    if not sanitized_message:
        raise HTTPException(status_code=400, detail="Message is required")
    if len(sanitized_message) > 500:
        raise HTTPException(status_code=400, detail="Message is too long")

    parsed_starts_at = _to_utc_datetime(starts_at, "starts_at", required=False)
    parsed_expires_at = _to_utc_datetime(expires_at, "expires_at", required=True)

    if parsed_starts_at and parsed_starts_at >= parsed_expires_at:
        raise HTTPException(status_code=400, detail="Expiration must be after start date")

    now = datetime.now(timezone.utc)
    payload = {
        "message": sanitized_message,
        "starts_at": parsed_starts_at,
        "expires_at": parsed_expires_at,
        "created_at": now,
        "updated_at": now,
    }

    result = announcements_collection.insert_one(payload)
    created = announcements_collection.find_one({"_id": result.inserted_id})
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create announcement")

    return _serialize_announcement(created)


@router.put("/{announcement_id}", response_model=Dict[str, Any])
def update_announcement(
    announcement_id: str,
    message: str,
    expires_at: str,
    starts_at: Optional[str] = None,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, Any]:
    """Update an existing announcement (signed-in users only)."""
    _require_signed_in_user(teacher_username)

    sanitized_message = message.strip()
    if not sanitized_message:
        raise HTTPException(status_code=400, detail="Message is required")
    if len(sanitized_message) > 500:
        raise HTTPException(status_code=400, detail="Message is too long")

    parsed_starts_at = _to_utc_datetime(starts_at, "starts_at", required=False)
    parsed_expires_at = _to_utc_datetime(expires_at, "expires_at", required=True)

    if parsed_starts_at and parsed_starts_at >= parsed_expires_at:
        raise HTTPException(status_code=400, detail="Expiration must be after start date")

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        logger.warning("Invalid announcement id '%s': %s", announcement_id, exc)
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.update_one(
        {"_id": object_id},
        {
            "$set": {
                "message": sanitized_message,
                "starts_at": parsed_starts_at,
                "expires_at": parsed_expires_at,
                "updated_at": datetime.now(timezone.utc),
            }
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    updated = announcements_collection.find_one({"_id": object_id})
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update announcement")

    return _serialize_announcement(updated)


@router.delete("/{announcement_id}", response_model=Dict[str, str])
def delete_announcement(
    announcement_id: str,
    teacher_username: Optional[str] = Query(None)
) -> Dict[str, str]:
    """Delete an announcement (signed-in users only)."""
    _require_signed_in_user(teacher_username)

    try:
        object_id = ObjectId(announcement_id)
    except Exception as exc:
        logger.warning("Invalid announcement id '%s': %s", announcement_id, exc)
        raise HTTPException(status_code=400, detail="Invalid announcement id") from exc

    result = announcements_collection.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Announcement not found")

    return {"message": "Announcement deleted"}
