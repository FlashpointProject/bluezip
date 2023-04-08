from unittest.mock import patch
import unittest
import tempfile
import sqlite3
import shutil
import os

import yaml

import bluezip

# chosen by fair dice roll
RANDOM_UUID = 'c27c7809-d79b-4db0-94da-df8f89955aff'

class TestTempFile(unittest.TestCase):
    DUMMY = b'LOREM IPSUM DOLOR SIT AMET'

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def join(self, path):
        return os.path.abspath(os.path.join(self.cwd, path))

    def chdir(self, path):
        self.cwd = self.join(path)

    def mkdir(self, path):
        os.makedirs(self.join(path), exist_ok=True)

    def write(self, path, content=None):
        path = self.join(path)
        parent = os.path.dirname(path)
        os.makedirs(parent, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(content or self.DUMMY)

class Test_game_from_curation(TestTempFile):
    def test_empty(self):
        self.assertRaisesRegex(ValueError, 'Missing content folder', bluezip.game_from_curation, RANDOM_UUID, self.cwd)

    def test_no_meta(self):
        self.mkdir('content')
        self.assertRaisesRegex(ValueError, 'Missing metadata', bluezip.game_from_curation, RANDOM_UUID, self.cwd)

    def test_bad_meta(self):
        self.mkdir('content')
        self.write('meta.yaml', b'"')
        self.assertRaisesRegex(ValueError, 'Malformed metadata', bluezip.game_from_curation, RANDOM_UUID, self.cwd)

    def test_incomplete_meta(self):
        self.mkdir('content')
        self.write('meta.yaml', b'')
        self.assertRaisesRegex(ValueError, 'Incomplete metadata', bluezip.game_from_curation, RANDOM_UUID, self.cwd)

    def test_integrity(self):
        self.mkdir('content')
        title = 'Alien Hominid'
        meta = { 'Title': title }
        expect = bluezip.Game(RANDOM_UUID, title, self.join('content'))
        with open(self.join('meta.yaml'), 'w') as f:
            yaml.dump(meta, f)
        game = bluezip.game_from_curation(RANDOM_UUID, self.cwd)
        self.assertEqual(expect, game)

class Test_game_from_fp_db(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE game (id TEXT PRIMARY KEY, title TEXT, platform TEXT)')

    @patch('bluezip.util')
    def test_nonexistant(self, util):
        util.open_db.return_value = self.db
        self.assertRaises(ValueError, bluezip.game_from_fp_database, RANDOM_UUID, '')

    @patch('bluezip.util')
    def test_ok(self, util):
        util.open_db.return_value = self.db
        args = (RANDOM_UUID, 'Alien Hominid', 'Flash')
        self.db.execute('INSERT INTO game VALUES (?,?,?)', args)
        expect = bluezip.Game(*args, '')
        self.assertEqual(expect, bluezip.game_from_fp_database(RANDOM_UUID, ''))

class Test_create_torrentzip(TestTempFile):
    def test_ok(self):
        expect = '815bf52d71d9db68fbd1218297a363859034e5e6ed8f1dd6cd1c3313900ff927'
        dist = self.join('game.zip')
        build = self.join('build')
        self.chdir('build/content/www.example.com')
        self.write('game.swf')
        self.write('assets/data.xml')
        self.mkdir('music')
        digest = bluezip.create_torrentzip(RANDOM_UUID, build, dist)
        self.assertEqual(expect, digest.hex())

if __name__ == '__main__':
    unittest.main()
