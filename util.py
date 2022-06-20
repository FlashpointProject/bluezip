import sqlite3
import zlib
import re
import os
import sys
import shutil
import stat

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

def is_gamezip(entries):
    return set(entries) == {'content', 'content.json'}

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

def shutil_move(src, dst, copy_function=copy2, rmtree_onerror=None):
    """Recursively move a file or directory to another location. This is
    similar to the Unix "mv" command. Return the file or directory's
    destination.

    If the destination is a directory or a symlink to a directory, the source
    is moved inside the directory. The destination path must not already
    exist.

    If the destination already exists but is not a directory, it may be
    overwritten depending on os.rename() semantics.

    If the destination is on our current filesystem, then rename() is used.
    Otherwise, src is copied to the destination and then removed. Symlinks are
    recreated under the new name if os.rename() fails because of cross
    filesystem renames.

    The optional `copy_function` argument is a callable that will be used
    to copy the source or it will be delegated to `copytree`.
    By default, copy2() is used, but any function that supports the same
    signature (like copy()) can be used.

    The optional `rmtree_onerror` argument is a callable that will be used
    as the "onerror" argument to rmtree(), if it gets called.

    A lot more could be done here...  A look at a mv.c shows a lot of
    the issues this implementation glosses over.

    """
    sys.audit("shutil.move", src, dst)
    real_dst = dst
    if os.path.isdir(dst):
        if _samefile(src, dst):
            # We might be on a case insensitive filesystem,
            # perform the rename anyway.
            os.rename(src, dst)
            return

        # Using _basename instead of os.path.basename is important, as we must
        # ignore any trailing slash to avoid the basename returning ''
        real_dst = os.path.join(dst, _basename(src))

        if os.path.exists(real_dst):
            raise Error("Destination path '%s' already exists" % real_dst)
    try:
        os.rename(src, real_dst)
    except OSError:
        if os.path.islink(src):
            linkto = os.readlink(src)
            os.symlink(linkto, real_dst)
            os.unlink(src)
        elif os.path.isdir(src):
            if _destinsrc(src, dst):
                raise Error("Cannot move a directory '%s' into itself"
                            " '%s'." % (src, dst))
            if (_is_immutable(src)
                    or (not os.access(src, os.W_OK) and os.listdir(src)
                        and sys.platform == 'darwin')):
                raise PermissionError("Cannot move the non-empty directory "
                                      "'%s': Lacking write permission to '%s'."
                                      % (src, src))
            shutil.copytree(src, real_dst, copy_function=copy_function,
                            symlinks=True)
            shutil.rmtree(src, onerror=rmtree_onerror)
        else:
            copy_function(src, real_dst)
            os.unlink(src)
    return real_dst

def _samefile(src, dst):
    # Macintosh, Unix.
    if isinstance(src, os.DirEntry) and hasattr(os.path, 'samestat'):
        try:
            return os.path.samestat(src.stat(), os.stat(dst))
        except OSError:
            return False

    if hasattr(os.path, 'samefile'):
        try:
            return os.path.samefile(src, dst)
        except OSError:
            return False

    # All other platforms: check for same pathname.
    return (os.path.normcase(os.path.abspath(src)) ==
            os.path.normcase(os.path.abspath(dst)))

def _is_immutable(src):
    st = _stat(src)
    immutable_states = [stat.UF_IMMUTABLE, stat.SF_IMMUTABLE]
    return hasattr(st, 'st_flags') and st.st_flags in immutable_states

def _basename(path):
    """A basename() variant which first strips the trailing slash, if present.
    Thus we always get the last component of the path, even for directories.

    path: Union[PathLike, str]

    e.g.
    >>> os.path.basename('/bar/foo')
    'foo'
    >>> os.path.basename('/bar/foo/')
    ''
    >>> _basename('/bar/foo/')
    'foo'
    """
    path = os.fspath(path)
    sep = os.path.sep + (os.path.altsep or '')
    return os.path.basename(path.rstrip(sep))

def _destinsrc(src, dst):
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not src.endswith(os.path.sep):
        src += os.path.sep
    if not dst.endswith(os.path.sep):
        dst += os.path.sep
    return dst.startswith(src)
