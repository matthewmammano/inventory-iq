"""
Centralized data access service.

Common database queries used across multiple modules.
Eliminates repeated query patterns.
"""

import logging
from typing import Optional

from app.auth.models import Users
from app.inventory.models import Items

logger = logging.getLogger(__name__)


class DataAccessService:
    """Centralized service for common database queries."""

    @staticmethod
    def get_user_by_squad(squad_name: str) -> Optional[Users]:
        """Get user by squad display name."""
        try:
            return Users.query.filter_by(display_name=squad_name).first()
        except Exception as e:
            logger.error(f"Database error querying user by squad '{squad_name}': {e}")
            return None

    @staticmethod
    def get_item_by_id(item_id: int, user_id: int) -> Optional[Items]:
        """Get item by ID for specific user."""
        try:
            return Items.query.filter_by(id=item_id, user_id=user_id).first()
        except Exception as e:
            logger.error(f"Database error querying item {item_id} for user {user_id}: {e}")
            return None

    @staticmethod
    def get_active_items_for_user(user_id: int) -> list[Items]:
        """Get all active items for user, ordered by last_accessed."""
        try:
            return (
                Items.query.filter_by(user_id=user_id, active=True)
                .order_by(Items.last_accessed.desc().nullslast())
                .all()
            )
        except Exception as e:
            logger.error(f"Database error fetching active items for user {user_id}: {e}")
            return []
