"""Independent advanced HWPX checks. No application/WASM queries.

The old unmerged-table oracle remains unchanged. Owner paths follow direct
subList ancestry, never recursive concatenation of all section hp:t nodes.
"""
from __future__ import annotations

import io
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET
from hwpx_oracle import inspect_hwpx

HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
HS = 'http://www.hancom.co.kr/hwpml/2011/section'
def q(name): return f'{{{HP}}}{name}'


def one(parent, name):
    nodes = parent.findall(q(name))
    if len(nodes) != 1:
        raise ValueError(f'Expected one direct {name}')
    return nodes[0]


def integer(node, name, *, minimum=0):
    try:
        value = int(node.attrib[name])
    except (KeyError, ValueError) as error:
        raise ValueError(f'Missing/invalid {name}') from error
    if value < minimum:
        raise ValueError(f'{name} below {minimum}')
    return value


def flow(paragraph):
    """Only visible direct paragraph flow; ctrl wrappers are transparent."""
    def visit(node):
        for child in node:
            if child.tag in (q('run'), q('ctrl')):
                yield from visit(child)
            elif child.tag in (q('t'), q('fieldBegin'), q('fieldEnd'), q('autoNum')):
                yield child
    return list(visit(paragraph))


def content(owner, owner_path):
    outside, fields, pending, paragraphs = [], [], None, []
    for para_index, paragraph in enumerate(owner.findall(q('p'))):
        para_outside = []
        for node in flow(paragraph):
            if node.tag == q('autoNum'):
                if not re.search(r'/(?:footNote|endNote)$',owner_path):
                    raise ValueError('Unexpected saved control population: automatic number outside declared note')
                continue  # Counter identity is checked in its direct note owner.
            if node.tag == q('fieldBegin'):
                if pending is not None:
                    raise ValueError('Overlapping field begin')
                params = node.findall(f"{q('parameters')}/{q('stringParam')}")
                commands = [p.text or '' for p in params if p.get('name') == 'Command']
                if len(commands) > 1:
                    raise ValueError('Duplicate field Command parameter')
                pending = {'id': str(integer(node, 'id')), 'name': node.get('name'),
                           'type': node.get('type'), 'command': commands[0] if commands else '',
                           'owner': owner_path, 'paragraph': para_index,
                           'offset': len(''.join(para_outside)), 'value': ''}
            elif node.tag == q('fieldEnd'):
                if pending is None or node.get('beginIDRef') != pending['id']:
                    raise ValueError('Field end has wrong beginIDRef/order')
                fields.append(pending); pending = None
            elif pending is None:
                value = ''.join(node.itertext())
                outside.append(value); para_outside.append(value)
            else:
                pending['value'] += ''.join(node.itertext())
        paragraphs.append(''.join(para_outside))
    if pending is not None:
        raise ValueError('Unclosed field')
    return ''.join(outside), fields, paragraphs


def owned_objects(owner):
    """Objects belonging to this paragraph list, without nested owner leakage."""
    def visit(node):
        for child in node:
            if child.tag in (q('p'), q('run'), q('ctrl')):
                yield from visit(child)
            elif child.tag in (q('tbl'), q('equation'), q('footNote'), q('endNote'),
                               q('header'), q('footer'), q('rect'), q('line'), q('ellipse')):
                yield child
            elif child.tag not in (q('t'),q('secPr'),q('colPr'),q('fieldBegin'),
                                   q('fieldEnd'),q('autoNum'),q('linesegarray')):
                # This oracle covers a declared synthetic control set. A real
                # hp:pic/ole/video or unknown direct control cannot vanish just
                # because no advanced fixture expected that control type.
                raise ValueError('Unexpected saved control population: unhandled direct '+child.tag)
    return list(visit(owner))


