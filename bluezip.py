#!/bin/env python3
from dataclasses import dataclass
import subprocess
import tempfile
import argparse
import datetime
import sqlite3
import hashlib
import getpass
import zipfile
import fnmatch
import socket
import json
import time
import shutil
import sys
import stat
import re
import os

import yaml
import bluezip_dat
import bluezip_hook
from util import TermColor, pcolor
import util

DATABASE_VERSION = '1'
DIST_DIR = os.path.abspath('dist')

class Settings:
    def __init__(self, db):
        self.db = db

    def get(self, key, default=None):
        try:
            return self[key]
        except IndexError:
            return default

    def __contains__(self, key):
        try:
            _ = self[key]
            return True
        except IndexError:
            return False

    def setdefault(self, key, value):
        if key not in self:
            self[key] = value
        return value

    def __getitem__(self, key):
        c = self.db.cursor()
        c.execute('SELECT value FROM setting WHERE key = ?', (key,))
        value = c.fetchone()
        if not value:
            raise IndexError()
        return value[0]

    def __setitem__(self, key, value):
        self.db.execute('REPLACE INTO setting (key, value) VALUES (?,?)', (key, value))
        self.db.commit()

    def __iter__(self):
        c = self.db.cursor()
        c.execute('SELECT key, value FROM setting')
        for key, value in c:
            yield key, value

@dataclass
class Game:
    uid: str
    title: str
    platform: str
    content_path: str

def game_from_curation(uid, curation):
    content = os.path.join(curation, 'content')
    if not os.path.isdir(content):
        raise ValueError('Missing content folder')
    meta = util.find(curation, ['meta.txt', 'meta.yml', 'meta.yaml'])
    if not meta:
        raise ValueError('Missing metadata')

    with open(meta, 'r', encoding='utf-8') as f:
        try:
            meta = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError('Malformed metadata') from e
    if not 'Title' in meta or not 'Platform' in meta:
        raise ValueError('Incomplete metadata')
    return Game(uid, meta['Title'], meta['Platform'], content)

def game_from_fp_database(uid, content_path):
    fp_db = util.open_db()
    c = fp_db.cursor()
    c.execute('SELECT title, platform FROM game WHERE id = ?', (uid,))
    game = c.fetchone()
    fp_db.close()
    if not game:
        raise ValueError(f'No game found by UUID: {uid}')

    title, platform = game
    return Game(uid, title, platform, content_path)

def create_torrentzip(uid, platform, build_dir, dist_file):
    content_meta = {
        'version': 1,
        'uniqueId': uid,
        'platform': platform
    }
    with open(os.path.join(build_dir, 'content.json'), 'w', encoding='utf-8', newline='\r\n') as f:
        json.dump(content_meta, f, indent=4)
    with zipfile.ZipFile(dist_file, 'w', strict_timestamps=False) as z:
        for r, _, f in os.walk(build_dir):
            for fname in f:
                path = os.path.join(r, fname)
                rel = os.path.relpath(path, build_dir).replace(os.path.sep, '/')
                z.write(path, arcname=rel)
    subprocess.check_call(['bin/trrntzip', dist_file], stdout=subprocess.DEVNULL)
    return util.digest(dist_file, hashlib.sha256())

def delete_paths(root, paths):
    for path in paths:
        os.remove(path)
    for path in paths:
        while True:
            try:
                path = os.path.abspath(os.path.join(path, os.pardir))
                os.rmdir(path)
                print('Removed empty folder:', os.path.relpath(path, root))
            except OSError:
                break

def rollback(db, session):
    c = db.cursor()
    c.execute("SELECT id, time FROM session WHERE operation != 'ROLLBACK' AND rollback IS NULL ORDER BY time DESC LIMIT 1")
    data = c.fetchone()
    if not data:
        print('Nothing to rollback.')
        return
    prev_session, tstamp = data
    date = datetime.datetime.fromtimestamp(tstamp)
    print(f'Rolling back database to {date}')
    if not util.prompt('Proceed?'):
        sys.exit(0)
    db.execute('DELETE FROM file WHERE game_sha IN (SELECT sha256 FROM game WHERE session = ?)', (prev_session,))
    db.execute('DELETE FROM game WHERE session = ?', (prev_session,))
    db.execute('UPDATE session SET rollback = ? WHERE id = ?', (session, prev_session))
    db.commit()

def remove_readonly(func, path, _):
    "Clear the readonly bit and reattempt the removal"
    os.chmod(path, stat.S_IWRITE)
    func(path)

