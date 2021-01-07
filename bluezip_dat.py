import lxml.etree as ET
from collections import namedtuple

DOCTYPE = '<!DOCTYPE datafile PUBLIC "-//Logiqx//DTD ROM Management Datafile//EN" "http://www.logiqx.com/Dats/datafile.dtd">'

def namedtuple_factory(cursor, row):
    """Returns sqlite rows as named tuples."""
    fields = [col[0] for col in cursor.description]
    Row = namedtuple("Row", fields)
    return Row(*row)

def export_dat(db, filename):
    db.row_factory = namedtuple_factory
    root = ET.Element('datafile')
    header = ET.SubElement(root, 'header')
    ET.SubElement(header, 'name').text = 'BlueMaxima\'s Flashpoint'
    ET.SubElement(header, 'description').text = 'BlueMaxima\'s Flashpoint'
    ET.SubElement(header, 'author').text = 'Flashpoint contributors'
    ET.SubElement(header, 'homepage').text = 'BlueMaxima\'s Flashpoint'
    ET.SubElement(header, 'url').text = 'https://bluemaxima.org/flashpoint/'
    c = db.cursor()
    c.execute('SELECT * FROM game')
    for game in c:
        f = db.cursor()
        f.execute("SELECT file, size, printf('%X', crc) AS crc, hex(md5) AS md5, hex(sha1) AS sha1 FROM file WHERE game_sha = ?", (game.sha256,))
        elem = ET.SubElement(root, 'game', name=game.id)
        ET.SubElement(elem, 'description').text = game.title
        for entry in f:
            ET.SubElement(elem, 'rom', name=f'{entry.file}', size=str(entry.size), crc=entry.crc, md5=entry.md5, sha1=entry.sha1, status='verified')

    tree = ET.ElementTree(root)
    xml = ET.tostring(tree, pretty_print=True, xml_declaration=True, encoding="UTF-8", doctype=DOCTYPE)
    with open(filename, 'wb') as f:
        f.write(xml)