def reference(owner, target):
    """Actual control anchor in its direct paragraph flow, independent of ID."""
    for pi, paragraph in enumerate(owner.findall(q('p'))):
        offset = 0
        def nodes(parent):
            for child in parent:
                if child.tag in (q('run'),q('ctrl')): yield from nodes(child)
                else: yield child
        for node in nodes(paragraph):
            if node is target: return (pi,offset)
            if node.tag == q('t'): offset += len(''.join(node.itertext()))
    raise ValueError('Object has no direct paragraph anchor')


def table_grid(table, owner_path):
    rows, cols = integer(table, 'rowCnt', minimum=1), integer(table, 'colCnt', minimum=1)
    actual_rows = table.findall(q('tr'))
    if len(actual_rows) != rows or rows * cols > 65536:
        raise ValueError('Table row count differs or grid exceeds oracle limit')
    cells, occupied = {}, {}
    for actual_row, row in enumerate(actual_rows):
        for cell in row.findall(q('tc')):
            addr, span = one(cell, 'cellAddr'), one(cell, 'cellSpan')
            r, c = integer(addr, 'rowAddr'), integer(addr, 'colAddr')
            rs, cs = integer(span, 'rowSpan', minimum=1), integer(span, 'colSpan', minimum=1)
            if r != actual_row or r + rs > rows or c + cs > cols or (r, c) in cells:
                raise ValueError('Cell address/span outside grid, duplicate, or wrong tr')
            sublist = one(cell, 'subList')
            text, fields, paragraphs = content(sublist, f'{owner_path}/r{r}c{c}')
            cells[(r, c)] = {'span': (rs, cs), 'text': text, 'fields': fields, 'paragraphs': paragraphs}
            for rr in range(r, r + rs):
                for cc in range(c, c + cs):
                    if (rr, cc) in occupied:
                        raise ValueError('Merged grid has overlapping coverage')
                    occupied[(rr, cc)] = (r, c)
    if set(occupied) != {(r, c) for r in range(rows) for c in range(cols)}:
        raise ValueError('Merged grid has uncovered cells')
    return {'rows': rows, 'cols': cols, 'cells': cells, 'occupancy': occupied}


