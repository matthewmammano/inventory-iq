"""Request models for the admin review of barcodes no item carries."""

from pydantic import BaseModel, Field

from app.api.schema import LOCKED_INPUT

MAX_SCANNED_BARCODE_LENGTH = 64


class AddBarcodeRequest(BaseModel):
    """A barcode an admin typed in by hand; a malformed one is refused, not recorded."""

    model_config = LOCKED_INPUT

    upc: str = Field(min_length=1, max_length=MAX_SCANNED_BARCODE_LENGTH)


class LinkBarcodeRequest(BaseModel):
    """The item a reviewed barcode should open from now on."""

    model_config = LOCKED_INPUT

    item_id: int = Field(gt=0)
