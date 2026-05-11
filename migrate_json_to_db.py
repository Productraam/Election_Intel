"""
Election Intelligence - JSON to Database Migration
Imports all saved_wards/*.json files into SQLite database.
Run once: py migrate_json_to_db.py
"""

import os
import sys
import json
from datetime import datetime

# Setup Flask app context
sys.path.insert(0, os.path.dirname(__file__))
from flask import Flask
from database import db, init_db, Ward, Voter, ElectionHistory

app = Flask(__name__)
init_db(app)

SAVE_DIR = os.path.join(os.path.dirname(__file__), 'saved_wards')


def migrate():
    with app.app_context():
        if not os.path.isdir(SAVE_DIR):
            print("No saved_wards/ directory found.")
            return

        files = [f for f in os.listdir(SAVE_DIR) if f.endswith('.json')]
        if not files:
            print("No JSON files found in saved_wards/")
            return

        print(f"Found {len(files)} ward files to migrate.\n")
        total_voters = 0
        total_history = 0

        for fname in sorted(files):
            fpath = os.path.join(SAVE_DIR, fname)
            file_key = fname[:-5]

            # Check if already migrated
            existing = Ward.query.filter_by(file_key=file_key).first()
            if existing:
                print(f"  SKIP  {fname} (already in DB, {existing.voters.count()} voters)")
                continue

            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            ward_name = data.get('ward_name', file_key)
            hierarchy = data.get('hierarchy', {})
            metadata = data.get('metadata', {})
            voters_data = data.get('voters', [])
            history_data = data.get('election_history', [])
            saved_at = data.get('saved_at', '')

            # Create ward
            ward = Ward(
                name=ward_name,
                file_key=file_key,
                source_filename=data.get('source_filename', ''),
            )
            ward.hierarchy = hierarchy
            ward.ward_metadata = metadata
            if saved_at:
                try:
                    ward.saved_at = datetime.fromisoformat(saved_at)
                except Exception:
                    pass

            db.session.add(ward)
            db.session.flush()  # get ward.id

            # Import voters
            for vd in voters_data:
                voter = Voter.from_dict(vd, ward.id)
                db.session.add(voter)

            # Import election history
            for hd in history_data:
                eh = ElectionHistory.from_dict(hd, ward.id)
                db.session.add(eh)

            db.session.commit()
            total_voters += len(voters_data)
            total_history += len(history_data)
            print(f"  OK    {fname} → {len(voters_data)} voters, {len(history_data)} history entries")

        print(f"\nMigration complete: {total_voters} voters, {total_history} history entries imported.")


if __name__ == '__main__':
    migrate()
