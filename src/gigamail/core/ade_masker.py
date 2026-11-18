"""
ade_masker.py — Masking deterministico di dati sensibili italiani per ADE Mail.

Principi:
- Deterministico: solo regex + validatori con checksum normati. Nessuna AI.
- Stateless: la mappa di mascheramento NON è persistita lato server; viene
  restituita al client che la rimanda per /unmask.
- Reversibile: mask(text) -> (masked, mapping); unmask(masked, mapping) -> text.
- User-in-control: detect() suggerisce, il client decide cosa mascherare.

Due livelli:
  L1 validator deterministici (5 killer): CF, P.IVA, IBAN, email, telefono.
  L2 maschere utente per-account: l'utente seleziona testo e salva una maschera
     (valore -> tipo), applicata automaticamente ai testi futuri di quell'account.

Validator v1 (5 killer):
  Codice Fiscale  — DPR 605/1973, D.M. 12 marzo 1974 (carattere di controllo)
  Partita IVA     — DPR 633/1972, Decreto 13813/1976 art.9 (Luhn mod 10)
  IBAN            — ISO 13616 (checksum mod-97)
  Email           — RFC 5322 (formato)
  Telefono IT     — ITU-T E.164 / numerazione nazionale
"""
import os
import re
import sqlite3
from typing import Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# CODICE FISCALE — DPR 605/1973, D.M. 12 marzo 1974
# ─────────────────────────────────────────────────────────────────────────────
_CF_RE = re.compile(r'\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b', re.IGNORECASE)

_CF_ODD = {
    '0': 1, '1': 0, '2': 5, '3': 7, '4': 9, '5': 13, '6': 15, '7': 17, '8': 19, '9': 21,
    'A': 1, 'B': 0, 'C': 5, 'D': 7, 'E': 9, 'F': 13, 'G': 15, 'H': 17, 'I': 19, 'J': 21,
    'K': 2, 'L': 4, 'M': 18, 'N': 20, 'O': 11, 'P': 3, 'Q': 6, 'R': 8, 'S': 12, 'T': 14,
    'U': 16, 'V': 10, 'W': 22, 'X': 25, 'Y': 24, 'Z': 23,
}
_CF_EVEN = {
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
    'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4, 'F': 5, 'G': 6, 'H': 7, 'I': 8, 'J': 9,
    'K': 10, 'L': 11, 'M': 12, 'N': 13, 'O': 14, 'P': 15, 'Q': 16, 'R': 17, 'S': 18,
    'T': 19, 'U': 20, 'V': 21, 'W': 22, 'X': 23, 'Y': 24, 'Z': 25,
}
_CF_REMAINDER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def _cf_valid(cf: str) -> bool:
    cf = cf.upper()
    if len(cf) != 16:
        return False
    total = 0
    for i, ch in enumerate(cf[:15]):
        # posizione 1-based: dispari usa tabella ODD, pari usa EVEN
        if (i + 1) % 2 == 1:
            if ch not in _CF_ODD:
                return False
            total += _CF_ODD[ch]
        else:
            if ch not in _CF_EVEN:
                return False
            total += _CF_EVEN[ch]
    return _CF_REMAINDER[total % 26] == cf[15]


# ─────────────────────────────────────────────────────────────────────────────
# PARTITA IVA — DPR 633/1972, Decreto 13813/1976 art.9 (Luhn mod 10)
# ─────────────────────────────────────────────────────────────────────────────
_PIVA_RE = re.compile(r'(?<!\d)(?:IT\s?)?(\d{11})(?!\d)', re.IGNORECASE)


def _piva_valid(piva: str) -> bool:
    piva = re.sub(r'\D', '', piva)
    if len(piva) != 11:
        return False
    total = 0
    for i, ch in enumerate(piva):
        d = int(ch)
        if i % 2 == 1:  # posizioni pari (0-based dispari) raddoppiate
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ─────────────────────────────────────────────────────────────────────────────
# IBAN — ISO 13616 (checksum mod-97)
# ─────────────────────────────────────────────────────────────────────────────
# IBAN — forma contigua o a gruppi di 4. Validato poi col checksum mod-97.
_IBAN_RE = re.compile(
    r'\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b',
    re.IGNORECASE
)

