"""
Restock Detection Service for Inventory Management.

Automatically classifies COUNT operations as restocks based on:
1. 47% threshold rule: COUNT with ≥47% increase from previous count
2. NULL→location pattern: from_location_id=None, to_location_id=X, positive quantity
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple

from app import db
from app.inventory.models import ActionLogs, OperationType

logger = logging.getLogger(__name__)

RESTOCK_THRESHOLD_PERCENT = 47.0


class RestockDetectionService:
    """Service for detecting and classifying inventory restocks."""
    
    @staticmethod
    def is_restock_operation(action_log: ActionLogs) -> bool:
        """
        Determine if an ActionLog represents a restock operation.
        
        Restock Detection Rules:
        1. NULL→location pattern: from_location_id=None, to_location_id exists, positive quantity
        2. 47% threshold: COUNT operation with ≥47% increase from previous count
        
        Args:
            action_log: ActionLog to analyze
            
        Returns:
            bool: True if this operation is classified as a restock
        """
        # Rule 1: NULL→location pattern (supplier to location transfer)
        if (action_log.from_location_id is None and 
            action_log.to_location_id is not None and 
            action_log.quantity_delta > 0):
            logger.info(f"Restock detected (NULL→location): ActionLog {action_log.id}")
            return True
        
        # Rule 2: 47% threshold for COUNT operations
        if action_log.operation_type == OperationType.count:
            previous_count = RestockDetectionService._get_previous_count(
                action_log.user_id, 
                action_log.item_id, 
                action_log.to_location_id, 
                action_log.time_scanned
            )
            
            if previous_count and previous_count.quantity_delta > 0:
                percent_increase = ((action_log.quantity_delta - previous_count.quantity_delta) / 
                                  previous_count.quantity_delta) * 100
                
                if percent_increase >= RESTOCK_THRESHOLD_PERCENT:
                    logger.info(f"Restock detected (47% rule): ActionLog {action_log.id}, "
                              f"increase: {percent_increase:.1f}% ({previous_count.quantity_delta} → {action_log.quantity_delta})")
                    return True
                else:
                    logger.debug(f"Count increase below threshold: {percent_increase:.1f}% for ActionLog {action_log.id}")
        
        return False
    
    @staticmethod
    def _get_previous_count(user_id: int, item_id: int, location_id: int, 
                           before_time: datetime) -> Optional[ActionLogs]:
        """Get the most recent COUNT operation before the given time for the same item/location."""
        return (ActionLogs.query
                .filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.to_location_id == location_id,
                    ActionLogs.operation_type == OperationType.count,
                    ActionLogs.time_scanned < before_time
                )
                .order_by(ActionLogs.time_scanned.desc())
                .first())
    
    @staticmethod
    def classify_action_log(action_log: ActionLogs) -> bool:
        """
        Classify an ActionLog and update its estimated_restock field.
        
        Args:
            action_log: ActionLog to classify
            
        Returns:
            bool: True if classified as restock, False otherwise
        """
        is_restock = RestockDetectionService.is_restock_operation(action_log)
        action_log.estimated_restock = is_restock
        return is_restock
    
    @staticmethod
    def reclassify_historical_data(user_id: Optional[int] = None, 
                                  batch_size: int = 1000) -> Dict[str, int]:
        """
        Reclassify all existing ActionLogs to populate estimated_restock field.
        
        Args:
            user_id: If provided, only reclassify for this user
            batch_size: Number of records to process per batch
            
        Returns:
            Dict with classification statistics
        """
        logger.info(f"Starting historical data reclassification for user_id={user_id}")
        
        query = ActionLogs.query
        if user_id:
            query = query.filter(ActionLogs.user_id == user_id)
        
        # Process in chronological order to ensure proper previous count detection
        query = query.order_by(ActionLogs.time_scanned.asc())
        
        total_processed = 0
        restocks_found = 0
        batch_count = 0
        max_batches = 10_000  # PRODUCTION SAFETY: Maximum 10M records (10000 * 1000)
        
        while batch_count < max_batches:
            batch = query.offset(batch_count * batch_size).limit(batch_size).all()
            if not batch:
                break  # No more records to process
            
            batch_restocks = 0
            for action_log in batch:
                if RestockDetectionService.classify_action_log(action_log):
                    batch_restocks += 1
            
            total_processed += len(batch)
            restocks_found += batch_restocks
            batch_count += 1
            
            # Commit this batch
            db.session.commit()
            
            logger.info(f"Processed batch {batch_count}: {len(batch)} records, "
                       f"{batch_restocks} restocks found")
        
        # PRODUCTION SAFETY: Warn if we hit the limit
        if batch_count >= max_batches:
            logger.warning(f"SAFETY LIMIT REACHED: Stopped processing after {max_batches} batches "
                          f"({total_processed} records). Consider increasing batch_size or running in chunks.")
        
        logger.info(f"Historical reclassification complete: {total_processed} records processed, "
                   f"{restocks_found} restocks identified ({restocks_found/total_processed*100:.1f}%)")
        
        return {
            "total_processed": total_processed,
            "restocks_found": restocks_found,
            "percentage_restocks": restocks_found / total_processed * 100 if total_processed > 0 else 0
        }
    
    @staticmethod
    def get_restock_timeline(user_id: int, item_id: int, location_id: int) -> List[ActionLogs]:
        """Get all identified restocks for an item at a location, chronologically."""
        return (ActionLogs.query
                .filter(
                    ActionLogs.user_id == user_id,
                    ActionLogs.item_id == item_id,
                    ActionLogs.to_location_id == location_id,
                    ActionLogs.estimated_restock == True
                )
                .order_by(ActionLogs.time_scanned.asc())
                .all())
    
    @staticmethod
    def get_consumption_periods(user_id: int, item_id: int, location_id: int) -> List[Tuple[ActionLogs, ActionLogs]]:
        """
        Get consumption periods (pairs of counts) excluding restock periods.
        
        Returns:
            List of (start_count, end_count) tuples representing valid consumption periods
        """
        # Get all counts for this item/location
        counts = (ActionLogs.query
                 .filter(
                     ActionLogs.user_id == user_id,
                     ActionLogs.item_id == item_id,
                     ActionLogs.to_location_id == location_id,
                     ActionLogs.operation_type == OperationType.count
                 )
                 .order_by(ActionLogs.time_scanned.asc())
                 .all())
        
        if len(counts) < 2:
            return []
        
        consumption_periods = []
        for i in range(len(counts) - 1):
            start_count = counts[i]
            end_count = counts[i + 1]
            
            # Only include periods where the end count is NOT a restock
            if not end_count.estimated_restock:
                consumption_periods.append((start_count, end_count))
        
        return consumption_periods