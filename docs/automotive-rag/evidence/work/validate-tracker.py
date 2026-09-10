"""Read-only checks of the saved Excel/JSON pair and preserved source files."""
from pathlib import Path
from hashlib import sha256
import json
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'outputs'
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
machine = json.loads((OUT / 'CC_Workshop_Implementation_Plan.json').read_text(encoding='utf-8'))
manifest = json.loads((ROOT / 'work/input-manifest.json').read_text(encoding='utf-8-sig'))
for source in manifest:
    expected = source['SHA256'].lower()
    for path in [ROOT / 'work/inputs' / source['Name'], Path('C:/Users/Warwick/Downloads') / source['Name']]:
        assert sha256(path.read_bytes()).hexdigest() == expected, f'Changed input: {path.name}'

with zipfile.ZipFile(OUT / 'CC_Workshop_Planning_Tracker.xlsx') as z:
    workbook = ET.fromstring(z.read('xl/workbook.xml'))
    names = [x.attrib['name'] for x in workbook.findall('s:sheets/s:sheet', NS)]
    assert names == ['README','Handover','Tasks','Steps','Decisions','Evidence']
    strings = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for element in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', NS):
            strings.append(''.join(element.itertext()))
    sheets = {}
    for index, name in enumerate(names, 1):
        xml = ET.fromstring(z.read(f'xl/worksheets/sheet{index}.xml'))
        rows = []
        for row in xml.findall('s:sheetData/s:row', NS):
            values = {}
            for cell in row.findall('s:c', NS):
                assert cell.get('t') != 'e', f"Formula error: {name}!{cell.get('r')}"
                value = cell.find('s:v', NS)
                text = '' if value is None else value.text or ''
                if cell.get('t') == 's':
                    text = strings[int(text)]
                elif cell.get('t') == 'inlineStr':
                    text = ''.join(cell.find('s:is', NS).itertext())
                values[''.join(c for c in cell.get('r') if c.isalpha())] = text
            rows.append(values)
        sheets[name] = rows
    handover = {row.get('A'): row.get('B') for row in sheets['Handover']}
    assert handover['Snapshot ID'] == machine['snapshot']['id']
    assert handover['Plan version'] == machine['snapshot']['plan_version']
    for name, id_key in [('Tasks','Task'),('Steps','Step ID'),('Decisions','ID'),('Evidence','#')]:
        start = 2 if name == 'Tasks' else 1
        actual = [row['A'] for row in sheets[name][start:] if row.get('A')]
        expected = [row[id_key] for row in machine['workbook_tables'][name]]
        assert actual == expected, f'{name} IDs differ from JSON'
    table_names = set()
    for name in z.namelist():
        if name.startswith('xl/tables/') and name.endswith('.xml'):
            table_names.add(ET.fromstring(z.read(name)).get('name'))
    assert table_names == {'tblTasks','tblSteps','tblDecisions','tblEvidence'}, table_names
    flattened = '\n'.join(str(v) for rows in sheets.values() for row in rows for v in row.values())
    for legacy in ['Atomic Media', 'Atomic-Chat', 'feature-atomic-code-foundation', 'a13b71a83']:
        assert legacy not in flattened, f'Legacy project text retained: {legacy}'

result = {'status':'passed','snapshot_id':machine['snapshot']['id'],
          'checks':['all three original Downloads files unchanged','six sheets and order',
                    'saved Excel/JSON IDs and snapshot agree','four named Excel tables',
                    'no cached formula errors','no legacy project content'],
          'counts':machine['snapshot']['progress']}
(ROOT / 'work/saved-tracker-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