# IBAN length per country (ISO 13616 registry). A country missing here
# is still checked with mod-97.
_IBAN_LEN = {
    'AD': 24, 'AE': 23, 'AL': 28, 'AT': 20, 'AZ': 28, 'BA': 20, 'BE': 16,
    'BG': 22, 'BH': 22, 'BR': 29, 'BY': 28, 'CH': 21, 'CR': 22, 'CY': 28,
    'CZ': 24, 'DE': 22, 'DK': 18, 'DO': 28, 'EE': 20, 'EG': 29, 'ES': 24,
    'FI': 18, 'FO': 18, 'FR': 27, 'GB': 22, 'GE': 22, 'GI': 23, 'GL': 18,
    'GR': 27, 'GT': 28, 'HR': 21, 'HU': 28, 'IE': 22, 'IL': 23, 'IQ': 23,
    'IS': 26, 'IT': 27, 'JO': 30, 'KW': 30, 'KZ': 20, 'LB': 28, 'LC': 32,
    'LI': 21, 'LT': 20, 'LU': 20, 'LV': 21, 'LY': 25, 'MC': 27, 'MD': 24,
    'ME': 22, 'MK': 19, 'MR': 27, 'MT': 31, 'MU': 30, 'NL': 18, 'NO': 15,
    'PK': 24, 'PL': 28, 'PS': 29, 'PT': 25, 'QA': 29, 'RO': 24, 'RS': 22,
    'SA': 24, 'SC': 31, 'SD': 18, 'SE': 24, 'SI': 19, 'SK': 24, 'SM': 27,
    'ST': 25, 'SV': 28, 'TL': 23, 'TN': 24, 'TR': 26, 'UA': 29, 'VA': 22,
    'VG': 24, 'XK': 20,
}


def _iban_valid(iban: str) -> bool:
    iban = re.sub(r'\s', '', iban).upper()
    cc = iban[:2]
    if cc in _IBAN_LEN and len(iban) != _IBAN_LEN[cc]:
        return False
    if len(iban) < 15:
        return False
    # Sposta i primi 4 caratteri in fondo, converte lettere in numeri (A=10..Z=35)
    rearranged = iban[4:] + iban[:4]
    digits = ''
    for ch in rearranged:
        if ch.isdigit():
            digits += ch
        elif ch.isalpha():
            digits += str(ord(ch) - 55)
        else:
            return False
    try:
        return int(digits) % 97 == 1
    except ValueError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL — RFC 5322 (formato pratico)
# ─────────────────────────────────────────────────────────────────────────────
_EMAIL_RE = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
)


# ─────────────────────────────────────────────────────────────────────────────
# TELEFONO IT — numerazione nazionale / E.164
# ─────────────────────────────────────────────────────────────────────────────
# Cellulari (3xx) e fissi italiani, con o senza prefisso +39 / 0039
# Cellulari (3xx) e fissi italiani. Separatori: spazio . - / e prefisso +39/0039/(+39)
_TEL_RE = re.compile(
    r'(?<![\w.])'
    r'(?:\(?(?:\+39|0039)\)?[\s./-]?)?'
    r'(?:3\d{2}[\s./-]?\d{3}[\s./-]?\d{3,4}'      # cellulare: 3xx xxx xxxx
    r'|0\d{1,3}[\s./-]?\d{3,4}[\s./-]?\d{3,5}'    # fisso: 0xx xxx xxxx
    r'|0\d{1,3}[\s./-]?\d{5,8})'                  # fisso compatto: 02.123456
    r'(?![\w])'
)


def _tel_valid(tel: str) -> bool:
    digits = re.sub(r'\D', '', tel)
    digits = digits.lstrip('0') if digits.startswith('0039') else digits
    if digits.startswith('39') and len(digits) > 10:
        digits = digits[2:]
    # cellulare 10 cifre (3xx) o fisso 6-11 cifre
    if len(digits) < 6 or len(digits) > 11:
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# UNITED STATES AND INTERNATIONAL
# Shapes that are ordinary numbers too (a 9-digit routing number, an
# account number) are taken only after the word that names them.
# ─────────────────────────────────────────────────────────────────────────────
# Social Security Number, written with separators: 123-45-6789. Never
# 000, 666 or 9xx in the area, 00 in the group, 0000 in the serial.
_SSN_RE = re.compile(r'(?<![\w-])\d{3}[- ]\d{2}[- ]\d{4}(?![\w-])')


