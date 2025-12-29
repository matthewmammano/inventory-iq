"""Centralized data access service.

Common database queries used across multiple modules.  This module
replaces direct ``Model.query`` usage with explicit SQLAlchemy v2
``Session`` usage via :func:`app.db.get_session` so code is Pylance
friendly and easier to type-check.

TODO: expand with more helper methods as the migration completes.
"""

from collections.abc import Sequence

from loguru import logger
from sqlalchemy import desc, select

# SQLAlchemy Session type intentionally not imported here to avoid circular imports
from app.auth.models import Users
from app.db import get_session
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
                stmt = select(Users).where(Users.display_name == squad_name)
                return session.execute(stmt).scalars().first()
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
                stmt = (
                    select(Items)
                    .where(Items.id == item_id)
                    .where(Items.user_id == user_id)
                )
                return session.execute(stmt).scalars().first()
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
                stmt = (
                    select(Items)
                    .where(Items.user_id == user_id)
                    .where(Items.active)
                    .order_by(desc(Items.last_accessed).nullslast())
                )
                results: Sequence[Items] = session.execute(stmt).scalars().all()
                return list(results)
        except Exception as e:
            logger.error(
                f"Database error fetching active items for user {user_id}: {e}"
            )
            return []
