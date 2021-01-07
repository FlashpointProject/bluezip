import uuid
import util

def in_bluezip(db, uid):
    c = db.cursor()
    c.execute('SELECT 1 FROM game WHERE id = ?', (uid,))
    return bool(c.fetchone())

def ensure_hook(db, fp_db, uid):
    if not in_bluezip(db, uid):
        return
    c = fp_db.cursor()
    c = fp_db.execute("SELECT id FROM additional_app WHERE parentGameId = ? AND name = 'Mount'", (uid,))
    row = c.fetchone()
    if row:
        mode = 'REPLACE'
        app_id, = row
    else:
        mode = 'INSERT'
        app_id = str(uuid.uuid4())
    fp_db.execute(f'{mode} INTO additional_app (id, applicationPath, autoRunBefore, launchCommand, name, waitForExit, parentGameId) VALUES (?,?,?,?,?,?,?)',
                  (app_id, 'FPSoftware\\fpmount\\fpmount.exe', 1, uid, 'Mount', 1, uid))

def hooks_add(db, fp_db):
    hooks_remove(db, fp_db)
    print('Adding Mount hooks, please wait..')
    games = fp_db.cursor()
    games.execute('SELECT id FROM game')
    for (uid,) in games:
        ensure_hook(db, fp_db, uid)
    fp_db.commit()

def hooks_remove(db, fp_db):
    print('Removing Mount hooks, please wait..')
    fp_db.execute("DELETE FROM additional_app WHERE name = 'Mount'")
    fp_db.commit()

OPERATIONS = {
    'add': hooks_add,
    'remove': hooks_remove
}

def run(db, arg):
    fp_db = util.open_db()
    OPERATIONS[arg](db, fp_db)