def _ssn_parts(raw: str):
    return re.split(r'[- ]', raw.strip())


def _ssn_valid(raw: str) -> bool:
    area, group, serial = _ssn_parts(raw)
    return (area not in ('000', '666') and not area.startswith('9')
            and group != '00' and serial != '0000')


# ITIN: written like an SSN, area 9xx, group 50-65, 70-88, 90-92, 94-99.
def _itin_valid(raw: str) -> bool:
    area, group, _serial = _ssn_parts(raw)
    g = int(group)
    return area.startswith('9') and (50 <= g <= 65 or 70 <= g <= 88
                                     or 90 <= g <= 92 or 94 <= g <= 99)


# Employer Identification Number: 12-3456789, with a prefix the IRS assigns.
_EIN_RE = re.compile(r'(?<![\w-])\d{2}-\d{7}(?![\w-])')
_EIN_BAD_PREFIX = {'00', '07', '08', '09', '17', '18', '19', '28', '29', '49',
                   '69', '70', '78', '79', '89', '96', '97'}


def _ein_valid(raw: str) -> bool:
    return raw.strip()[:2] not in _EIN_BAD_PREFIX


# ABA routing number, after "routing", "ABA" or "RTN": 9 digits, a valid
# Federal Reserve prefix and the 3-7-1 checksum.
_ABA_RE = re.compile(
    r'\b(?:routing|aba|rtn)\b(?:[\s#:.]|number|no\b|num\b|transit)*?(?P<v>\d{9})(?!\d)',
    re.IGNORECASE)


def _aba_valid(raw: str) -> bool:
    d = [int(c) for c in re.sub(r'\D', '', raw)]
    if len(d) != 9:
        return False
    prefix = d[0] * 10 + d[1]
    if not (prefix <= 12 or 21 <= prefix <= 32 or 61 <= prefix <= 72 or prefix == 80):
        return False
    total = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    return total % 10 == 0


# A US bank account number, only after "account number", "acct", ...:
# 6 to 17 digits.
_US_ACCOUNT_RE = re.compile(
    r'\b(?:account|acct)\b\.?(?:[\s#:.]|number|no\b|num\b)*?(?P<v>\d{6,17})(?!\d)',
    re.IGNORECASE)


# Payment card: 13-19 digits, in groups or not, a known issuer prefix and
# the Luhn check.
_CARD_RE = re.compile(r'(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])')


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _card_valid(raw: str) -> bool:
    digits = re.sub(r'\D', '', raw)
    if not 13 <= len(digits) <= 19 or not _luhn(digits):
        return False
    two, three, four = int(digits[:2]), int(digits[:3]), int(digits[:4])
    return (digits[0] == '4'                                  # Visa
            or 51 <= two <= 55 or 2221 <= four <= 2720        # Mastercard
            or two in (34, 37)                                # American Express
            or four == 6011 or two == 65 or 644 <= three <= 649  # Discover
            or two == 35                                      # JCB
            or two in (36, 38, 39) or 300 <= three <= 305     # Diners
            or two == 62)                                     # UnionPay


# EU VAT number with its country prefix (the Italian one is PARTITA_IVA).
_EU_VAT_RE = re.compile(
    r'\b(?:ATU\d{8}|BE[01]\d{9}|BG\d{9,10}|CY\d{8}[A-Z]|CZ\d{8,10}|DE\d{9}'
    r'|DK\d{8}|EE\d{9}|EL\d{9}|ES[A-Z0-9]\d{7}[A-Z0-9]|FI\d{8}'
    r'|FR[A-HJ-NP-Z0-9]{2}\d{9}|HR\d{11}|HU\d{8}|IE\d[A-Z0-9+*]\d{5}[A-Z]{1,2}'
    r'|LT(?:\d{12}|\d{9})|LU\d{8}|LV\d{11}|MT\d{8}|NL\d{9}B\d{2}|PL\d{10}'
    r'|PT\d{9}|RO\d{2,10}|SE\d{12}|SI\d{8}|SK\d{10})\b')