def inspect_advanced_hwpx(path):
    data = path.read_bytes() if isinstance(path, Path) else path
    inspect_hwpx(data)  # package/path/XML security stays at the existing strict boundary
    result = {'body': '', 'fields': [], 'tables': {}, 'equations': [], 'notes': [],
              'headers': [], 'footers': [], 'shapes': [], 'pages': [], 'breaks': [], 'paragraphs': {}}
    ids = set()
    def read_owner(owner, path):
        text, fields, paragraphs = content(owner, path)
        result['paragraphs'][path] = paragraphs
        for field in fields:
            if field['id'] in ids:
                raise ValueError('Duplicate field ID across owners')
            ids.add(field['id'])
        result['fields'].extend(fields)
        table_index = 0
        for obj in owned_objects(owner):
            if obj.tag == q('tbl'):
                table_path = f'{path}/t{table_index}'; table_index += 1
                result['tables'][table_path] = table_grid(obj, table_path)
                for row in obj.findall(q('tr')):
                    for cell in row.findall(q('tc')):
                        addr = one(cell, 'cellAddr')
                        read_owner(one(cell, 'subList'), f'{table_path}/r{addr.get("rowAddr")}c{addr.get("colAddr")}')
            elif obj.tag == q('equation'):
                size, pos = one(obj, 'sz'), one(obj, 'pos')
                result['equations'].append({'script': one(obj, 'script').text or '',
                    'size': (integer(size, 'width'), integer(size, 'height')),
                    'owner': path, 'anchor': dict(pos.attrib), 'id': obj.get('id'),
                    'reference': reference(owner,obj), 'base_unit': integer(obj,'baseUnit',minimum=1)})
            elif obj.tag in (q('footNote'), q('endNote'), q('header'), q('footer')):
                kind = obj.tag.rsplit('}', 1)[-1]
                sublist = one(obj, 'subList')
                inner_text, _, inner_paragraphs = content(sublist, f'{path}/{kind}')
                entry = {'kind': kind, 'text': inner_text, 'owner': path,
                         'attrs': dict(obj.attrib), 'reference': reference(owner,obj),
                         'paragraphs': inner_paragraphs,
                         'automatic_numbers': [dict(node.attrib) for paragraph in sublist.findall(q('p'))
                             for node in flow(paragraph) if node.tag == q('autoNum')]}
                key = 'notes' if kind.endswith('Note') else kind + 's'
                result[key].append(entry)
                read_owner(sublist, f'{path}/{kind}')
            else:
                size, pos = one(obj, 'sz'), one(obj, 'pos')
                draw = obj.find(q('drawText'))
                inner = one(draw, 'subList') if draw is not None else None
                shape_text = content(inner, path+'/drawText')[0] if inner is not None else ''
                result['shapes'].append({'kind': obj.tag.rsplit('}',1)[-1], 'text': shape_text,
                    'owner': path, 'size': (integer(size,'width',minimum=1), integer(size,'height',minimum=1)),
                    'anchor': dict(pos.attrib), 'line': dict(one(obj,'lineShape').attrib),
                    'has_textbox': inner is not None, 'text_wrap': obj.get('textWrap')})
                if inner is not None: read_owner(inner, path+'/drawText')
        return text
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = sorted((n for n in archive.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n)),
                       key=lambda name: int(re.search(r'(\d+)\.xml$', name)[1]))
        for si, name in enumerate(names):
            section = ET.fromstring(archive.read(name))
            if section.tag != f'{{{HS}}}sec':
                raise ValueError('Wrong section namespace/root (expected hs:sec)')
            result['body'] += read_owner(section, f's{si}/body')
            for pi, paragraph in enumerate(section.findall(q('p'))):
                if paragraph.get('pageBreak') == '1': result['breaks'].append((si, pi))
            pages = section.findall(f"{q('p')}/{q('run')}/{q('secPr')}/{q('pagePr')}")
            if len(pages) != 1:
                raise ValueError('Expected one pagePr per owned section')
            page = pages[0]
            result['pages'].append({'width': integer(page,'width',minimum=1),
                'height': integer(page,'height',minimum=1), 'landscape': page.get('landscape'),
                'margin': {k: integer(one(page,'margin'),k) for k in
                           ('left','right','top','bottom','header','footer','gutter')}})
    return result


def require_body(result, *markers):
    other = ''.join(f['value'] for f in result['fields'])
    other += ''.join(n['text'] for key in ('notes','headers','footers','shapes') for n in result[key])
    other += ''.join(c['text'] for t in result['tables'].values() for c in t['cells'].values())
    body_paragraphs = [text for path, rows in result['paragraphs'].items()
                       if re.fullmatch(r's\d+/body',path) for text in rows]
    for marker in markers:
        if (result['body'].count(marker) != 1 or marker in other
                or sum(text.count(marker) for text in body_paragraphs) != 1):
            raise ValueError('Body marker missing/duplicate or moved to another owner: '+marker)


def assert_population(result, **expected):
    for key in ('tables','fields','equations','notes','headers','footers','shapes'):
        if len(result[key]) != expected.get(key,0):
            raise ValueError('Unexpected saved control population: '+key)


def assert_checkpoint(result, *, body_paragraphs, pages, population, headers=(), footers=(), breaks=()):
    """Complete declared saved history state, independent of the last command.

    Expectations come from authored input metadata and explicit UI marker/state
    declarations. A later Redo cannot excuse body/HF/control loss in an Undo save.
    """
    assert_population(result,**population)
    body_owners = {path: rows for path,rows in result['paragraphs'].items()
                   if re.fullmatch(r's\d+/body',path)}
    if (body_owners != {'s0/body':list(body_paragraphs)}
            or result['body'] != ''.join(body_paragraphs)):
        raise ValueError('Saved history checkpoint body/paragraph ownership differs')
    if result['pages'] != pages:
        raise ValueError('Saved history checkpoint page definitions differ')
    if result['breaks'] != list(breaks):
        raise ValueError('Saved history checkpoint page breaks differ')
    for key,texts in (('headers',headers),('footers',footers)):
        actual = result[key]
        if (len(actual) != len(texts)
                or any(row['text'] != text or row['paragraphs'] != [text]
                       or row['owner'] != 's0/body' or row['attrs'].get('applyPageType') != 'BOTH'
                       for row,text in zip(actual,texts))):
            raise ValueError('Saved history checkpoint direct '+key+' differs')
    return result


