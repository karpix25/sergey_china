import logging
from sqlalchemy import inspect, text
from database import engine

logger = logging.getLogger(__name__)

def upgrade_db_schema():
    """Система автоматической миграции: добавляет недостающие колонки в БД."""
    try:
        inspector = inspect(engine)
        columns = [c['name'] for c in inspector.get_columns('videos')]
        
        needed = {
            'product_info': 'TEXT',
            'voice_gcs_path': 'VARCHAR',
            'srt_gcs_path': 'VARCHAR'
        }
        
        with engine.connect() as conn:
            for col_name, col_type in needed.items():
                if col_name not in columns:
                    logger.info(f"Adding missing column '{col_name}' to 'videos' table")
                    # Using raw SQL for ALTER TABLE as it's the simplest way for small tweaks
                    conn.execute(text(f"ALTER TABLE videos ADD COLUMN {col_name} {col_type}"))
            conn.commit()
            
        logger.info("Database schema upgrade check completed")
    except Exception as e:
        logger.error(f"Failed to upgrade database schema: {e}")
        # Note: We don't raise here to allow app to try starting anyway, 
        # though it might fail later on queries.