# US / NANP phone, with separators: (415) 555-0132, +1 415 555 0132.
_US_PHONE_RE = re.compile(
    r'(?<![\w+])(?:\+?1[\s.-]?)?(?:\([2-9]\d{2}\)\s?|[2-9]\d{2}[\s.-])'
    r'[2-9]\d{2}[\s.-]\d{4}(?![\w-])')


# Any other number with an international prefix (E.164: 8-15 digits).
# Every group after the first starts with a separator or a bracket, so a
# long run of digits has one way to match (no backtracking blow-up).
_INTL_PHONE_RE = re.compile(
    r'(?<![\w+])\+[1-9]\d{0,14}(?:[\s.-]?\(\d{1,5}\)|[\s.-]\d{1,10}){0,6}(?![\w(])')


def _intl_phone_valid(raw: str) -> bool:
    return 8 <= len(re.sub(r'\D', '', raw)) <= 15


# Street address, heuristic. Italian: "Via Roma 10", "Piazza Duomo, 3",
# with the postcode and the town when they follow. US: "1600 Main Street",
# "42 Oak Ave, Apt 5", with "Springfield, IL 62701" when it follows.
# A word of a street name: capitalised ("Roma", "XX", "4"), a linking
# word ("della"), or "dell'Orso". Words are split by blanks only, so a
# name has one way to match.
_IT_STREET_WORD = (r"(?:[A-ZÀ-Ý0-9][\wà-ÿ'.]*|d[aei]|del|dei|degli|della|delle|dello"
                   r"|dell'[A-ZÀ-Ý][\wà-ÿ]*)")
_IT_ADDRESS_RE = re.compile(
    r'\b(?i:via|viale|piazza|piazzale|p\.zza|corso|c\.so|largo|vicolo|strada|'
    r'lungomare|contrada|borgo)\s+'
    + _IT_STREET_WORD.join([r"(?:", r"\s+){0,4}", r""]) +
    r',?\s*\d{1,4}(?:\s?[A-Za-z]\b)?(?:/[A-Za-z0-9]{1,4})?\b'
    r"(?:,?\s+\d{5}\s+[A-ZÀ-Ý][\wà-ÿ']+(?:\s+[A-ZÀ-Ý][\wà-ÿ']+)?(?:\s+\(?[A-Z]{2}\)?)?)?")
_US_ADDRESS_RE = re.compile(
    r'(?<![\w-])\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][a-z]+\s+){1,4}'
    r'(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|'
    r'Way|Place|Pl|Terrace|Ter|Parkway|Pkwy|Highway|Hwy|Circle|Cir)\b\.?'
    r'(?:,?\s+(?:Apt|Suite|Ste|Unit|#)\.?\s*[\w-]+)?'
    r'(?:,\s*(?:[A-Z][a-z]+\s?){1,3},\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?')


