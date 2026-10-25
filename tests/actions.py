"""One squad doing inventory work, driven through the real services."""

from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from app.inventory.constants import VirtualLocation
from app.inventory.expiration_service import ExpirationAllocation
from app.inventory.scan_submit_service import ScanSubmitResult, save_scan_submission
from app.inventory.scan_support import ScanActor, ScanPermissions
from app.inventory.schema import ScanItemRequest
from tests.factories import AgencyFixture

ADMIN_PERMISSIONS: Final = ScanPermissions(count=True, restock=True)
GUEST_NO_RESTOCK: Final = ScanPermissions(count=True, restock=False)


@dataclass(frozen=True, slots=True)
class Squad:
    """An agency plus the session its scans run in."""

    fixture: AgencyFixture
    session: Session
    is_admin: bool = True
    permissions: ScanPermissions = ADMIN_PERMISSIONS

    @property
    def id(self) -> int:
        return self.fixture.id

    def as_guest(self, *, permissions: ScanPermissions = GUEST_NO_RESTOCK) -> "Squad":
        return Squad(self.fixture, self.session, is_admin=False, permissions=permissions)

    def scan(
        self,
        *,
        source: int | None,
        destination: int | None,
        quantity: int,
        item_id: int | None = None,
        allocations: list[ExpirationAllocation] | None = None,
    ) -> ScanSubmitResult:
        actor = ScanActor(agency_id=self.id, is_admin=self.is_admin, session=self.session)
        request_data = ScanItemRequest(
            item_id=item_id if item_id is not None else self.fixture.item.id,
            from_storage_id=source,
            to_storage_id=destination,
            counter_value=quantity,
        )
        return save_scan_submission(actor, request_data=request_data, permissions=self.permissions, expiration_allocations=allocations)

    def count(
        self,
        quantity: int,
        *,
        storage_id: int | None = None,
        item_id: int | None = None,
        allocations: list[ExpirationAllocation] | None = None,
    ) -> ScanSubmitResult:
        return self.scan(
            source=VirtualLocation.COUNT,
            destination=self._storage(storage_id),
            quantity=quantity,
            item_id=item_id,
            allocations=allocations,
        )

    def restock(self, quantity: int, *, storage_id: int | None = None) -> ScanSubmitResult:
        return self.scan(source=VirtualLocation.RESTOCK, destination=self._storage(storage_id), quantity=quantity)

    def take_out(self, quantity: int, *, storage_id: int | None = None) -> ScanSubmitResult:
        return self.scan(source=self._storage(storage_id), destination=VirtualLocation.TAKEOUT, quantity=quantity)

    def transfer(self, quantity: int, *, source: int, destination: int) -> ScanSubmitResult:
        return self.scan(source=source, destination=destination, quantity=quantity)

    def count_every_storage(self) -> None:
        """Restock is refused until the whole location is counted, so open from a counted location."""
        for storage in (self.fixture.shelf, self.fixture.truck):
            self.count(0, storage_id=storage.id)

    def _storage(self, storage_id: int | None) -> int:
        return storage_id if storage_id is not None else self.fixture.shelf.id
