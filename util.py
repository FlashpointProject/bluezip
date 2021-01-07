import sqlite3
import zlib
import re
import os

def open_db():
    try:
        with open('DB_PATH', 'r', encoding='utf-8') as f:
            path = f.read()
    except FileNotFoundError:
        print('\033[31mError: Please specify the path to the Flashpint database in DB_PATH.\033[0m')
        return None
    if not os.path.isfile(path):
        print('\033[31mError: Flashpoint database in DB_PATH not found.\033[0m')
        return None
    return sqlite3.connect(path)

def crc32(fname):
    prev = 0
    for line in open(fname, 'rb'):
        prev = zlib.crc32(line, prev)
    return prev & 0xFFFFFFFF

def digest(fname, h):
    with open(fname, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            h.update(chunk)
    return h.digest()

def find(path, fnames):
    for r, _, f in os.walk(path):
        for fname in f:
            if fname.lower() in fnames:
                return os.path.join(r, fname)
    return None

def validate_uuid(uid):
    return re.match('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', uid)

def suffix(fname, suffixes):
    pattern = '|'.join(suffixes)
    return re.match(f'.*({pattern})$', fname)

def extension(fname, extensions):
    m = suffix(fname, [r'\.' + ext for ext in extensions])
    if m:
        return m.group(1)[1:]
    return None

def prompt(text, default=False):
    default_dict = {
        True: '[Y/n]',
        False: '[y/N]'
    }
    default_str = default_dict[default]
    while True:
        choice = input(f'{text} {default_str} ')
        if not choice:
            return default
        if choice.lower() in ['y', 'yes']:
            return True
        if choice.lower() in ['n', 'no']:
            return False

        print('Please respond with "y" or "n".')

class TermColor:
    ENABLE = True
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    RESET = '\033[0m'

def pcolor(color, *args, sep=' ', **kwargs):
    color = getattr(TermColor, color.upper())
    text = sep.join(args)
    if TermColor.ENABLE:
        text = color + text + TermColor.RESET
    print(text, **kwargs)

def pcolor_off(color, *args, **kwargs):
    print(*args, **kwargs)

def no_color():
    global pcolor
    pcolor = pcolor_off