# ─────────────────────────────────────────────────────────────────────────────
# RAGIONE SOCIALE — nome azienda + forma giuridica (euristico)
# Cattura le parole maiuscole immediatamente prima della sigla societaria.
# Es: "Immobiliare Verdi Srl" -> match; "ho una Srl" -> no (una è minuscola/stopword)
# ─────────────────────────────────────────────────────────────────────────────
# sigle: srl, s.r.l., spa, s.p.a., snc, s.n.c., sas, s.a.s., ss, scarl, coop
_SOC_SUFFIX = r'(?:s\.?r\.?l\.?(?:s\.?)?|s\.?p\.?a\.?|s\.?n\.?c\.?|s\.?a\.?s\.?|s\.?s\.?|s\.?c\.?a\.?r\.?l\.?|soc\.?\s*coop\.?)'
# 1-3 parole che iniziano con maiuscola subito prima della sigla
_SOC_RE = re.compile(
    r'\b((?:[A-ZÀ-Þ][\wà-ÿ&\'.]*\s+){1,3})(' + _SOC_SUFFIX + r')\b',
    re.IGNORECASE
)
# parole che NON sono nomi azienda anche se a inizio frase
_SOC_STOP = {
    'la', 'le', 'lo', 'il', 'una', 'uno', 'un', 'mia', 'mio', 'sua', 'suo',
    'nostra', 'nostro', 'vostra', 'questa', 'questo', 'ho', 'in', 'di', 'da',
    'per', 'con', 'alla', 'alle', 'allo', 'della', 'delle', 'dello', 'come',
    'tipo', 'tua', 'tuo', 'sono', 'era', 'fondato', 'aperto',
    'anche', 'e', 'ed', 'ma', 'poi', 'quindi', 'inoltre', 'presso', 'oggi',
    'ieri', 'cioe', 'cioè', 'ossia', 'nonche', 'nonché', 'che', 'chi',
    'spettabile', 'spett', 'spettle', 'egregia', 'egregio', 'gentile',
    'gentfilissima', 'gentilissimo', 'chiarissimo', 'preg', 'pregma',
}


def _soc_norm(w: str) -> str:
    """Normalizza una parola per il confronto stopword: minuscolo, no punti."""
    return w.lower().replace('.', '').strip()


def _soc_valid(match_text: str) -> bool:
    """Valida: deve restare almeno una parola-nome con iniziale maiuscola."""
    words = match_text.strip().split()
    if len(words) < 2:
        return False
    name_words = words[:-1]  # togli la sigla
    real = [w for w in name_words
            if _soc_norm(w) not in _SOC_STOP and w[:1].isupper()]
    return len(real) >= 1


def _soc_finditer(text: str):
    """Genera match di ragione sociale, restringendo alle sole parole-nome maiuscole."""
    for m in _SOC_RE.finditer(text):
        pre = m.group(1)
        suffix = m.group(2)
        words = pre.split()
        while words and (_soc_norm(words[0]) in _SOC_STOP or not words[0][:1].isupper()):
            words.pop(0)
        if not words:
            continue
        name = ' '.join(words) + ' ' + suffix
        start = m.start() + m.group(0).find(words[0])
        yield (name.strip(), start, m.end())


# ─────────────────────────────────────────────────────────────────────────────
# DETECTOR
# ─────────────────────────────────────────────────────────────────────────────
# Ordine importante: i più specifici/lunghi prima, per evitare che IBAN/CF
# vengano spezzati da match di telefono o piva.
_DETECTORS = [
    # (type, placeholder prefix, regex, optional validator). A regex with a
    # group named "v" masks that group only (the keyword before it stays).
    ('CODICE_FISCALE', 'CF',    _CF_RE,    _cf_valid),
    ('IBAN',           'IBAN',  _IBAN_RE,  _iban_valid),
    ('CREDIT_CARD',    'CARD',  _CARD_RE,  _card_valid),
    ('EMAIL',          'EMAIL', _EMAIL_RE, None),
    ('US_ROUTING',     'ROUTING', _ABA_RE, _aba_valid),
    ('US_BANK_ACCOUNT', 'ACCOUNT', _US_ACCOUNT_RE, None),
    ('SSN',            'SSN',   _SSN_RE,   _ssn_valid),
    ('ITIN',           'ITIN',  _SSN_RE,   _itin_valid),
    ('EIN',            'EIN',   _EIN_RE,   _ein_valid),
    ('PARTITA_IVA',    'PIVA',  _PIVA_RE,  _piva_valid),
    ('EU_VAT',         'VAT',   _EU_VAT_RE, None),
    ('TELEFONO',       'TEL',   _TEL_RE,   _tel_valid),
    ('US_PHONE',       'PHONE', _US_PHONE_RE, None),
    ('INTL_PHONE',     'PHONE', _INTL_PHONE_RE, _intl_phone_valid),
    ('INDIRIZZO',      'ADDRESS', _IT_ADDRESS_RE, None),
    ('US_ADDRESS',     'ADDRESS', _US_ADDRESS_RE, None),
]


