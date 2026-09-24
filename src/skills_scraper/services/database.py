import os
import datetime
from tinydb import TinyDB, Query
from skills_scraper.config.settings import DATA_FOLDER_NAME

class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Database, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize the database by loading from file or creating default structure."""
        self.db_path = os.path.join(DATA_FOLDER_NAME, 'database.json')
        # TinyDB handles file creation
        self.db = TinyDB(self.db_path, indent=2, encoding='utf-8')
        
        # Ensure metadata exists
        self.metadata_table = self.db.table('metadata')
        if not self.metadata_table.all():
            self.update_metadata()

    def update_metadata(self):
        """Update the metadata table with app info and timestamp."""
        info = {
            'app_name': 'CSBHelper',
            'description': 'Google Cloud Skills Boost Helper and Scraper',
            'version': '1.0.0',
            'site_url': 'https://www.skills.google/',
            'last_modified': datetime.datetime.now().isoformat()
        }
        # Assuming metadata is a single document, we upsert based on a fixed ID or clear and insert
        # For simplicity, clear and insert
        self.metadata_table.truncate()
        self.metadata_table.insert(info)

    def upsert(self, table_name: str, data: dict):
        """
        Update or insert a document into the specified table.
        Uses 'id' as the unique key.
        """
        table = self.db.table(table_name)
        doc_id = str(data.get('id'))
        
        if not doc_id:
            print(f"Error: Cannot upsert item without ID into {table_name}")
            return

        # Use Query to find existing document
        Item = Query()
        table.upsert(data, Item.id == doc_id)
        
        # Update metadata timestamp
        # self.update_metadata() # Avoid frequent writes, maybe just on batch?
        # For now, let's update timestamp in metadata without full rewrite if possible, 
        # but TinyDB doesn't support partial update easily without query. 
        # Let's skip metadata update on every single upsert for performance, 
        # or do it if it's critical. 
        # User requested: "update will be saved back to the data/database.json"
        # So we should probably keep it up to date.
        
        # Optimization: Only update metadata if enough time passed? 
        # Or just update it.
        # self.update_metadata() 

    def search(self, table_name: str, query_str: str, field: str = None):
        """
        Search for documents in the specified table matching the query string.
        Returns a list of matching documents (values).
        """
        table = self.db.table(table_name)
        results = []
        
        query_str_lower = query_str.lower()
        
        # TinyDB search is robust but for free-text search across fields or specific field
        # we might need to iterate or use custom test.
        # Iterating all documents is similar to what we did before.
        
        all_items = table.all()
        for item in all_items:
            if field:
                val = item.get(field)
                if val:
                    # Handle list fields (e.g. topics)
                    if isinstance(val, list):
                         # check if query is in any of the list items
                         if any(query_str_lower in str(v).lower() for v in val):
                             results.append(item)
                    elif query_str_lower in str(val).lower():
                        results.append(item)
            else:
                # Search across the whole document
                if query_str_lower in str(item).lower():
                    results.append(item)
                    
        return results

    def get(self, table_name: str, doc_id: str):
        """Get a document by ID."""
        table = self.db.table(table_name)
        Item = Query()
        result = table.search(Item.id == str(doc_id))
        return result[0] if result else None

    def all(self, table_name: str):
        """Get all documents from a table."""
        table = self.db.table(table_name)
        return table.all()
    
    def close(self):
        self.db.close()
