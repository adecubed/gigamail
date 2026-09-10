"""
google_drive.py — File su Google Drive, scope drive.file.

LIMITE DA CONOSCERE PRIMA DI USARLO: con lo scope drive.file GigaMail vede
solo i file che ha creato lui, non l'intero Drive dell'utente. Non e' un
bug ed e' una scelta: lo scope 'drive' completo e' classificato "restricted"
da Google e fa scattare una valutazione di sicurezza esterna, a pagamento e
lunga, su ogni versione dell'app. Per allegare, archiviare e condividere
documenti generati dalla posta drive.file basta.

Chi si aspetta di cercare dentro i propri file esistenti va avvisato in
chiaro, non lasciato davanti a una lista vuota: e' quello che fa il campo
`nota` nelle risposte dei tool.

Come ms_calendar e google_calendar: HTTP puro con requests, nessuna
libreria Google.
"""

import mimetypes
import os
from typing import Dict, List

import requests

from .google_auth import auth_headers, check, get_token

API = 'https://www.googleapis.com/drive/v3'
UPLOAD_API = 'https://www.googleapis.com/upload/drive/v3'

_FIELDS = 'id,name,mimeType,size,modifiedTime,webViewLink,parents,iconLink'

# Documenti nativi Google: non hanno byte da scaricare, vanno esportati.
_EXPORT = {
    'application/vnd.google-apps.document':
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.google-apps.spreadsheet':
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.google-apps.presentation':
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.google-apps.drawing': 'application/pdf',
}

_EXPORT_EXT = {
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
    'application/pdf': '.pdf',
}


def _bearer(email: str = None) -> dict:
    """Solo Authorization: per upload e download il Content-Type lo decide
    la richiesta, non l'helper."""
    return {'Authorization': f'Bearer {get_token(email)}'}


def _clean(f: Dict) -> Dict:
    size = f.get('size')
    return {
        'id': f.get('id'),
        'name': f.get('name'),
        'mime_type': f.get('mimeType'),
        'size': int(size) if size is not None and str(size).isdigit() else None,
        'modified': f.get('modifiedTime'),
        'link': f.get('webViewLink', ''),
        'is_folder': f.get('mimeType') == 'application/vnd.google-apps.folder',
    }


def list_files(query: str = '', limit: int = 50, folder_id: str = '',
               email: str = None) -> List[Dict]:
    """File visibili a GigaMail, i piu' recenti per primi.

    `query` e' testo libero: viene tradotto in un contains sul nome. Chi
    vuole la sintassi di ricerca di Drive puo' passarla direttamente, e
    viene riconosciuta dalla presenza di un operatore.
    """
    clausole = ['trashed = false']
    if query:
        pare_sintassi_drive = any(op in query for op in (' contains ', ' = ', ' in '))
        if pare_sintassi_drive:
            clausole.append(f'({query})')
        else:
            sicuro = query.replace("\\", "\\\\").replace("'", "\\'")
            clausole.append(f"name contains '{sicuro}'")
    if folder_id:
        clausole.append(f"'{folder_id}' in parents")

    params = {
        'q': ' and '.join(clausole),
        'fields': f'files({_FIELDS}),nextPageToken',
        'orderBy': 'modifiedTime desc',
        'pageSize': max(1, min(int(limit), 100)),
        'spaces': 'drive',
    }
    res = requests.get(f'{API}/files', headers=auth_headers(email),
                       params=params, timeout=30)
    check(res)
    return [_clean(f) for f in res.json().get('files', [])]


def get_file(file_id: str, email: str = None) -> Dict:
    res = requests.get(f'{API}/files/{file_id}', headers=auth_headers(email),
                       params={'fields': _FIELDS}, timeout=30)
    check(res)
    return _clean(res.json())


def download_file(file_id: str, dest_dir: str, email: str = None) -> Dict:
    """Scarica un file in dest_dir. I documenti nativi Google vengono
    esportati nel corrispondente formato Office, perche' non hanno byte
    propri da scaricare. Ritorna {path, name, mime_type, size}."""
    meta_res = requests.get(f'{API}/files/{file_id}', headers=auth_headers(email),
                            params={'fields': 'id,name,mimeType'}, timeout=30)
    check(meta_res)
    meta = meta_res.json()
    nome = meta.get('name') or file_id
    mime = meta.get('mimeType') or ''

    if mime == 'application/vnd.google-apps.folder':
        raise ValueError(f"'{nome}' e' una cartella, non un file.")

    if mime in _EXPORT:
        target_mime = _EXPORT[mime]
        url = f'{API}/files/{file_id}/export'
        params = {'mimeType': target_mime}
        ext = _EXPORT_EXT.get(target_mime, '')
        if ext and not nome.lower().endswith(ext):
            nome += ext
    else:
        target_mime = mime
        url = f'{API}/files/{file_id}'
        params = {'alt': 'media'}

    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, _nome_sicuro(nome))

    with requests.get(url, headers=_bearer(email), params=params,
                      stream=True, timeout=120) as r:
        check(r)
        with open(path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)

    return {'path': path, 'name': nome, 'mime_type': target_mime,
            'size': os.path.getsize(path)}


def _nome_sicuro(nome: str) -> str:
    """Un nome che arriva da Drive non e' fidato: puo' contenere separatori
    di percorso e scrivere fuori dalla cartella di destinazione."""
    nome = os.path.basename(str(nome).replace('\\', '/'))
    for ch in '<>:"|?*':
        nome = nome.replace(ch, '_')
    return nome.strip() or 'file'


def upload_file(local_path: str, name: str = '', folder_id: str = '',
                email: str = None) -> Dict:
    """Carica un file locale. Ritorna i metadati del file creato."""
    if not os.path.isfile(local_path):
        raise ValueError(f'File inesistente: {local_path}')

    nome = name or os.path.basename(local_path)
    mime = mimetypes.guess_type(nome)[0] or 'application/octet-stream'
    metadata: Dict = {'name': nome}
    if folder_id:
        metadata['parents'] = [folder_id]

    with open(local_path, 'rb') as f:
        contenuto = f.read()

    # multipart/related: metadati JSON + byte in una sola richiesta.
    files = {
        'metadata': (None, _json_dumps(metadata), 'application/json; charset=UTF-8'),
        'file': (nome, contenuto, mime),
    }
    res = requests.post(
        f'{UPLOAD_API}/files',
        headers=_bearer(email),
        params={'uploadType': 'multipart', 'fields': _FIELDS},
        files=files,
        timeout=300,
    )
    check(res)
    return _clean(res.json())


def create_folder(name: str, parent_id: str = '', email: str = None) -> Dict:
    payload: Dict = {
        'name': name,
        'mimeType': 'application/vnd.google-apps.folder',
    }
    if parent_id:
        payload['parents'] = [parent_id]
    res = requests.post(f'{API}/files', headers=auth_headers(email),
                        params={'fields': _FIELDS}, json=payload, timeout=30)
    check(res)
    return _clean(res.json())


def delete_file(file_id: str, email: str = None) -> bool:
    """Sposta nel cestino, non cancella. Il cestino e' recuperabile
    dall'utente; una cancellazione definitiva presa da un agente non lo
    sarebbe."""
    res = requests.patch(f'{API}/files/{file_id}', headers=auth_headers(email),
                         json={'trashed': True}, timeout=30)
    return res.status_code == 200


def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj)
