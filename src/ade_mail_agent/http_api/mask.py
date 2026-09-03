"""Mask (privacy, deterministico, non-LLM)."""
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ade_mail_agent.core import (
    ade_masker,
)

from .common import _active_id

router = APIRouter()


# ── MASK (privacy, non-LLM) ──────────────────────────────────────────

class MaskDetectRequest(BaseModel):
    text: str
    account_id: Optional[int] = None


@router.post("/mask/detect")
def mask_detect(req: MaskDetectRequest):
    user_masks = ade_masker.get_user_masks(req.account_id or _active_id() or 0)
    return {"entities": ade_masker.detect(req.text, user_masks=user_masks)}


class MaskRequest(BaseModel):
    text: str
    selected_values: Optional[List[str]] = None
    account_id: Optional[int] = None


@router.post("/mask")
def mask_text(req: MaskRequest):
    masked, mapping = ade_masker.mask(req.text, selected_values=req.selected_values)
    return {"masked_text": masked, "mapping": mapping}


class UnmaskRequest(BaseModel):
    masked_text: str
    mapping: dict


@router.post("/unmask")
def unmask_text(req: UnmaskRequest):
    return {"text": ade_masker.unmask(req.masked_text, req.mapping)}


@router.get("/mask/suggest")
def mask_suggest(selection: str):
    return {"type": ade_masker.suggest_type(selection)}


@router.get("/masks")
def get_masks(account_id: Optional[int] = None):
    return ade_masker.get_user_masks(account_id or _active_id() or 0)


class UserMaskRequest(BaseModel):
    value: str
    label_type: str = "MASK"
    account_id: Optional[int] = None


@router.post("/masks")
def add_mask(req: UserMaskRequest):
    return ade_masker.add_user_mask(
        req.account_id or _active_id() or 0, req.value, label_type=req.label_type
    )


@router.delete("/masks/{mask_id}")
def delete_mask(mask_id: int, account_id: Optional[int] = None):
    return {"success": ade_masker.delete_user_mask(
        account_id or _active_id() or 0, mask_id
    )}
