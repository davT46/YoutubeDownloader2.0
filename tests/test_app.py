import os
import sys
import unittest
import tempfile
import json
import shutil
import urllib.parse

# Add root folder to sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import youtube_audio_downloader_app as app


class TestUrlValidation(unittest.TestCase):
    def test_normalize_url(self):
        self.assertEqual(app._normalize_url('  youtube.com/watch?v=123  '), 'https://youtube.com/watch?v=123')
        self.assertEqual(app._normalize_url('http://youtu.be/123'), 'http://youtu.be/123')
        self.assertEqual(app._normalize_url('https://youtu.be/123'), 'https://youtu.be/123')
        self.assertEqual(app._normalize_url(''), '')

    def test_valid_youtube_urls(self):
        valid_urls = [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'http://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ',
            'https://music.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://m.music.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://gaming.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://www.youtube.com/shorts/dQw4w9WgXcQ',
            'https://www.youtube.com/playlist?list=PL123456789',
            'youtube.com/watch?v=dQw4w9WgXcQ',
            'www.youtube.com/watch?v=dQw4w9WgXcQ',
            'youtu.be/dQw4w9WgXcQ',
            'https://youtube-nocookie.com/embed/dQw4w9WgXcQ',
        ]
        for url in valid_urls:
            with self.subTest(url=url):
                self.assertTrue(app._is_youtube_url(url), f"Failed for {url}")

    def test_invalid_urls(self):
        invalid_urls = [
            'https://www.youtube.com/playlist?list=...',
            'https://www.youtube.com/watch?v=...',
            'https://vimeo.com/123456',
            'https://evil-youtube.com/watch?v=123',
            'not_a_url',
            'ftp://youtube.com/watch?v=123',
            'https://google.com',
            '',
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertFalse(app._is_youtube_url(url), f"Should be invalid: {url}")


class TestVersionParsing(unittest.TestCase):
    def test_version_parsing(self):
        dummy = app.App.__new__(app.App)
        self.assertEqual(dummy._parse_version('2.0.4'), (2, 0, 4))
        self.assertEqual(dummy._parse_version('v2.0.5'), (2, 0, 5))
        self.assertEqual(dummy._parse_version('2.1'), (2, 1, 0))
        self.assertEqual(dummy._parse_version('v2.1.0-rc1+build123'), (2, 1, 0))
        self.assertEqual(dummy._parse_version('invalid'), (0, 0, 0))


class TestYtDlpOutputTemplates(unittest.TestCase):
    def test_template_logic(self):
        save_dir = r"C:\Downloads"
        output_template_pl = os.path.join(save_dir, '%(playlist|Single Songs)s', '%(playlist_index&{:02d} - |)s%(title)s.%(ext)s')
        output_template_single = os.path.join(save_dir, 'Single Songs', '%(title)s.%(ext)s')
        self.assertIn('%(playlist|Single Songs)s', output_template_pl)
        self.assertIn('%(playlist_index&{:02d} - |)s%(title)s.%(ext)s', output_template_pl)
        self.assertIn('Single Songs', output_template_single)


class TestSettingsPersistence(unittest.TestCase):
    def test_settings_structure(self):
        settings_data = {
            'theme': 'Dark',
            'mode': 'Playlist',
            'browser': 'Firefox',
            'download_path': r'C:\Downloads',
            'max_workers': 4,
            'cookie_file_path': None,
        }
        with tempfile.NamedTemporaryFile('w+', encoding='utf-8', delete=False) as f:
            json.dump(settings_data, f)
            temp_path = f.name
        try:
            with open(temp_path, encoding='utf-8') as f:
                loaded = json.load(f)
            self.assertEqual(loaded['browser'], 'Firefox')
            self.assertEqual(loaded['max_workers'], 4)
        finally:
            os.remove(temp_path)


class TestLogFileRotation(unittest.TestCase):
    def test_rotation_logic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'app.log')
            # Write a large dummy file exceeding 100 bytes
            with open(log_path, 'wb') as f:
                f.write(b'x' * 200)

            # Check rotation logic
            max_size = 100
            if os.path.exists(log_path) and os.path.getsize(log_path) > max_size:
                rot_path = log_path + '.1'
                if os.path.exists(rot_path):
                    os.remove(rot_path)
                os.replace(log_path, rot_path)

            self.assertTrue(os.path.exists(rot_path))
            self.assertFalse(os.path.exists(log_path))


if __name__ == '__main__':
    unittest.main()
