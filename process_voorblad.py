"""
Automatisch invullen van voorbladen — Belisol PVC CERTIX bestelbonnen

Gebruik:
    python3 process_voorblad.py <bestelfiche.pdf> [output.pdf]

Als output.pdf niet opgegeven wordt, wordt het bestand opgeslagen als
<bestelfiche>_ingevuld.pdf in dezelfde map.

Vereisten:
    pip install pymupdf --break-system-packages
"""

import sys
import re
import shutil
import io
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    _PIL_BESCHIKBAAR = True
except ImportError:
    _PIL_BESCHIKBAAR = False

# ── Font voor maataanduidingen in tekeningen ──────────────────────────────────
_MAAT_FONT_KANDIDATEN = [
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',   # Ubuntu/Debian
    '/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf',        # Fedora/RHEL
    '/System/Library/Fonts/Helvetica.ttc',                                 # macOS
    '/Library/Fonts/Arial.ttf',                                            # macOS (Office)
]
_MAAT_FONT = next((f for f in _MAAT_FONT_KANDIDATEN if Path(f).exists()), None)

# ── Pad naar het blanco voorblad-template ──────────────────────────────────────
VOORBLAD_TEMPLATE = Path(__file__).parent / 'voorblad_template.pdf'

# ── UniColor kleurposities (y-coördinaat van elke kleuroptie) ─────────────────
UNICOLOR_Y = {
    'M9010':  197.1, 'V910N':  209.1, 'V901N':  221.1,
    'V609N':  233.1, 'V612N':  245.1, 'V504N':  257.1,
    'V511N':  269.1, 'V716N':  281.1, 'V739N':  293.1,
    'VNATN':  305.1, 'VKITN':  329.1, 'VDONKN': 341.1,
    'V916MS': 364.1, 'V716S':  376.1, 'V904MS2':399.1, 'V721MS': 422.1,
}

# ── Checkbox-kolommen (kader en vleugel) ──────────────────────────────────────
CB_KADER_X   = 41.1
CB_VLEUGEL_X = 54.5
CB_HALF_H    = 4.5

# ── Kleuren ───────────────────────────────────────────────────────────────────
BLAUW = (0.106, 0.455, 0.761)
ZWART = (0, 0, 0)
ROOD  = (1, 0, 0)
GEEL  = (1, 0.96, 0.2)  # achtergrond voor tekst die niet op voorblad past

# ── Profiel-selectie rechthoeken (Certix 82/116 × stomp/aanslag) ─────────────
PROFIEL_RECT = {
    ('certix82',  'stomp'):   fitz.Rect(248, 160, 310, 215),
    ('certix82',  'aanslag'): fitz.Rect(310, 160, 378, 215),
    ('certix116', 'stomp'):   fitz.Rect(248, 215, 310, 260),
    ('certix116', 'aanslag'): fitz.Rect(310, 215, 378, 260),
}

# ── Raamgreep/raamkruk checkbox-posities (Webdings  bbox) ──────────────────
RAAMGREEP_CB = {
    'wit':    fitz.Rect(106.5, 626.0, 113.8, 633.3),
    'zilver': fitz.Rect(161.5, 626.0, 168.8, 633.3),  # F1 = zilver
}
CB_MET_SLEUTEL = fitz.Rect(106.5, 637.9, 113.8, 645.4)

# ── Raambeslag checkbox-posities (standaard of SKG) ───────────────────────────
RAAMBESLAG_CB = {
    'standaard': fitz.Rect(106.5, 649.9, 113.8, 657.4),
    'skg':       fitz.Rect(159.2, 649.9, 168.8, 657.4),
}

# ── Raamscharnieren checkbox-posities (verdoken + kleur) ─────────────────────
SCHARNIER_CB = {
    'verdoken':  fitz.Rect(37.0,  683.4, 45.2,  691.9),
    'wit':       fitz.Rect(117.2, 683.4, 125.4, 691.9),
    'zilver':    fitz.Rect(165.3, 683.4, 173.6, 691.9),
    'antraciet': fitz.Rect(37.0,  695.4, 45.2,  703.9),
    'creme':     fitz.Rect(106.0, 695.4, 114.2, 703.9),
    'zwart':     fitz.Rect(161.0, 695.4, 169.2, 703.9),
}

# ── Deurgreep checkbox-posities (wit of zilver) ───────────────────────────────
DEURGREEP_CB = {
    'wit':    fitz.Rect(106.0, 718.4, 114.3, 726.9),
    'zilver': fitz.Rect(161.0, 718.4, 169.3, 726.9),
}

# ── Deurscharnieren checkbox-posities (kleur, nooit verdoken) ─────────────────
DEURSCHARNIEREN_CB = {
    'wit':       fitz.Rect(106.0, 740.4, 114.3, 748.9),
    'zilver':    fitz.Rect(161.0, 740.4, 169.3, 748.9),
    'creme':     fitz.Rect(106.0, 760.4, 114.2, 768.9),
    'zwart':     fitz.Rect(161.0, 760.4, 169.2, 768.9),
    'antraciet': fitz.Rect(106.0, 774.4, 114.2, 782.9),
}

# ── Beglazing (2.3.5) — posities exact gemeten via rawdict ───────────────────
# Dubbel-rij baseline y=317.58; puntjes op x≈305-320 en x≈351-366
GLAS_DUBBEL_SPOT1 = fitz.Rect(304, 307, 321, 320)   # buitenzijde — stopt vóór '/' op x=323
GLAS_DUBBEL_SPOT2 = fitz.Rect(350, 307, 370, 320)   # binnenzijde (tweede glas)
GLAS_DUBBEL_PT1   = fitz.Point(305.2, 317.6)
GLAS_DUBBEL_PT2   = fitz.Point(351.5, 317.6)

# Triple-rij baseline y=329.57; puntjes op x≈259-274, 305-320, 352-366
GLAS_TRIPLE_SPOT1 = fitz.Rect(257, 319, 275, 332)   # buitenzijde — stopt vóór '/' op x=277
GLAS_TRIPLE_SPOT2 = fitz.Rect(304, 319, 321, 332)   # middenglas — stopt vóór '/' op x=323
GLAS_TRIPLE_SPOT3 = fitz.Rect(350, 319, 370, 332)   # binnenzijde
GLAS_TRIPLE_PT1   = fitz.Point(258.8, 329.6)
GLAS_TRIPLE_PT2   = fitz.Point(305.2, 329.6)
GLAS_TRIPLE_PT3   = fitz.Point(351.6, 329.6)