def assert_grid(result, path, expected):
    table = result['tables'].get(path)
    if table is None or set(table['cells']) != set(expected):
        raise ValueError('Wrong table path/anchor addresses')
    for addr, (span, text, paragraphs) in expected.items():
        if table['cells'][addr]['span'] != span or table['cells'][addr]['text'] != text:
            raise ValueError(f'Wrong direct cell span/text at {path}/{addr}')
        if table['cells'][addr]['paragraphs'] != list(paragraphs):
            raise ValueError(f'Wrong direct cell paragraphs at {path}/{addr}')
    return table


def assert_field(result, *, name, guide, memo, value, body, anchor=None):
    assert_population(result,fields=1)
    if len(result['fields']) != 1:
        raise ValueError('Expected exactly one field begin/end pair')
    field = result['fields'][0]
    # HWPX stores guide/memo in Command wstring parameters, not invented attrs.
    units = lambda value: len(value.encode('utf-16-le'))//2
    inner = f'Direction:wstring:{units(guide)}:{guide} HelpState:wstring:{units(memo)}:{memo}  '
    expected_command = f'Clickhere:set:{units(inner)-1}:{inner}'
    if (field['name'],field['type'],field['owner'],field['value']) != (name,'CLICK_HERE','s0/body',value):
        raise ValueError('Field metadata/value/ownership differs')
    if expected_command != field['command']:
        raise ValueError('Field guide/memo Command differs')
    if anchor is not None and (field['paragraph'],field['offset']) != anchor:
        raise ValueError('Field reference moved in paragraph flow')
    require_body(result, *body)
    if value and value in result['body'] or guide in result['body'] or memo in result['body']:
        raise ValueError('Field content leaked into body')
    return field


def assert_equation(result, script, *, body, anchor=None, dimensions_hu=(2712,2440)):
    assert_population(result,equations=1)
    if len(result['equations']) != 1 or result['equations'][0]['script'] != script:
        raise ValueError('Expected exactly one equation with the exact script')
    eq = result['equations'][0]
    if eq['owner'] != 's0/body' or eq['anchor'].get('treatAsChar') != '1' or min(eq['size']) <= 0 or eq['base_unit'] != 1000:
        raise ValueError('Equation moved or lost inline anchor')
    # Declared x^2/x^3 + {1} over {2}, BaseUnit1000 intrinsic frame from the
    # fixed layout::EqLayout source is 2712x2440 HU. Owned input generation
    # independently confirms that contract; GUI output never supplies a golden.
    if eq['size'] != tuple(dimensions_hu):
        raise ValueError('Equation physical geometry differs from declared script frame')
    if anchor is not None and eq['reference'] != anchor:
        raise ValueError('Equation reference moved in paragraph flow')
    require_body(result, *body)
    return eq


def assert_notes(result, expected, *, body, anchors=None):
    assert_population(result,notes=len(expected))
    actual = [(n['kind'],n['text'],n['attrs'].get('number'),n['owner']) for n in result['notes']]
    if actual != [(kind,text,'1','s0/body') for kind,text in expected]:
        raise ValueError('Note count/kind/number/direct owner differs')
    if any(note['paragraphs'] != [text] for note, (_,text) in zip(result['notes'],expected)):
        raise ValueError('Note direct paragraph count/text differs')
    for note, (kind,_) in zip(result['notes'],expected):
        wanted = {'num':'1','numType':'FOOTNOTE' if kind=='footNote' else 'ENDNOTE'}
        if note['automatic_numbers'] != [wanted]:
            raise ValueError('Note direct automatic number/kind differs')
    if anchors is not None and [n['reference'] for n in result['notes']] != list(anchors):
        raise ValueError('Note references moved in paragraph flow')
    require_body(result, *body)
    return result['notes']


