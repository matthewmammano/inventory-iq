"""Response models for the admin review of barcodes no item carries."""

from pydantic import BaseModel

from app.shared.timezone_utils import utc_isoformat

from .constants import UnknownUpcStatus
from .models import UnknownUpcScan
from .upc_service import UnknownUpcReviewGroups, recorded_upc_message


class UnknownBarcodeResponse(BaseModel):
    """One scanned barcode waiting for an admin decision, with the online guess that came with it."""

    id: int
    upc: str
    status: UnknownUpcStatus
    lookup_title: str | None
    suggested_item_id: int | None
    suggested_item_name: str | None
    first_scanned_at: str
    last_scanned_at: str

    @classmethod
    def of(cls, scan: UnknownUpcScan) -> "UnknownBarcodeResponse":
        return cls(
            id=scan.id,
            upc=scan.upc,
            status=scan.status,
            lookup_title=scan.lookup_title,
            suggested_item_id=scan.suggested_item_id,
            suggested_item_name=scan.suggested_item.name if scan.suggested_item else None,
            first_scanned_at=utc_isoformat(scan.created_at),
            last_scanned_at=utc_isoformat(scan.updated_at),
        )


class UnknownBarcodeReviewResponse(BaseModel):
    """Every barcode awaiting review, in the two groups the admin screen lists."""

    pending: list[UnknownBarcodeResponse]
    ignored: list[UnknownBarcodeResponse]

    @classmethod
    def of(cls, groups: UnknownUpcReviewGroups) -> "UnknownBarcodeReviewResponse":
        return cls(
            pending=[UnknownBarcodeResponse.of(scan) for scan in groups.pending],
            ignored=[UnknownBarcodeResponse.of(scan) for scan in groups.ignored],
        )


class AddedBarcodeResponse(BaseModel):
    """What became of a barcode an admin typed in by hand."""

    upc: str
    status: UnknownUpcStatus
    message: str

    @classmethod
    def of(cls, upc: str, status: UnknownUpcStatus) -> "AddedBarcodeResponse":
        return cls(upc=upc, status=status, message=recorded_upc_message(status))