# Arceringsgebieden per glasrij (niet van toepassing)
GLAS_DUBBEL_RECT  = fitz.Rect(229, 306, 372, 322)
GLAS_TRIPLE_RECT  = fitz.Rect(229, 319, 372, 335)

# ── Arceergebieden voor niet-van-toepassing secties ──────────────────────────
SECTIE_232_RECT = fitz.Rect(30, 606, 222, 704)   # 2.3.2 Raam/Window
SECTIE_233_RECT = fitz.Rect(30, 703, 222, 792)   # 2.3.3 Deur/Door

# ── Elementtypes die een opendraaiende vleugel hebben ───────────────────────
OPENDRAAIEND_KW = ['draai', 'kiep', 'opendraaiend']

# ── Trefwoorden die uit Vak B gefilterd worden ────────────────────────────────
REMOVE_KEYWORDS = [
    'certix', 'classix', 'schroefgat', 'fixatiegat',
    'kleur kader', 'kleur vleugel', 'vleugel luna', 'nachtventilatie',
    'blokvliegenhor', 'blok vliegenhor',
    'raamkruk', 'raamgreep',
    'afsluitbare raamkruk', 'afsluitbare raamgreep',
    'zichtbaar beslag', 'verdoken beslag',
    'deurgreep', 'deurkruk', 'deurscharnieren',
    'glas',
]


def arceer(p: fitz.Page, rect: fitz.Rect, kleur=None, step: int = 8) -> None:
    """Tekent diagonale lijnarcering (45°) over een rechthoekig gebied."""
    if kleur is None:
        kleur = ROOD
    x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
    for c in range(int(x0 - y1), int(x1 - y0) + 1, step):
        punten = []
        xi = c + y0
        if x0 <= xi <= x1: punten.append((xi, y0))
        xi = c + y1
        if x0 <= xi <= x1: punten.append((xi, y1))
        yi = x0 - c
        if y0 <= yi <= y1: punten.append((x0, yi))
        yi = x1 - c
        if y0 <= yi <= y1: punten.append((x1, yi))
        if len(punten) >= 2:
            p.draw_line(fitz.Point(*punten[0]), fitz.Point(*punten[1]),
                        color=kleur, width=0.4)


def normaliseer_kleur(raw: str) -> str:
    """Normaliseert een kleuromschrijving naar een standaardwaarde voor beslag/raamgreep."""
    r = raw.lower().strip()
    if 'wit' in r or 'white' in r:
        return 'wit'
    if 'zilver' in r or 'silver' in r or r == 'f1' or 'aluminium naturel' in r or 'geanodiseerd' in r:
        return 'zilver'
    if 'antraciet' in r or 'anthracite' in r:
        return 'antraciet'
    if 'crème' in r or 'creme' in r:
        return 'creme'
    if 'zwart' in r or 'black' in r:
        return 'zwart'
    return r  # onbekende kleur: geef terug als-is


def parse_glas(glas_str: str):
    """Parse een glasnotatie zoals '4/16/4' of '33.2/16/4/16/33.2'.
    Retourneert (type, lagen):
      type  = 'dubbel' (2 glaslagen) of 'triple' (3 glaslagen) of None
      lagen = lijst van glaslaag-diktes als strings (bijv. ['4', '4'] of ['33.2', '4', '33.2'])
    Even indices in de slash-splitsing zijn glaslagen, oneven zijn spouwbreedtes.
    """
    # Verwijder eventuele suffixen zoals 'TFO', 'HR++', etc.
    token = glas_str.strip().split()[0]
    delen = token.split('/')
    lagen = [delen[i] for i in range(0, len(delen), 2)]
    if len(lagen) == 2:
        return 'dubbel', lagen
    if len(lagen) == 3:
        return 'triple', lagen
    return None, lagen


def extraheer_header(doc: fitz.Document) -> dict:
    """Leest klantnaam, ordernummer, opmeter, datum opmeting, enz. uit pagina 0."""
    tekst = doc[0].get_text("text")
    regels = [r.strip() for r in tekst.split('\n') if r.strip()]
    h = {}
    for regel in regels:
        r = regel.lower()
        if re.match(r'^b[a-z]+-\d+', regel, re.I):
            h.setdefault('ordernummer', regel)
        if ('kozijn' in r or 'certix' in r) and 'kleur' not in r:
            h.setdefault('kozijn_type', regel)
        if regel.startswith('Positie'):
            h['posities'] = re.sub(r'Positie\s*:\s*', '', regel).replace(' ', '')
        m2 = re.search(
            r'datum opmeting[:\s]+([\d\s/]+).*?opmeter[:\s]+(.+)', regel, re.I
        )
        if m2:
            h['datum_opmeting'] = m2.group(1).strip()
            h['opmeter']        = m2.group(2).strip()
        if 'klantnaam' not in h:
            skip = ['bestelfiche', 'bstil', 'bfvl', 'kozijn', 'positie',
                    'handtekening', 'datum', 'opmeter', 'certix']
            if regel and not any(s in r for s in skip) and not re.match(r'\d', regel):
                h['klantnaam'] = regel
    return h