class Bluezip:
    def __init__(self, db, settings, session, args):
        self.db = db
        self.settings = settings
        self.session = session
        self.args = args

    def cleanup_obsolete(self, game, sha):
        htdocs = self.args.htdocs
        if not htdocs:
            return
        c = self.db.cursor()
        c.execute('SELECT file FROM file WHERE game_sha = ?', (sha,))
        exclude = self.settings['obsolete_exclude'].split(',')
        obsolete = list()
        for (fname,) in c:
            contentless = re.sub('^content/', '', fname)
            path = os.path.abspath(os.path.join(htdocs, contentless))
            rel = os.path.relpath(path, htdocs)
            if os.path.isfile(path):
                if any([fnmatch.fnmatch(rel, rule) for rule in exclude]):
                    print('Obsolete (excluded):', rel)
                    continue
                obsolete.append(path)
                print('Obsolete:', rel)
        if len(obsolete) < int(self.settings['obsolete_threshold']):
            message = f'only {len(obsolete)}' if obsolete else 'no'
            pcolor('yellow', f'Warning: An htdocs path was provided but {message} files were found. Possibly a bad conversion?')
        if not obsolete:
            sys.exit(0)
        if util.prompt(f'Delete {len(obsolete)} files?'):
            delete_paths(htdocs, obsolete)

    def process_game(self, game):
        tmp = tempfile.mkdtemp()
        build_dir = os.path.join(tmp, 'build')
        dist = os.path.join(tmp, 'dist.zip')
        c = self.db.cursor()
        c.execute('SELECT revision, sha256, title FROM game WHERE id = ? ORDER BY revision DESC LIMIT 1', (game.uid,))
        revision, prev_sha256, prev_title = c.fetchone() or (1, None, None)
        os.mkdir(build_dir)
        util.shutil_move(game.content_path, os.path.join(build_dir, 'content'), rmtree_onerror=remove_readonly)
        sha256 = create_torrentzip(game.uid, game.platform, build_dir, dist)
        outfile = os.path.join(DIST_DIR, f'{game.uid}.zip')
        util.shutil_move(dist, outfile, rmtree_onerror=remove_readonly)
        if prev_sha256:
            if prev_sha256 == sha256:
                pcolor('green', 'no change')
                return
            revision += 1
        for r, _, f in os.walk(build_dir):
            for fname in f:
                path = os.path.join(r, fname)
                rel = os.path.relpath(path, build_dir).replace(os.path.sep, '/')
                crc = util.crc32(path)
                md5 = util.digest(path, hashlib.md5())
                sha = util.digest(path, hashlib.sha1())
                size = os.stat(path).st_size
                self.db.execute('INSERT INTO file VALUES (?,?,?,?,?,?)', (sha256, rel, size, crc, md5, sha))
        short_sha = sha256.hex()[:6].upper()
        pcolor('green', f'[rev {revision}: {short_sha}]')
        if prev_title and prev_title != game.title:
            pcolor('yellow', f'Warning: {game.uid} has been renamed ({prev_title} -> {game.title})')
        try:
            self.db.execute('INSERT INTO game VALUES (?,?,?,?,?,?)', (game.uid, revision, sha256, game.title, game.platform, self.session))
        except sqlite3.IntegrityError as e:
            pcolor('red', f'Error: {e} when storing {game.title}. Skipped.')
            return
        self.db.commit()
        shutil.rmtree(tmp, onerror=remove_readonly)
        if revision == 1:
            self.cleanup_obsolete(game, sha256)

    def process_game_from_path(self, uid, path, from_db):
        if from_db:
            game = game_from_fp_database(uid, path)
        else:
            game = game_from_curation(uid, path)
        self.process_game(game)

    def process_archive(self, fname, from_db=False):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'curation')
        subprocess.check_call(['bin/7za', 'x', f'-o{path}', fname], stdout=subprocess.DEVNULL)
        entries = os.listdir(path)
        if len(entries) == 1: # must be root folder
            uid = entries[0]
            if not util.validate_uuid(uid):
                pcolor('red', f'\nError: Root folder in {fname} not a valid UUID. Skipped.')
                return
            path = os.path.join(path, uid)
        else:
            uid, _ = os.path.splitext(os.path.basename(fname))
            if not util.validate_uuid(uid):
                pcolor('red', f'\nError: No root folder in {fname} and archive filename not a valid UUID. Skipped.')
                return
            if util.is_gamezip(entries):
                path = os.path.join(path, 'content')
        try:
            self.process_game_from_path(uid, path, from_db)
        finally:
            shutil.rmtree(tmp)

    def process_auto(self, path, from_db=False):
        kind = 'Content' if from_db else 'Curation'
        fname = os.path.basename(path)
        exts = self.settings['archive_extensions'].split(',')
        ext = util.extension(fname, exts)
        if os.path.isfile(path) and ext:
            print(f'{kind} archive ({ext}): {fname}'.ljust(80), end='', flush=True)
            self.process_archive(path, from_db)
            return
        if not os.path.isdir(path):
            return
        if not util.validate_uuid(fname):
            return
        print(f'{kind} folder: {fname}'.ljust(80), end='', flush=True)
        self.process_game_from_path(fname, path, from_db)

    def process_all(self, path):
        for name in os.listdir(path):
            try:
                self.process_auto(os.path.join(path, name))
            except ValueError as e:
                pcolor('red', f'Error: {e} in {name}. Skipped.')

