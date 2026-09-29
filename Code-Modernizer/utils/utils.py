import os
import logging

def setup_logger(name):
    """
    Sets up and returns a standard configured logger.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

def sanitize_path(base_dir, requested_path):
    """
    Sanitizes a requested file path to ensure it explicitly resolves 
    inside the intended base directory. Rejects relative traversal and absolute paths.
    """
    if os.path.isabs(requested_path):
        raise ValueError(f"Absolute paths are not allowed: {requested_path}")
    if ".." in requested_path:
        raise ValueError(f"Path traversal is not allowed: {requested_path}")
        
    base_abs = os.path.abspath(base_dir)
    target_abs = os.path.abspath(os.path.join(base_dir, requested_path))
    
    # Ensure the target absolute path starts exactly with the base absolute path
    if os.path.commonpath([base_abs, target_abs]) != base_abs:
        raise ValueError(f"Path resolves outside of intended base directory: {requested_path}")
        
    return target_abs

def generate_chunk_id(index):
    """
    Standardizes the generation of chunk IDs.
    Returns strings like 'chunk_01', 'chunk_02'.
    """
    return f"chunk_{index+1:02d}"