def parse_volgblad(page: fitz.Page) -> dict:
    """Leest profiel, kleuren en opties uit één volgblad-pagina."""
    tekst = page.get_text("text")
    t = tekst.lower()
    info = {
        'profiel_reeks': None, 'profiel_type': None,
        'kader_buiten': None,  'vleugel_buiten': None,
        'heeft_blokvliegenhor': False, 'heeft_schroefgat': False,
    }
    if 'certix 116' in t or 'certix blok 116' in t:
        info['profiel_reeks'] = 'certix116'
    elif 'certix 82' in t or 'certix blok 82' in t:
        info['profiel_reeks'] = 'certix82'

    if 't-kaderprofiel' in t or 'aanslag' in t:
        info['profiel_type'] = 'aanslag'
    elif 'stomp' in t:
        info['profiel_type'] = 'stomp'

    m = re.search(r'kleur kader[^:\n]*:\s*([A-Z][A-Z0-9]+)', tekst, re.I)
    if m:
        info['kader_buiten'] = m.group(1).upper()

    m2 = re.search(r'kleur vleugel[^:\n]*:\s*([A-Z][A-Z0-9]+)', tekst, re.I)
    if m2:
        val = m2.group(1).upper()
        if val != 'IDEM':
            info['vleugel_buiten'] = val
    if not info['vleugel_buiten'] and 'idem kleur kader' in t:
        info['vleugel_buiten'] = info['kader_buiten']

    info['heeft_blokvliegenhor'] = 'blokvliegenhor' in t or 'blok vliegenhor' in t
    info['heeft_schroefgat']     = 'schroefgat' in t or 'fixatiegat' in t

    # Element type (eerste regel Vak B) — bepaalt of draaiende vleugel aanwezig is
    VAK_B_clip = fitz.Rect(305, 105, 580, 300)
    vak_b_blokken = page.get_text('dict', clip=VAK_B_clip)['blocks']
    eerste_regel = ''
    for blk in vak_b_blokken:
        for line in blk.get('lines', []):
            r = ' '.join(s['text'] for s in line['spans']).strip()
            if r and r not in ('•', '•', '-'):
                eerste_regel = r
                break
        if eerste_regel:
            break
    info['element_type'] = eerste_regel
    info['is_opendraaiend'] = any(kw in eerste_regel.lower() for kw in OPENDRAAIEND_KW)
    info['heeft_afsluitbare_kruk'] = bool(
        re.search(r'afsluitbaar', t) and re.search(r'kruk|greep', t)
    )

    # Raamkruk/raamgreep kleur + SKG-beslag
    # Zoek de volledige raamkruk-regel
    m3 = re.search(r'(raam(?:kruk|greep)[^\n]*)', tekst, re.I)
    if m3:
        raamkruk_regel = m3.group(1)
        # Kleur: alles na dubbelpunt, genormaliseerd (F1 / aluminium naturel → zilver)
        m_kleur = re.search(r'raam(?:kruk|greep)\s*:\s*(.+)', raamkruk_regel, re.I)
        info['raamgreep'] = normaliseer_kleur(m_kleur.group(1).strip()) if m_kleur else None
        # SKG-beslag: aanwezig als 'SKG' in de raamkruk-regel staat
        info['raambeslag'] = 'skg' if re.search(r'skg', raamkruk_regel, re.I) else 'standaard'
    else:
        info['raamgreep'] = None
        info['raambeslag'] = None

    # Raamscharnieren: verdoken of zichtbaar beslag + kleur
    # Kleur alleen aanduiden bij zichtbaar; bij verdoken enkel het type
    m_sch = re.search(r'(verdoken|zichtbaar)\s+beslag\s*:\s*(.+)', tekst, re.I)
    if m_sch:
        info['beslag_type'] = m_sch.group(1).lower()
        if info['beslag_type'] == 'zichtbaar':
            info['beslag_kleur'] = normaliseer_kleur(m_sch.group(2).strip())
        else:
            info['beslag_kleur'] = None  # verdoken: geen kleur aanduiden
    else:
        info['beslag_type'] = None
        info['beslag_kleur'] = None

    # Deurgreep / deurkruk kleur
    m_dg = re.search(r'deur(?:greep|kruk)\s*:\s*(.+)', tekst, re.I)
    info['deurgreep'] = normaliseer_kleur(m_dg.group(1).strip()) if m_dg else None

    # Deurscharnieren kleur (nooit verdoken)
    m_ds = re.search(r'deurscharnieren\s*:\s*(.+)', tekst, re.I)
    info['deurscharnieren'] = normaliseer_kleur(m_ds.group(1).strip()) if m_ds else None

    # Beglazing: '4/16/4 TFO' of '33.2/16/4/16/33.2'
    m_glas = re.search(r'glas\s*(?:\([^)]*\))?\s*:\s*([\d./]+)', tekst, re.I)
    if m_glas:
        glas_raw = m_glas.group(1)
        info['glas_type'], info['glas_lagen'] = parse_glas(glas_raw)
        info['glas_str'] = glas_raw  # voor weergave bij inconsistentie
    else:
        info['glas_type'] = None
        info['glas_lagen'] = None
        info['glas_str'] = None

    return info