def main():
    global DIST_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument('path', nargs='?')
    parser.add_argument('-c', '--convert', action='store_true')
    parser.add_argument('-b', '--batch', action='store_true')
    parser.add_argument('-o', '--output', metavar='PATH')
    parser.add_argument('--htdocs', metavar='PATH')
    parser.add_argument('--hooks', choices=['add', 'remove'])
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--dat', metavar='FILE')
    parser.add_argument('--set', nargs='?', metavar='KEY=VALUE', const=[])
    parser.add_argument('-n', '--no-color', action='store_true')
    args = parser.parse_args()

    if args.no_color:
        TermColor.ENABLE = False
    elif os.name == 'nt':
        os.system('color')

    db = sqlite3.connect('bluezip.db')
    db.execute('CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS session (id TEXT PRIMARY KEY, user TEXT, operation TEXT, time INTEGER, rollback TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS file (game_sha BLOB, file TEXT, size INTEGER, crc INTEGER, md5 BLOB, sha1 BLOB)')
    db.execute('CREATE TABLE IF NOT EXISTS game (id TEXT, revision INTEGER, sha256 BLOB UNIQUE, title TEXT, platform TEXT, session TEXT, PRIMARY KEY (id, revision))')
    session = os.urandom(6).hex()
    user = '%s@%s' % (getpass.getuser(), socket.gethostname())
    settings = Settings(db)
    settings.setdefault('version', DATABASE_VERSION)
    settings.setdefault('set_altapps', '1')
    settings.setdefault('archive_extensions', 'zip,7z')
    settings.setdefault('obsolete_threshold', '1')
    settings.setdefault('obsolete_exclude', '')

    if settings['version'] > DATABASE_VERSION:
        pcolor('yellow', 'The database was created in a newer version of bluezip. Bluezip might not work correctly and could cause data loss.')
        if not util.prompt('Proceed?'):
            sys.exit(0)

    def log_session(operation):
        db.execute('INSERT INTO session (id, user, operation, time) VALUES (?,?,?,?)', (session, user, operation, int(time.time())))
        db.commit()

    if args.output:
        DIST_DIR = args.output

    try:
        os.mkdir(DIST_DIR)
    except FileExistsError:
        pass

    bluezip = Bluezip(db, settings, session, args)
    if args.path:
        if args.batch:
            log_session('BUILD')
            bluezip.process_all(args.path)
        else:
            log_session('BUILD')
            try:
                bluezip.process_auto(args.path, args.convert)
            except ValueError as e:
                pcolor('red', f'\nError: {e}')
                sys.exit(1)
        sys.exit(0)

    if args.dat:
        bluezip_dat.export_dat(db, args.dat)
    elif args.hooks:
        bluezip_hook.run(db, args.hooks)
    elif args.rollback:
        log_session('ROLLBACK')
        rollback(db, session)
    elif args.set != None:
        pcolor('yellow', 'This command allows modification of internal database attributes. Be careful!')
        if args.set:
            if '=' not in args.set:
                parser.error('use KEY=VALUE')
                sys.exit(1)
            key, value = args.set.split('=')
            append = False
            if key.endswith('+'):
                append = True
                key = key[:-1]
            if key not in settings:
                parser.error(f'unknown attribute: {key}')
                sys.exit(1)
            old = settings[key]
            if append:
                settings[key] += value
            else:
                settings[key] = value
            print(f'Set {key}: "{old}" -> "{settings[key]}"')
        else:
            for key, value in settings:
                print(f'{key}={value}')
    else:
        parser.error('no flags specified')

if __name__ == '__main__':
    main()
