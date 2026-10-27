import base64
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Store
from app import config
from migrate_vault import migrate
from packaged import import_previous_vault
import json

class PackagingTests(unittest.TestCase):
    def test_migration_preserves_notes_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Store(Path(tmp) / 'old')
            note = source.read_note('serious-game', 'art')
            source.save_note('serious-game', 'art', 'Muted colors', note['revision'])
            attachment = source.root / 'attachments' / 'image.png'
            attachment.parent.mkdir()
            attachment.write_bytes(b'example')
            source.add_reference('Screenshot', 'serious-game', 'art', str(attachment))
            external = Path(tmp) / 'reference.txt'
            external.write_text('Keep outside vault')
            source.add_reference('External', 'serious-game', 'art', str(external))
            target = migrate(source.root, Path(tmp) / 'new')
            copied = Store(target)
            self.assertEqual(copied.read_note('serious-game', 'art')['text'], 'Muted colors')
            with copied.db() as db:
                paths = {r['path'] for r in db.execute('SELECT path FROM refs')}
            self.assertEqual(paths, {str(target / 'attachments/image.png'), str(external.resolve())})
            self.assertTrue(attachment.exists())
            with self.assertRaises(ValueError): migrate(source.root, target)

    def test_frozen_config_uses_executable_as_mcp(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, 'frozen', True, create=True):
            result = config(Store(tmp))
            self.assertIn('--mcp', result['codex'])
            self.assertNotIn('mcp_server.py', result['codex'])

    def test_first_launch_imports_connected_vault_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            source = Store(home / 'old')
            note = source.read_note('cash-grab', 'ui')
            source.save_note('cash-grab', 'ui', 'Large buttons', note['revision'])
            settings = home / 'Library/Application Support/Claude/claude_desktop_config.json'
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({'mcpServers': {'conectify': {'args': ['old.py', '--vault', str(source.root)]}}}))
            target = home / 'new'
            with patch.object(Path, 'home', return_value=home):
                import_previous_vault(target)
                import_previous_vault(target)
            self.assertEqual(Store(target).read_note('cash-grab', 'ui')['text'], 'Large buttons')