def vul_voorblad(header: dict, spec: dict) -> fitz.Document:
    """Opent het blanco template en vult alle velden in op basis van header + spec."""
    doc = fitz.open(str(VOORBLAD_TEMPLATE))
    p = doc[0]

    # Profiel-kader (blauwe rand om het juiste profieltekening-vak)
    if spec['profiel_reeks'] and spec['profiel_type']:
        key = (spec['profiel_reeks'], spec['profiel_type'])
        if key in PROFIEL_RECT:
            p.draw_rect(PROFIEL_RECT[key], color=ZWART, width=2)

    # Fixatiegaten checkbox
    if spec['heeft_schroefgat']:
        p.draw_rect(fitz.Rect(252.3, 255.7, 259.3, 262.7), color=ZWART, fill=ZWART)

    # Kleur-checkboxen
    kader  = spec.get('kader_buiten')
    vleugel = spec.get('vleugel_buiten') or kader
    if kader and kader in UNICOLOR_Y:
        cy = UNICOLOR_Y[kader] + CB_HALF_H
        p.draw_rect(
            fitz.Rect(CB_KADER_X-3.5, cy-3.5, CB_KADER_X+3.5, cy+3.5),
            color=ZWART, fill=ZWART,
        )
    if vleugel and vleugel in UNICOLOR_Y:
        cy = UNICOLOR_Y[vleugel] + CB_HALF_H
        p.draw_rect(
            fitz.Rect(CB_VLEUGEL_X-3.5, cy-3.5, CB_VLEUGEL_X+3.5, cy+3.5),
            color=ZWART, fill=ZWART,
        )

    # Raamgreep checkbox (wit of zilver/F1)
    raamgreep = spec.get('raamgreep')
    if raamgreep and raamgreep in RAAMGREEP_CB:
        p.draw_rect(RAAMGREEP_CB[raamgreep], color=ZWART, fill=ZWART)

    # Met sleutel checkbox
    if spec.get('met_sleutel'):
        p.draw_rect(CB_MET_SLEUTEL, color=ZWART, fill=ZWART)

    # Raambeslag checkbox (standaard of SKG)
    raambeslag = spec.get('raambeslag')
    if raambeslag and raambeslag in RAAMBESLAG_CB:
        p.draw_rect(RAAMBESLAG_CB[raambeslag], color=ZWART, fill=ZWART)

    # Raamscharnieren: verdoken → alleen type-checkbox; zichtbaar → alleen kleur-checkbox
    if spec.get('beslag_type') == 'verdoken':
        p.draw_rect(SCHARNIER_CB['verdoken'], color=ZWART, fill=ZWART)
    elif spec.get('beslag_type') == 'zichtbaar':
        beslag_kleur = spec.get('beslag_kleur')
        if beslag_kleur and beslag_kleur in SCHARNIER_CB:
            p.draw_rect(SCHARNIER_CB[beslag_kleur], color=ZWART, fill=ZWART)

    # Deurgreep kleur
    deurgreep = spec.get('deurgreep')
    if deurgreep and deurgreep in DEURGREEP_CB:
        p.draw_rect(DEURGREEP_CB[deurgreep], color=ZWART, fill=ZWART)

    # Deurscharnieren kleur
    deurscharnieren = spec.get('deurscharnieren')
    if deurscharnieren and deurscharnieren in DEURSCHARNIEREN_CB:
        p.draw_rect(DEURSCHARNIEREN_CB[deurscharnieren], color=ZWART, fill=ZWART)

    # Beglazing (2.3.5)
    glas_type  = spec.get('glas_type')
    glas_lagen = spec.get('glas_lagen') or []
    if glas_type == 'dubbel' and len(glas_lagen) >= 2:
        for spot, pt, waarde in [
            (GLAS_DUBBEL_SPOT1, GLAS_DUBBEL_PT1, glas_lagen[0]),
            (GLAS_DUBBEL_SPOT2, GLAS_DUBBEL_PT2, glas_lagen[1]),
        ]:
            p.draw_rect(spot, color=None, fill=(1, 1, 1))   # bedek puntjes
            p.insert_text(pt, waarde, fontsize=9, color=ZWART)
        arceer(p, GLAS_TRIPLE_RECT)   # triple niet van toepassing
    elif glas_type == 'triple' and len(glas_lagen) >= 3:
        for spot, pt, waarde in [
            (GLAS_TRIPLE_SPOT1, GLAS_TRIPLE_PT1, glas_lagen[0]),
            (GLAS_TRIPLE_SPOT2, GLAS_TRIPLE_PT2, glas_lagen[1]),
            (GLAS_TRIPLE_SPOT3, GLAS_TRIPLE_PT3, glas_lagen[2]),
        ]:
            p.draw_rect(spot, color=None, fill=(1, 1, 1))
            p.insert_text(pt, waarde, fontsize=9, color=ZWART)
        arceer(p, GLAS_DUBBEL_RECT)   # dubbel niet van toepassing

    # Frame-kleur (blokvliegenhor)
    if spec['heeft_blokvliegenhor'] and kader:
        p.insert_text(fitz.Point(296, 776), kader, fontsize=9, color=ZWART)

    # Bicolor-vak arceren als kader en vleugel dezelfde kleur hebben (unicolor)
    BICOLOR_RECT = fitz.Rect(37, 442, 225, 607)
    is_bicolor = kader and vleugel and kader != vleugel
    if not is_bicolor:
        arceer(p, BICOLOR_RECT)

    # Sectie 2.3.2 arceren als er geen ramen/kozijnen zijn
    if not spec.get('heeft_ramen', True):
        arceer(p, SECTIE_232_RECT)

    # Sectie 2.3.3 arceren als er geen deuren zijn
    if not spec.get('heeft_deuren', False):
        arceer(p, SECTIE_233_RECT)


    # Klantgegevens
    if header.get('klantnaam'):
        p.insert_text(fitz.Point(500, 234), header['klantnaam'], fontsize=8, color=ZWART)
    if header.get('opmeter'):
        p.insert_text(fitz.Point(500, 769), header['opmeter'], fontsize=8, color=ZWART)
    # Vandaag als invuldatum
    vandaag = date.today().strftime('%d/%m/%Y')
    p.insert_text(fitz.Point(440, 749), vandaag, fontsize=8, color=ZWART)

    return doc


def process_volgblad(page: fitz.Page, afwijkingen: list = None) -> None:
    """Wist Vak B en herplaatst de relevante regels (zonder technische trefwoorden).

    afwijkingen: optionele lijst van strings die als rode notities worden toegevoegd,
                 bijv. ['Afwijkende beglazing: 4/16/4 (voorblad: 33.2/16/4/16/33.2)']
    """
    VAK_B = fitz.Rect(305, 105, 580, 300)
    blokken = page.get_text("dict", clip=VAK_B)["blocks"]
    regels = []
    for blk in blokken:
        for line in blk.get("lines", []):
            tekst = " ".join(s["text"] for s in line["spans"]).strip()
            # Filter lege regels en losse opsommingstekens
            if tekst and tekst not in ('•', '•', '-', ''):
                regels.append(tekst)
    behoud = [r for r in regels if not any(kw in r.lower() for kw in REMOVE_KEYWORDS)]

    page.add_redact_annot(VAK_B, fill=(1, 1, 1))
    page.apply_redactions()

    y = VAK_B.y0 + 8
    for r in behoud:
        # Gele achtergrond: tekst die niet op het voorblad gezet kon worden
        page.draw_rect(
            fitz.Rect(VAK_B.x0 + 2, y - 7, VAK_B.x1 - 4, y + 2),
            color=None, fill=GEEL,
        )
        page.insert_text(fitz.Point(VAK_B.x0 + 4, y), r, fontsize=7, color=ZWART)
        y += 10

    # Afwijkingen van het voorblad in rood onderaan Vak B
    ROOD = (0.85, 0.1, 0.1)
    ROOD_LICHT = (1.0, 0.88, 0.88)
    for a in (afwijkingen or []):
        if y + 10 > VAK_B.y1:
            break  # geen ruimte meer
        page.draw_rect(
            fitz.Rect(VAK_B.x0 + 2, y - 7, VAK_B.x1 - 4, y + 2),
            color=None, fill=ROOD_LICHT,
        )
        page.insert_text(fitz.Point(VAK_B.x0 + 4, y), f'⚠ {a}', fontsize=7, color=ROOD)
        y += 10


# ── Automatische verwerking (geen gebruikersinput) ────────────────────────────

RAAM_KW = ['raam', 'kozijn', 'kiep', 'schuif', 'vast']


def _meest_voorkomend(waarden: list):
    """Retourneert de meest voorkomende waarde in een lijst, of None als de lijst leeg is."""
    return max(set(waarden), key=waarden.count) if waarden else None