def assert_page(result, *, header, footer, body, margins_mm=(17,19,13,23,8,9,0)):
    assert_population(result,headers=1,footers=1)
    if len(result['pages']) != 1:
        raise ValueError('Expected one section page definition')
    wanted_margin = dict(zip(('left','right','top','bottom','header','footer','gutter'),
                            (round(mm*7200/25.4) for mm in margins_mm)))
    # Dialog uses 0.1mm inputs; A4 preset becomes 210.0×297.0mm in saved HU.
    expected = {'width': round(210*7200/25.4), 'height': round(297*7200/25.4),
                'landscape': 'NARROWLY', 'margin': wanted_margin}
    if result['pages'][0] != expected or result['breaks'] != [(0,1)]:
        raise ValueError('A4 landscape/margin/page-break definition differs')
    for key, marker in (('headers',header),('footers',footer)):
        rows = result[key]
        if len(rows) != 1 or rows[0]['text'] != marker or rows[0]['owner'] != 's0/body' or rows[0]['attrs'].get('applyPageType') != 'BOTH':
            raise ValueError('Header/footer text/direct owner/apply page differs')
    require_body(result, *body)
    paragraphs = result['paragraphs'].get('s0/body',[])
    if (len(body) != 2 or len(paragraphs) != 2
            or paragraphs[0].count(body[0]) != 1 or paragraphs[1].count(body[1]) != 1
            or body[1] in paragraphs[0] or body[0] in paragraphs[1]):
        raise ValueError('Page-break body paragraph ownership differs')
    return result


def assert_textbox(result, *, count, text='', body=(), dimensions_mm=(40,20), textbox=True):
    assert_population(result,shapes=count)
    shapes = result['shapes']
    if len(shapes) != count or result['tables']:
        raise ValueError('Wrong shape count or shape became table')
    if count:
        shape = shapes[0]
        if shape['kind'] != 'rect' or shape['text'] != text or shape['owner'] != 's0/body':
            raise ValueError('Textbox kind/text/direct ownership differs')
        if shape['has_textbox'] != textbox or textbox and shape['text_wrap'] != 'IN_FRONT_OF_TEXT':
            raise ValueError('Textbox drawText subList/floating wrap differs')
        if shape['anchor'].get('treatAsChar') != '0':
            raise ValueError('Textbox lost floating anchor')
        wanted = [round(mm*7200/25.4) for mm in dimensions_mm]
        if any(abs(a-b)>round(7200/25.4) for a,b in zip(shape['size'],wanted)):
            raise ValueError('Textbox physical dimensions differ by more than 1mm')
    require_body(result,*body)
    return shapes


def assert_equation_ink(png, box):
    """Actual captured page raster only. Bounds are public selection geometry.

    This establishes visible nonempty ink, not mathematical glyph equivalence.
    """
    from PIL import Image
    with Image.open(png) as image:
        w,h=image.size
        left,top,right,bottom = [round(v*s) for v,s in zip(box,(w,h,w,h))]
        if not (0<=left<right<=w and 0<=top<bottom<=h) or min(right-left,bottom-top)<4:
            raise ValueError('Equation raster box missing/outside page')
        crop=image.convert('RGB').crop((left+1,top+1,right-1,bottom-1))
        dark=sum(max(pixel)<110 for pixel in crop.get_flattened_data())
        if dark<12 or dark/crop.width/crop.height>.85:
            raise ValueError('Equation box contains no visible equation ink')
    return {'ink_pixels':dark,'bounds_px':[left,top,right,bottom]}
