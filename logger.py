import os
import yaml
from datetime import datetime, timedelta
from pathlib import Path
import glob
from loguru import logger

def setup_logger():
    """Setup loguru logger with configuration from config.yml"""
    with open("config.yml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        log_config = config.get("logging", {})
        
    log_dir = log_config.get("directory", "logs")
    max_size_gb = log_config.get("retention", {}).get("max_size_gb", 5)
    max_days = log_config.get("retention", {}).get("max_days", 30)
    level = log_config.get("level", "INFO")
    
    # Create logs directory if it doesn't exist
    os.makedirs(log_dir, exist_ok=True)
    
    # Remove default handler
    logger.remove()
    
    # Add file handler with rotation
    log_file = os.path.join(log_dir, "{time:YYYY-MM-DD}.log")
    logger.add(
        log_file,
        rotation="00:00",  # Create new file at midnight
        compression="zip",  # Compress rotated files
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        enqueue=True,  # Thread-safe logging
        backtrace=True,  # Detailed traceback
        diagnose=True,  # Even more detailed traceback
    )
    
    # Add console handler
    logger.add(
        sink=lambda msg: print(msg),
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        colorize=True,
        enqueue=True,
    )
    
    # Apply unified retention policy
    apply_retention_policy(log_dir, max_size_gb, max_days)

def apply_retention_policy(log_dir, max_size_gb, max_days):
    """Apply unified size and age based retention policy
    
    The policy works as follows:
    1. First, remove all files older than max_days
    2. Then, if total size is still over max_size_gb, remove oldest files until size is under limit
    
    This ensures both policies are satisfied while keeping the most recent logs.
    """
    log_files = glob.glob(os.path.join(log_dir, "*.log")) + glob.glob(os.path.join(log_dir, "*.log.zip"))
    
    if not log_files:
        return
        
    # Sort files by modification time (newest first)
    log_files.sort(key=os.path.getmtime, reverse=True)
    
    current_time = datetime.now()
    retained_files = []
    
    # First pass: Keep files within age limit
    if max_days > 0:
        cutoff_date = current_time - timedelta(days=max_days)
        retained_files = [
            f for f in log_files 
            if datetime.fromtimestamp(os.path.getmtime(f)) > cutoff_date
        ]
    else:
        retained_files = log_files[:]
    
    # Second pass: Apply size limit to remaining files
    if max_size_gb > 0:
        total_size_gb = 0
        files_to_keep = []
        
        for log_file in retained_files:
            size_gb = os.path.getsize(log_file) / (1024 * 1024 * 1024)
            if total_size_gb + size_gb <= max_size_gb:
                total_size_gb += size_gb
                files_to_keep.append(log_file)
            else:
                try:
                    os.remove(log_file)
                    logger.debug(f"Removed log file due to size limit: {log_file}")
                except OSError:
                    logger.warning(f"Failed to remove old log file: {log_file}")
    
    # Remove files that didn't make the cut
    files_to_remove = set(log_files) - set(retained_files)
    for log_file in files_to_remove:
        try:
            os.remove(log_file)
            logger.debug(f"Removed log file due to age limit: {log_file}")
        except OSError:
            logger.warning(f"Failed to remove old log file: {log_file}")

# Initialize logger when module is imported
setup_logger()