def extraheer_header_uit_volgblad(page: fitz.Page) -> dict:
    """Leest ordernummer, klantnaam, opmeter en datum uit de footer van een volgblad."""
    tekst = page.get_text('text')
    regels = [r.strip() for r in tekst.split('\n') if r.strip()]
    h = {}

    for regel in regels:
        r = regel.lower()
        # Ordernummer: patroon BSTIL-XXXXXXX-XX of BFVL-XXXXXXX-XX
        if re.match(r'^b[a-z]+-\d+', regel, re.I) and '-' in regel:
            # Kan "BSTIL-0471937-TF - Kiers Jip" zijn
            delen = regel.split(' - ', 1)
            h.setdefault('ordernummer', delen[0].strip())
            if len(delen) > 1 and 'klantnaam' not in h:
                h['klantnaam'] = delen[1].strip()

        # "Datum opmeting: 15/06/2026 - Opmeter: Ruud van Beurden"
        m = re.search(r'datum opmeting[:\s]+([\d/\s]+)[–\-]+\s*opmeter[:\s]+(.+)', regel, re.I)
        if m:
            h['datum_opmeting'] = m.group(1).strip()
            h['opmeter']        = m.group(2).strip()

        # Fallback: aparte regels
        m2 = re.search(r'datum opmeting[:\s]+([\d/\s]+)', regel, re.I)
        if m2 and 'datum_opmeting' not in h:
            h['datum_opmeting'] = m2.group(1).strip()
        m3 = re.search(r'opmeter[:\s]+(.+)', regel, re.I)
        if m3 and 'opmeter' not in h:
            h['opmeter'] = m3.group(1).strip()

    return h


def bepaal_groep_spec(specs: list) -> dict:
    """Bepaalt automatisch de consensus-spec voor een groep volgbladen.

    Neemt per veld de meest voorkomende waarde. Geen gebruikersinput.
    """
    merged = specs[0].copy()

    merged['heeft_ramen']  = any(any(kw in s.get('element_type', '').lower() for kw in RAAM_KW) for s in specs)
    merged['heeft_deuren'] = any('deur' in s.get('element_type', '').lower() for s in specs)

    # Enkelvoudige velden: meest voorkomende waarde
    for veld in ('raamgreep', 'raambeslag', 'beslag_type', 'beslag_kleur',
                 'deurgreep', 'deurscharnieren', 'kader_buiten', 'vleugel_buiten',
                 'profiel_reeks', 'profiel_type'):
        waarden = [s[veld] for s in specs if s.get(veld)]
        merged[veld] = _meest_voorkomend(waarden)

    # Profieltype standaard aanslag als niet gevonden
    if not merged.get('profiel_type'):
        merged['profiel_type'] = 'aanslag'

    # Beglazing: meest voorkomende combinatie
    glas_types     = [s['glas_type']          for s in specs if s.get('glas_type')]
    glas_lagen_all = [tuple(s['glas_lagen'])   for s in specs if s.get('glas_lagen')]
    merged['glas_type']  = _meest_voorkomend(glas_types)
    merged['glas_lagen'] = list(_meest_voorkomend(glas_lagen_all)) if glas_lagen_all else None
    merged['glas_str']   = '/'.join(_meest_voorkomend(glas_lagen_all)) if glas_lagen_all else None

    # Afsluitbare kruk
    opendraaiend = [s for s in specs if s.get('is_opendraaiend')]
    afs_count    = sum(1 for s in opendraaiend if s.get('heeft_afsluitbare_kruk'))
    merged['met_sleutel'] = (afs_count == len(opendraaiend) and afs_count > 0)

    # Boolean velden: True als één volgblad het heeft
    merged['heeft_blokvliegenhor'] = any(s.get('heeft_blokvliegenhor') for s in specs)
    merged['heeft_schroefgat']     = any(s.get('heeft_schroefgat')     for s in specs)

    return merged


def zoek_afwijkingen(spec: dict, groep_spec: dict) -> list:
    """Vergelijkt één volgblad-spec met de groep-consensus en geeft afwijkingen terug."""
    afwijkingen = []

    def check(veld, label, waarde_spec=None, waarde_groep=None):
        v = waarde_spec if waarde_spec is not None else spec.get(veld)
        g = waarde_groep if waarde_groep is not None else groep_spec.get(veld)
        if v and g and str(v).lower() != str(g).lower():
            afwijkingen.append(f'{label}: {v} (voorblad: {g})')

    check('glas_str',        'Afwijkende beglazing')
    check('profiel_type',    'Afwijkend profiel')
    check('raamgreep',       'Afwijkende raamkruk')
    check('raambeslag',      'Afwijkend raambeslag')
    check('beslag_type',     'Afwijkend scharnier-type')
    check('beslag_kleur',    'Afwijkende scharnier-kleur')
    check('deurgreep',       'Afwijkende deurgreep')
    check('deurscharnieren', 'Afwijkende deurscharnieren')
    check('kader_buiten',    'Afwijkende kaderkleur')
    check('vleugel_buiten',  'Afwijkende vleugel-kleur')

    return afwijkingen


def groepeer_volgbladen(specs: list) -> list:
    """Groepeert volgblad-specs in [ramen/kozijnen, deuren].

    Retourneert lijst van (naam, [indices]) tuples.
    Elementen waarvan het type niet herkend wordt gaan bij ramen.
    """
    ramen_idx  = []
    deuren_idx = []
    for i, s in enumerate(specs):
        et = s.get('element_type', '').lower()
        if 'deur' in et:
            deuren_idx.append(i)
        else:
            ramen_idx.append(i)  # ramen, kozijnen, onbekend → bij ramen

    groepen = []
    if ramen_idx:
        groepen.append(('Ramen / Kozijnen', ramen_idx))
    if deuren_idx:
        groepen.append(('Deuren', deuren_idx))
    return groepen


