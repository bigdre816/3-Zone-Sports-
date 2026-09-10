#!/usr/bin/env python3
"""Health check endpoint for Render and monitoring services.

This script provides a simple health check that Render can use to verify
the application is running correctly. It tests basic connectivity and
database access.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import Config
from backend.db import Database

def check_health():
    """Check application health."""
    try:
        # Load config
        config = Config.from_env()
        print(f"✓ Configuration loaded (env={config.env})")
        
        # Test database connection
        db = Database(config.database_path)
        db.execute("SELECT 1")
        db.close()
        print(f"✓ Database connection working ({config.database_path})")
        
        # Verify secrets are set (in production)
        if config.is_production:
            if config.token_secret == "three-zone-demo-token-secret-CHANGE-ME-0000000000":
                print("✗ ERROR: Token secret still has demo value")
                return False
            if config.media_service_key == "three-zone-demo-media-service-key-CHANGE-ME-000000":
                print("✗ ERROR: Media service key still has demo value")
                return False
            print("✓ Secrets are configured")
        
        print("\n✓ Health check passed")
        return True
        
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = check_health()
    sys.exit(0 if success else 1)