def detect(text: str, user_masks: Optional[List[Dict]] = None) -> List[Dict]:
    """
    Trova tutti i candidati sensibili nel testo.
    Ritorna lista di {type, label_prefix, value, start, end} senza sovrapposizioni.
    user_masks: lista di {value, label_type} salvate dall'utente (L2), applicate
    in aggiunta ai validator deterministici (L1). Hanno priorità (matchate prima).
    """
    if not text:
        return []
    occupied = []  # intervalli (start, end) già presi
    found = []

    def _overlaps(s, e):
        for (os_, oe_) in occupied:
            if s < oe_ and e > os_:
                return True
        return False

    # L2 PRIMA: maschere utente (match esatto del valore salvato), priorità alta.
    for um in (user_masks or []):
        val = (um.get('value') or '').strip()
        if not val:
            continue
        label = um.get('label_type') or 'MASK'
        mask_id = um.get('id')  # id regola nel DB, per eliminazione
        # match di tutte le occorrenze del valore esatto
        start = 0
        while True:
            idx = text.find(val, start)
            if idx == -1:
                break
            s, e = idx, idx + len(val)
            if not _overlaps(s, e):
                occupied.append((s, e))
                found.append({
                    'type': label,
                    'label_prefix': label,
                    'value': val,
                    'start': s,
                    'end': e,
                    'source': 'user',
                    'mask_id': mask_id,
                })
            start = e

    # L1: validator deterministici
    for typ, prefix, rx, validator in _DETECTORS:
        group = 'v' if 'v' in rx.groupindex else 0
        for m in rx.finditer(text):
            s, e = m.start(group), m.end(group)
            raw = m.group(group)
            if _overlaps(s, e):
                continue
            if validator and not validator(raw):
                continue
            occupied.append((s, e))
            found.append({
                'type': typ,
                'label_prefix': prefix,
                'value': raw.strip(),
                'start': s,
                'end': e,
                'source': 'validator',
            })

    # L1b: ragione sociale (euristico, finditer custom)
    for name, s, e in _soc_finditer(text):
        if _overlaps(s, e):
            continue
        if not _soc_valid(name):
            continue
        occupied.append((s, e))
        found.append({
            'type': 'AZIENDA',
            'label_prefix': 'AZIENDA',
            'value': name,
            'start': s,
            'end': e,
            'source': 'validator',
        })

    found.sort(key=lambda c: c['start'])
    return found


def mask(text: str, selected_values: List[str] = None,
         user_masks: Optional[List[Dict]] = None) -> Tuple[str, Dict[str, str]]:
    """
    Maschera il testo. Ritorna (testo_mascherato, mapping placeholder->valore).
    Se selected_values è fornito, maschera SOLO quei valori (user-in-control);
    altrimenti maschera tutti i candidati rilevati (L1 validator + L2 maschere utente).
    Stateless: il mapping è restituito, non salvato.
    """
    candidates = detect(text, user_masks=user_masks)
    if selected_values is not None:
        sel = set(selected_values)
        candidates = [c for c in candidates if c['value'] in sel]

    # Assegna placeholder con indice per tipo. Stesso valore -> stesso placeholder.
    mapping: Dict[str, str] = {}        # placeholder -> valore
    value_to_ph: Dict[str, str] = {}    # valore -> placeholder (dedup)
    counters: Dict[str, int] = {}

    for c in candidates:
        val = c['value']
        if val in value_to_ph:
            continue
        prefix = c['label_prefix']
        counters[prefix] = counters.get(prefix, 0) + 1
        ph = f'[{prefix}_{counters[prefix]}]'
        value_to_ph[val] = ph
        mapping[ph] = val

    # Sostituzione: dal valore più lungo al più corto, per evitare match parziali
    masked = text
    for val in sorted(value_to_ph.keys(), key=len, reverse=True):
        masked = masked.replace(val, value_to_ph[val])

    return masked, mapping


def unmask(masked_text: str, mapping: Dict[str, str]) -> str:
    """Ripristina i valori originali dato il mapping placeholder->valore."""
    if not mapping:
        return masked_text
    text = masked_text
    # Placeholder più lunghi prima (es. [CF_10] prima di [CF_1])
    for ph in sorted(mapping.keys(), key=len, reverse=True):
        text = text.replace(ph, mapping[ph])
    return text