def verwerk_automatisch(volgbladen_pad: str, output_pad: str = None,
                         maat_wijzigingen: dict = None) -> str:
    """Verwerkt een PDF met alleen volgbladen en genereert automatisch de juiste voorbladen.

    maat_wijzigingen: optioneel dict {pagina_index_in_volgbladen: {'breedte': 'oud=nieuw', 'hoogte': '...'}}
    """
    if output_pad is None:
        p = Path(volgbladen_pad)
        output_pad = str(p.parent / (p.stem + '_ingevuld.pdf'))

    vb_doc = fitz.open(volgbladen_pad)
    n      = len(vb_doc)

    # Header extraheren uit de eerste volgblad
    header = extraheer_header_uit_volgblad(vb_doc[0])

    # Alle volgbladen parsen
    specs = [parse_volgblad(vb_doc[i]) for i in range(n)]

    # Groeperen
    groepen = groepeer_volgbladen(specs)

    # Output-document opbouwen
    result = fitz.open()   # leeg document

    for groep_naam, groep_idx in groepen:
        groep_specs = [specs[i] for i in groep_idx]
        groep_spec  = bepaal_groep_spec(groep_specs)

        # Voorblad genereren voor deze groep
        voorblad_doc = vul_voorblad(header, groep_spec)
        result.insert_pdf(voorblad_doc)

        # Volgbladen verwerken en toevoegen
        for i in groep_idx:
            page = vb_doc[i]

            # Maataanpassingen (optioneel)
            if maat_wijzigingen and i in maat_wijzigingen:
                w = maat_wijzigingen[i]
                for invoer, zone in ((w.get('breedte', ''), 'bottom'),
                                     (w.get('hoogte',  ''), 'right')):
                    if invoer and '=' in invoer:
                        try:
                            oud, nieuw = [int(x.strip()) for x in invoer.split('=', 1)]
                            wijzig_maat_in_tekening(page, oud, nieuw, zone=zone)
                        except ValueError:
                            pass

            # Afwijkingen bepalen en in Vak B schrijven
            afwijkingen = zoek_afwijkingen(specs[i], groep_spec)
            process_volgblad(page, afwijkingen)

            # Volgblad toevoegen aan output
            result.insert_pdf(vb_doc, from_page=i, to_page=i)

    result.save(output_pad)
    print(f'✅ Opgeslagen: {output_pad}  ({len(groepen)} voorblad(en), {n} volgblad(en))')
    return output_pad


def _zoek_getal_bbox(arr, getal_str, zone='bottom'):
    """Zoekt de pixel-bbox van getal_str in een numpy-afbeelding.

    Maatstrategie:
    - 'bottom': breedte-maataanduiding (onderste 15% van afbeelding, horizontaal gecentreerd)
    - 'right':  hoogte-maataanduiding  (rechtse 15%, verticaal gecentreerd, 90° gedraaid)

    Retourneert (x0, y0, x1, y1) of None.
    """
    h, w = arr.shape[:2]

    if zone == 'bottom':
        y_start = int(h * 0.85)
        strip = arr[y_start:, :]
    else:  # 'right'
        x_start = int(w * 0.85)
        strip = np.rot90(arr[:, x_start:], k=1)   # roteer 90° → zoek als horizontale tekst
        y_start = 0

    dark = (strip < 100).any(axis=2)
    sh, sw = dark.shape

    # Markeer "lijnrijen": rijen met > 30% donkere pixels = maatlijnen, geen tekst
    row_totals = dark.sum(axis=1)
    lijnrijen = set(i for i, c in enumerate(row_totals) if c > sw * 0.30)

    # Bouw een "tekst-only" masker: lijnrijen op nul zetten
    tekst_mask = dark.copy()
    for r in lijnrijen:
        tekst_mask[r, :] = False

    # Kolomtelling op basis van tekst-only masker, exclusief pijlmarge (5%)
    margin = max(5, int(sw * 0.05))
    col_counts = tekst_mask[:, margin:sw - margin].sum(axis=0)

    # Drempel: minstens 10% van strip-hoogte donkere tekstrijen (slaat maatlijnen over)
    threshold = max(4, int(sh * 0.10))

    # Vind aaneengesloten kolomgroepen boven drempel (= letterkolommen)
    groups, in_grp, start = [], False, None
    for i, c in enumerate(col_counts):
        if c >= threshold and not in_grp:
            in_grp, start = True, i + margin
        elif c < threshold // 2 and in_grp:
            in_grp = False
            groups.append((start, i + margin - 1))
    if in_grp:
        groups.append((start, sw - margin - 1))

    if not groups:
        return None

    # Groepen binnen 15 px samenvoegen (inter-cijfer gaps in bijv. "980")
    merged = [list(groups[0])]
    for g in groups[1:]:
        if g[0] - merged[-1][1] <= 15:
            merged[-1][1] = g[1]   # verleng huidig blok
        else:
            merged.append(list(g))

    # Neem de meest gecentreerde groep (pijlpunten / losse tekens zitten aan de randen)
    cx = sw // 2
    best = min(merged, key=lambda g: abs((g[0] + g[1]) // 2 - cx))
    gx0, gx1 = best

    # Y-grenzen: alleen tekstrijen (geen maatlijnen) binnen de gevonden kolommen
    col_slice = tekst_mask[:, gx0:gx1 + 1]
    ry_indices = [i for i, v in enumerate(col_slice.any(axis=1)) if v]
    if not ry_indices:
        return None
    ry0, ry1 = ry_indices[0], ry_indices[-1]

    if zone == 'bottom':
        return (gx0, y_start + ry0, gx1, y_start + ry1)
    else:
        # Terugrekenen vanuit de geroteerde strip naar originele afbeelding
        orig_x0 = x_start + sh - 1 - ry1
        orig_x1 = x_start + sh - 1 - ry0
        orig_y0 = gx0
        orig_y1 = gx1
        return (orig_x0, orig_y0, orig_x1, orig_y1)


def wijzig_maat_in_tekening(page: fitz.Page, oude_maat: int, nieuwe_maat: int,
                             zone: str = 'auto') -> bool:
    """Vervangt een maataanduiding in de ingebedde tekening op een volgblad.

    Args:
        page:       de volgblad-pagina (wordt in-place gewijzigd)
        oude_maat:  te vervangen maat in mm (bijv. 980)
        nieuwe_maat: nieuwe maat in mm (bijv. 1080)
        zone:       'bottom' (breedte), 'right' (hoogte), of 'auto' (probeer beide)

    Returns:
        True als de maat gevonden en vervangen is.
    """
    if not _PIL_BESCHIKBAAR:
        print('⚠️  PIL/numpy niet beschikbaar — installeer met: pip install pillow numpy --break-system-packages')
        return False

    old_str = str(oude_maat)
    new_str = str(nieuwe_maat)

    imgs = page.get_images(full=True)
    if not imgs:
        print(f'⚠️  Geen afbeelding gevonden op pagina {page.number + 1}')
        return False

    doc = page.parent
    # Pak de grootste afbeelding (= de tekening)
    best = max(imgs, key=lambda i: i[2] * i[3])
    xref = best[0]
    raw = doc.extract_image(xref)
    img = Image.open(io.BytesIO(raw['image'])).convert('RGB')
    arr = np.array(img)

    # Zoek de bbox van old_str
    zones_to_try = ['bottom', 'right'] if zone == 'auto' else [zone]
    bbox = None
    found_zone = None
    for z in zones_to_try:
        bbox = _zoek_getal_bbox(arr, old_str, zone=z)
        if bbox:
            found_zone = z
            break

    if bbox is None:
        print(f'⚠️  Maat "{old_str}" niet gevonden in tekening op pagina {page.number + 1}')
        return False

    x0, y0, x1, y1 = bbox
    cx = (x0 + x1) // 2
    target_w = x1 - x0

    # Pas font size aan zodat old_str even breed is als in template
    if not _MAAT_FONT:
        print('⚠️  Geen geschikt font gevonden — maataanpassing overgeslagen')
        return False

    font_size = 10
    for fs in range(10, 120):
        font = ImageFont.truetype(_MAAT_FONT, fs)
        bb = font.getbbox(old_str)
        if bb[2] - bb[0] >= target_w:
            font_size = fs
            break
    font = ImageFont.truetype(_MAAT_FONT, font_size)

    draw = ImageDraw.Draw(img)
    # Wis de oude maat (witte rechthoek met kleine marge)
    draw.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], fill='white')

    # Schrijf nieuwe maat gecentreerd op dezelfde positie
    bb_new = font.getbbox(new_str)
    nw = bb_new[2] - bb_new[0]
    tx = cx - nw // 2 - bb_new[0]
    ty = y0 - bb_new[1]
    draw.text((tx, ty), new_str, fill='black', font=font)

    # Vervang de XObject direct — behoudt positie en transform exact
    out = io.BytesIO()
    img.save(out, format='PNG')
    pix = fitz.Pixmap(out.getvalue())
    page.replace_image(xref, pixmap=pix)

    print(f'✅ Maat {old_str} → {new_str} aangepast (pagina {page.number + 1}, zone={found_zone})')
    return True


