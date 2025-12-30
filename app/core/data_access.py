"""Centralized data access service.

Common database queries used across multiple modules.  This module
replaces direct ``Model.query`` usage with explicit SQLAlchemy v2
``Session`` usage via :func:`app.db.get_session` so code is Pylance
friendly and easier to type-check.

TODO: expand with more helper methods as the migration completes.
"""

from loguru import logger

from app.auth.models import Users
from app.auth.user_queries import get_user_by_display_name
from app.db import get_session
from app.inventory.item_queries import get_item, list_items_for_user
from app.inventory.models import Items


class DataAccessService:
    """Centralized service for common database queries.

    Notes
    -----
    All methods use :func:`app.db.get_session` to obtain a SQLAlchemy
    ``Session``. This keeps database access explicit and avoids the
    Flask-SQLAlchemy ``Model.query`` pattern.
    """

    @staticmethod
    def get_user_by_squad(squad_name: str) -> Users | None:
        """Get user by squad display name.

        Parameters
        ----------
        squad_name : str
            The display name of the squad to look up.

        Returns
        -------
        Optional[Users]
            The matching user or ``None`` if not found or on error.
        """

        try:
            with get_session() as session:
                return get_user_by_display_name(squad_name, session)
        except Exception as e:  # pragma: no cover - defensive logging
            logger.error(f"Database error querying user by squad '{squad_name}': {e}")
            return None

    @staticmethod
    def get_item_by_id(item_id: int, user_id: int) -> Items | None:
        """Get item by ID for a specific user.

        Parameters
        ----------
        item_id : int
            Item primary key to look up.
        user_id : int
            Owner user id to scope the lookup.

        Returns
        -------
        Optional[Items]
            The item instance or ``None`` if not found.
        """

        try:
            with get_session() as session:
                item = get_item(item_id, session)
                if item and item.user_id != user_id:
                    return None
                return item
        except Exception as e:  # pragma: no cover - defensive logging
            logger.error(
                f"Database error querying item {item_id} for user {user_id}: {e}"
            )
            return None

    @staticmethod
    def get_active_items_for_user(user_id: int) -> list[Items]:
        """Get all active items for a user, ordered by last_accessed.

        Parameters
        ----------
        user_id : int
            User id to filter items by.

        Returns
        -------
        List[Items]
            A list of active items (possibly empty on error).
        """

        try:
            with get_session() as session:
                return list(
                    list_items_for_user(
                        user_id,
                        include_inactive=False,
                        order_by_last_accessed=True,
                        session=session,
                    )
                )
        except Exception as e:
            logger.error(
                f"Database error fetching active items for user {user_id}: {e}"
            )
            return []