# ─────────────────────────────────────────────────────────────────────────────
# SUGGERIMENTO TIPO (euristico, deterministico)
# ─────────────────────────────────────────────────────────────────────────────
_COMPANY_MARKERS = re.compile(
    r'\b(s\.?r\.?l\.?|s\.?p\.?a\.?|s\.?n\.?c\.?|s\.?a\.?s\.?|s\.?s\.?|'
    r'societa|società|associazione|studio|impresa|ditta|coop|cooperativa|spa|srl|snc|sas)\b',
    re.IGNORECASE
)
_ADDRESS_MARKERS = re.compile(
    r'\b(via|viale|piazza|p\.zza|corso|c\.so|largo|vicolo|strada|località|localita|'
    r'fraz\.?|frazione)\b',
    re.IGNORECASE
)


def suggest_type(selection: str) -> str:
    """
    Suggerisce un'etichetta per il testo selezionato dall'utente (NOME/AZIENDA/
    INDIRIZZO/MASK). Euristica deterministica, l'utente può sempre modificarla.
    """
    s = (selection or '').strip()
    if not s:
        return 'MASK'
    if _COMPANY_MARKERS.search(s):
        return 'AZIENDA'
    if _ADDRESS_MARKERS.search(s) or re.search(r'\b\d{5}\b', s):  # CAP o marker via
        return 'INDIRIZZO'
    # Due+ parole capitalizzate consecutive → probabile nome persona
    words = s.split()
    cap = [w for w in words if w[:1].isupper() and w[1:].islower()]
    if len(words) <= 4 and len(cap) >= 2:
        return 'NOME'
    if len(words) == 1 and s[:1].isupper():
        return 'NOME'
    return 'MASK'


# ─────────────────────────────────────────────────────────────────────────────
# MASCHERE UTENTE PER-ACCOUNT (persistenza SQLite)
# ─────────────────────────────────────────────────────────────────────────────
def _db_path() -> str:
    """DB nella cartella dati ADE Mail (coerente con gli altri DB)."""
    from .data_paths import data_root
    return os.path.join(str(data_root()), '.user_masks.db')


def _conn():
    c = sqlite3.connect(_db_path())
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_masks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            value TEXT NOT NULL,
            label_type TEXT NOT NULL DEFAULT 'MASK',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(account_id, value)
        )
    """)
    return c


def get_user_masks(account_id: int) -> List[Dict]:
    """Ritorna le maschere salvate per un account."""
    if not account_id:
        return []
    try:
        with _conn() as c:
            rows = c.execute(
                "SELECT id, value, label_type FROM user_masks WHERE account_id=? ORDER BY length(value) DESC",
                (account_id,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[MASKER] get_user_masks error: {e}")
        return []


def add_user_mask(account_id: int, value: str, label_type: str = 'MASK') -> Dict:
    """Salva (o aggiorna) una maschera per l'account."""
    value = (value or '').strip()
    if not account_id or not value:
        return {}
    label_type = (label_type or 'MASK').strip().upper() or 'MASK'
    try:
        with _conn() as c:
            c.execute(
                """INSERT INTO user_masks (account_id, value, label_type) VALUES (?,?,?)
                   ON CONFLICT(account_id, value) DO UPDATE SET label_type=excluded.label_type""",
                (account_id, value, label_type)
            )
            c.commit()
            row = c.execute(
                "SELECT id, value, label_type FROM user_masks WHERE account_id=? AND value=?",
                (account_id, value)
            ).fetchone()
            return dict(row) if row else {}
    except Exception as e:
        print(f"[MASKER] add_user_mask error: {e}")
        return {}


def delete_user_mask(account_id: int, mask_id: int) -> bool:
    try:
        with _conn() as c:
            c.execute("DELETE FROM user_masks WHERE account_id=? AND id=?", (account_id, mask_id))
            c.commit()
            return True
    except Exception as e:
        print(f"[MASKER] delete_user_mask error: {e}")
        return False