def verwerk(bestelfiche_pad: str, output_pad: str = None) -> str:
    """Hoofdfunctie: verwerkt één bestelfiche en geeft het outputpad terug."""
    if output_pad is None:
        p = Path(bestelfiche_pad)
        output_pad = str(p.parent / (p.stem + '_ingevuld.pdf'))

    vb_doc = fitz.open(bestelfiche_pad)

    # Stap 1: parseer header en alle volgbladen
    header = extraheer_header(vb_doc)
    specs  = [parse_volgblad(vb_doc[i]) for i in range(1, len(vb_doc))]
    spec   = specs[0] if specs else {}

    # Detecteer of document ramen/kozijnen en/of deuren bevat
    RAAM_KW = ['raam', 'kozijn', 'kiep', 'schuif', 'vast']
    spec['heeft_ramen']  = any(
        any(kw in s.get('element_type', '').lower() for kw in RAAM_KW)
        for s in specs
    )
    spec['heeft_deuren'] = any('deur' in s.get('element_type', '').lower() for s in specs)

    # Consistentiecheck raamgreep: gebruik meest voorkomende waarde
    raamgrepen = [s['raamgreep'] for s in specs if s.get('raamgreep')]
    if raamgrepen:
        spec['raamgreep'] = max(set(raamgrepen), key=raamgrepen.count)
        if len(set(raamgrepen)) > 1:
            print(f"⚠️  Verschillende raamgreep-kleuren gevonden: {raamgrepen} — '{spec['raamgreep']}' gebruikt")

    # Consistentiecheck raambeslag (standaard of SKG)
    beslag_waarden = [s['raambeslag'] for s in specs if s.get('raambeslag') is not None]
    if not beslag_waarden:
        spec['raambeslag'] = None  # niet gevonden op volgbladen — niets aanduiden
    elif len(set(beslag_waarden)) == 1:
        spec['raambeslag'] = beslag_waarden[0]  # allemaal consistent
    else:
        # Inconsistent: mix van 'standaard' en 'skg'
        print(f'\n⚠️  Verschillende raambeslag-types gevonden op de volgbladen:')
        for i, s in enumerate(specs):
            print(f'   Volgblad {i+1}: {s.get("raambeslag", "onbekend")}')
        print('   Opties:')
        print('   1. Fout op een of meerdere volgbladen → kies het correcte type voor het voorblad')
        print('   2. Afwijkende volgbladen krijgen een apart voorblad (niet automatisch)')
        keuze = input('   Welk raambeslag aanduiden op het voorblad? [standaard/skg]: ').strip().lower()
        spec['raambeslag'] = 'skg' if keuze in ('skg', 's') else 'standaard'

    # Consistentiecheck raamscharnieren (verdoken/zichtbaar + kleur)
    beslag_types  = [s['beslag_type']  for s in specs if s.get('beslag_type')]
    beslag_kleuren = [s['beslag_kleur'] for s in specs if s.get('beslag_kleur')]
    if not beslag_types:
        spec['beslag_type']  = None
        spec['beslag_kleur'] = None
    elif len(set(beslag_types)) == 1 and len(set(beslag_kleuren)) <= 1:
        spec['beslag_type']  = beslag_types[0]
        spec['beslag_kleur'] = beslag_kleuren[0] if beslag_kleuren else None
    else:
        print(f'\n⚠️  Inconsistent raamscharnieren-beslag op de volgbladen:')
        for i, s in enumerate(specs):
            print(f'   Volgblad {i+1}: {s.get("beslag_type", "niet gevonden")} - {s.get("beslag_kleur", "?")}')
        keuze_type  = input('   Beslag type [verdoken/zichtbaar]: ').strip().lower()
        keuze_kleur = input('   Beslag kleur [wit/zilver/antraciet/creme/zwart]: ').strip().lower()
        spec['beslag_type']  = keuze_type
        spec['beslag_kleur'] = keuze_kleur

    # Consistentiecheck deurgreep
    deurgrepen = [s['deurgreep'] for s in specs if s.get('deurgreep')]
    if not deurgrepen:
        spec['deurgreep'] = None
    elif len(set(deurgrepen)) == 1:
        spec['deurgreep'] = deurgrepen[0]
    else:
        print(f'\n⚠️  Verschillende deurgreep-kleuren: {deurgrepen}')
        keuze = input('   Welke kleur voor deurgreep? [wit/zilver]: ').strip().lower()
        spec['deurgreep'] = keuze

    # Consistentiecheck deurscharnieren
    deursch = [s['deurscharnieren'] for s in specs if s.get('deurscharnieren')]
    if not deursch:
        spec['deurscharnieren'] = None
    elif len(set(deursch)) == 1:
        spec['deurscharnieren'] = deursch[0]
    else:
        print(f'\n⚠️  Verschillende deurscharnieren-kleuren: {deursch}')
        keuze = input('   Welke kleur voor deurscharnieren? [wit/zilver/antraciet/creme/zwart]: ').strip().lower()
        spec['deurscharnieren'] = keuze

    # Logische kruischeck: raamkruk vs deurkruk
    rg = spec.get('raamgreep')
    dg = spec.get('deurgreep')
    if rg and dg and rg != dg:
        print(f'\n⚠️  Raamkruk ({rg}) heeft een andere kleur dan deurgreep ({dg}).')
        ant = input('   Is dit correct? [ja/nee]: ').strip().lower()
        if ant not in ('ja', 'j', 'yes', 'y'):
            keuze = input('   Gebruik welke kleur voor beide? [raamkruk/deurgreep]: ').strip().lower()
            if 'raam' in keuze:
                spec['deurgreep'] = rg
            else:
                spec['raamgreep'] = dg

    # Logische kruischeck: raamscharnieren vs deurscharnieren
    rs = spec.get('beslag_kleur')
    ds = spec.get('deurscharnieren')
    if rs and ds and rs != ds:
        print(f'\n⚠️  Raamscharnieren ({rs}) heeft een andere kleur dan deurscharnieren ({ds}).')
        ant = input('   Is dit correct? [ja/nee]: ').strip().lower()
        if ant not in ('ja', 'j', 'yes', 'y'):
            keuze = input('   Gebruik welke kleur voor beide? [raam/deur]: ').strip().lower()
            if 'raam' in keuze:
                spec['deurscharnieren'] = rs
            else:
                spec['beslag_kleur'] = ds

    # Afsluitbare raamkruk: alleen relevant bij opendraaiende elementen
    opendraaiend_specs = [s for s in specs if s.get('is_opendraaiend')]
    afsluitbaar_count = sum(1 for s in opendraaiend_specs if s.get('heeft_afsluitbare_kruk'))
    if afsluitbaar_count == 0:
        spec['met_sleutel'] = False  # niet aanwezig — niets doen
    elif afsluitbaar_count == len(opendraaiend_specs):
        spec['met_sleutel'] = True   # alle draaiende elementen: aanduiden
    else:
        print(f'\n⚠️  Afsluitbare raamkruk staat niet bij alle opendraaiende elementen:')
        for i, s in enumerate(opendraaiend_specs):
            status = '✓ afsluitbaar' if s.get('heeft_afsluitbare_kruk') else '✗ niet afsluitbaar'
            print(f'   Element {i+1} ({s.get("element_type", "?").rstrip(":")}): {status}')
        ant = input('   \'Met sleutel\' voor alle elementen aanduiden? [ja/nee]: ').strip().lower()
        spec['met_sleutel'] = ant in ('ja', 'j', 'yes', 'y')

    # Consistentiecheck beglazing
    glas_types     = [s['glas_type']           for s in specs if s.get('glas_type')]
    glas_lagen_all = [tuple(s['glas_lagen'])   for s in specs if s.get('glas_lagen')]
    if not glas_types:
        spec['glas_type']  = None
        spec['glas_lagen'] = None
    elif len(set(glas_types)) == 1 and len(set(glas_lagen_all)) == 1:
        spec['glas_type']  = glas_types[0]
        spec['glas_lagen'] = list(glas_lagen_all[0])
    else:
        print(f'\n⚠️  Verschillende beglazingsopties gevonden op de volgbladen:')
        for i, s in enumerate(specs):
            print(f'   Volgblad {i+1}: {s.get("glas_str") or "niet gevonden"} ({s.get("glas_type","?")})')
        print('   Opties:')
        print('   1. Fout → geef de correcte glascode in (bv. 4/16/4 of 33.2/16/4/16/33.2)')
        print('   2. Elementen hebben écht ander glas → maak aparte voorbladen (niet automatisch)')
        keuze = input('   Welke beglazing aanduiden op het voorblad? : ').strip()
        spec['glas_type'], spec['glas_lagen'] = parse_glas(keuze)

    # NL-regel: bij ontbrekend profieltype vragen of het T-kaderprofiel (aanslag) is
    if spec.get('profiel_type') != 'aanslag':
        gevonden = spec.get('profiel_type') or 'niet gevonden'
        print(f"\n⚠️  Profieltype op de volgbladen: '{gevonden}'")
        print("   In Nederland is aanslag (T-kaderprofiel) de gebruikelijke keuze voor Certix.")
        antwoord = input("   Aanslag (T-kader) of stomp? [aanslag/stomp]: ").strip().lower()
        if antwoord in ('aanslag', 'a', ''):
            spec['profiel_type'] = 'aanslag'
        else:
            spec['profiel_type'] = 'stomp'

    # Stap 2: vul het voorblad in
    result_doc = vul_voorblad(header, spec)

    # Stap 3a: maataanpassingen in tekeningen (optioneel)
    if _PIL_BESCHIKBAAR:
        print('\n📐 Maataanpassingen in tekeningen (Enter = geen wijziging, formaat: oud=nieuw):')
        for i in range(1, len(vb_doc)):
            # Toon positienummer uit kopregels
            pos_regels = [r.strip() for r in vb_doc[i].get_text('text').split('\n') if r.strip()]
            pos_label = next((r for r in pos_regels if r.startswith('POS.')), f'Volgblad {i}')
            print(f'\n  {pos_label}')

            def _vraag_maat(label, zone):
                while True:
                    invoer = input(f'    {label}: ').strip()
                    if not invoer:
                        return
                    if '=' in invoer:
                        delen = invoer.split('=', 1)
                        try:
                            oud = int(delen[0].strip())
                            nieuw = int(delen[1].strip())
                            wijzig_maat_in_tekening(vb_doc[i], oud, nieuw, zone=zone)
                            return
                        except ValueError:
                            pass
                    print('      Gebruik formaat: 980=1080')

            _vraag_maat('Breedte (bijv. 980=1080)', zone='bottom')
            _vraag_maat('Hoogte  (bijv. 2290=2390)', zone='right')

    # Stap 3b: verwerk alle volgbladen (Vak B opschonen)
    for i in range(1, len(vb_doc)):
        process_volgblad(vb_doc[i])

    # Stap 4: voeg volgbladen toe aan het ingevulde voorblad
    result_doc.insert_pdf(vb_doc, from_page=1, to_page=len(vb_doc) - 1)

    # Stap 5: opslaan
    tmp = '/tmp/_voorblad_output.pdf'
    result_doc.save(tmp)
    shutil.copy(tmp, output_pad)

    print(f"✅ Opgeslagen: {output_pad}")
    return output_pad


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    invoer  = sys.argv[1]
    uitvoer = sys.argv[2] if len(sys.argv) > 2 else None
    verwerk(invoer, uitvoer)
