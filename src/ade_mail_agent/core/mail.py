"""
mail.py — Lettura, invio e gestione mail via Microsoft Graph API.
"""
import requests
from .auth import get_token
from typing import Optional, List, Dict
GRAPH_URL = 'https://graph.microsoft.com/v1.0'
def _headers() -> dict:
    return {'Authorization': f'Bearer {get_token()}', 'Content-Type': 'application/json'}
def get_messages(folder: str = 'inbox', top: int = 20, skip: int = 0) -> List[Dict]:
    url = f'{GRAPH_URL}/me/mailFolders/{folder}/messages'
    params = {
        '$top': top,
        '$skip': skip,
        '$select': 'id,subject,from,receivedDateTime,isRead,bodyPreview,hasAttachments',
        '$orderby': 'receivedDateTime desc',
    }
    res = requests.get(url, headers=_headers(), params=params)
    res.raise_for_status()
    return res.json().get('value', [])
def get_message(message_id: str) -> Dict:
    url = f'{GRAPH_URL}/me/messages/{message_id}'
    params = {'$select': 'id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,bodyPreview,isRead,hasAttachments'}
    res = requests.get(url, headers=_headers(), params=params)
    if res.status_code == 404:
        # ID stale (mail spostata di cartella) o non trovata: segnala senza crashare
        raise ValueError(f"Messaggio Graph non trovato (404): {message_id}")
    res.raise_for_status()
    msg = res.json()

    # Allegati: su Graph sono una sotto-risorsa separata, non un campo $select
    if msg.get('hasAttachments'):
        try:
            att_url = f'{GRAPH_URL}/me/messages/{message_id}/attachments'
            att_params = {'$select': 'id,name,contentType,size,isInline'}
            att_res = requests.get(att_url, headers=_headers(), params=att_params)
            if att_res.ok:
                items = att_res.json().get('value', [])
                # Escludi gli allegati inline (loghi/firme nel corpo), tieni i veri allegati
                msg['attachments'] = [
                    {
                        'id': a.get('id'),
                        'name': a.get('name'),
                        'size': a.get('size'),
                        'type': a.get('contentType'),
                    }
                    for a in items
                    if not a.get('isInline', False)
                ]
        except Exception as e:
            print(f"[MAIL] attachments fetch error: {e}")
            msg['attachments'] = []

    try:
        mark_read(message_id)
    except Exception:
        pass
    return msg
def mark_read(message_id: str):
    url = f'{GRAPH_URL}/me/messages/{message_id}'
    requests.patch(url, headers=_headers(), json={'isRead': True})
def set_read_status(message_id: str, is_read: bool = True):
    url = f'{GRAPH_URL}/me/messages/{message_id}'
    requests.patch(url, headers=_headers(), json={'isRead': is_read})
def send_message(to: str, subject: str, body: str,
                 reply_to_id: str = None,
                 cc: list = None, bcc: list = None,
                 attachments: list = None) -> Dict:
    """Invia una mail. Supporta CC, BCC, reply e allegati (fileAttachment)."""
    def _recipients(addrs: list) -> list:
        return [{'emailAddress': {'address': a}} for a in (addrs or [])]

    def _graph_attachments(atts: list) -> list:
        """Converte [{name, data_b64, type}] in fileAttachment Graph."""
        out = []
        for a in (atts or []):
            b64 = a.get('data_b64') or a.get('contentBytes')
            if not b64:
                continue
            out.append({
                '@odata.type': '#microsoft.graph.fileAttachment',
                'name': a.get('name') or 'allegato',
                'contentType': a.get('type') or 'application/octet-stream',
                'contentBytes': b64,
            })
        return out

    graph_atts = _graph_attachments(attachments)

    if reply_to_id and not graph_atts:
        # Reply senza allegati: endpoint /reply (mantiene il thread)
        url = f'{GRAPH_URL}/me/messages/{reply_to_id}/reply'
        payload = {'message': {'body': {'contentType': 'Text', 'content': body}}, 'comment': body}
        res = requests.post(url, headers=_headers(), json=payload)
    else:
        # sendMail: invio nuovo o forward; supporta allegati inline (<~3MB totali)
        url = f'{GRAPH_URL}/me/sendMail'
        msg = {
            'subject': subject,
            'body': {'contentType': 'Text', 'content': body},
            'toRecipients': _recipients([to]),
        }
        if cc:
            msg['ccRecipients'] = _recipients(cc)
        if bcc:
            msg['bccRecipients'] = _recipients(bcc)
        if graph_atts:
            msg['attachments'] = graph_atts
        payload = {'message': msg}
        res = requests.post(url, headers=_headers(), json=payload)
    ok = res.status_code in (200, 202)
    requested = 1 + len(cc or []) + len(bcc or [])
    # Graph risponde 202 Accepted senza corpo: non dice nulla per
    # destinatario, e l'espansione di gruppi/liste la fa lui dopo. Lo
    # dichiariamo invece di fingere un conteggio verificato.
    provider_result = {
        'provider': 'graph',
        'http_status': res.status_code,
        'request_id': res.headers.get('request-id') or res.headers.get('client-request-id'),
        'requested': requested,
        'accepted': None,  # non osservabile via sendMail
        'per_recipient_verified': False,
        'note': 'Graph sendMail returns 202 with no per-recipient result; '
                'group/alias expansion happens server-side after acceptance.',
    }
    if not ok:
        provider_result['error'] = f'HTTP {res.status_code}: {res.text[:300]}'
    return {
        'success': ok,
        'provider': 'microsoft',
        'sent_copy_saved': ok,
        'warning': None,
        'error': None if ok else f'HTTP {res.status_code}: {res.text[:300]}',
        'provider_result': provider_result,
    }
def get_attachment(message_id: str, filename: str = '') -> tuple:
    """
    Scarica un allegato via Graph. Ritorna (bytes, content_type) per coerenza
    con imap.get_attachment e con l'endpoint /mail/{id}/attachment.
    Cerca per nome esatto; se non trovato, prende il primo non-inline.
    """
    import base64
    # NB: 'contentBytes' NON è selezionabile nella lista /attachments (Graph 400).
    # Si recupera solo sul singolo allegato.
    list_url = f'{GRAPH_URL}/me/messages/{message_id}/attachments'
    res = requests.get(list_url, headers=_headers(),
                       params={'$select': 'id,name,contentType,size,isInline'})
    res.raise_for_status()
    items = res.json().get('value', [])
    if not items:
        raise ValueError('Nessun allegato nel messaggio')

    target = None
    if filename:
        target = next((a for a in items if (a.get('name') or '') == filename), None)
    if target is None:
        target = next((a for a in items if not a.get('isInline')), items[0])

    # Recupera il singolo allegato completo (include contentBytes per i fileAttachment)
    one_url = f'{GRAPH_URL}/me/messages/{message_id}/attachments/{target["id"]}'
    one_res = requests.get(one_url, headers=_headers())
    one_res.raise_for_status()
    att = one_res.json()

    content_b64 = att.get('contentBytes')
    if content_b64:
        data = base64.b64decode(content_b64)
    else:
        # itemAttachment / referenceAttachment: prova /$value
        val_url = f'{GRAPH_URL}/me/messages/{message_id}/attachments/{target["id"]}/$value'
        vr = requests.get(val_url, headers=_headers())
        vr.raise_for_status()
        data = vr.content

    return (data, att.get('contentType') or target.get('contentType') or 'application/octet-stream')


def get_priority_messages(top: int = 20) -> List[Dict]:
    url = f'{GRAPH_URL}/me/mailFolders/inbox/messages'
    params = {
        '$top': top,
        '$select': 'id,subject,from,receivedDateTime,isRead,bodyPreview,importance',
        '$orderby': 'receivedDateTime desc',
        '$filter': "importance eq 'high' or isRead eq false",
    }
    res = requests.get(url, headers=_headers(), params=params)
    res.raise_for_status()
    return res.json().get('value', [])
def search_messages(query: str, top: int = 10) -> List[Dict]:
    url = f'{GRAPH_URL}/me/messages'
    params = {
        '$search': f'"{query}"',
        '$top': top,
        '$select': 'id,subject,from,receivedDateTime,bodyPreview',
    }
    res = requests.get(url, headers=_headers(), params=params)
    res.raise_for_status()
    return res.json().get('value', [])
def move_to_folder(message_id: str, folder_id: str) -> bool:
    url = f'{GRAPH_URL}/me/messages/{message_id}/move'
    res = requests.post(url, headers=_headers(), json={'destinationId': folder_id})
    return res.status_code == 201

def list_folders() -> List[Dict]:
    url = f'{GRAPH_URL}/me/mailFolders'
    params = {'$top': 200, '$select': 'id,displayName,parentFolderId,childFolderCount,totalItemCount,unreadItemCount'}
    res = requests.get(url, headers=_headers(), params=params)
    res.raise_for_status()
    return res.json().get('value', [])

def create_folder(name: str) -> Dict:
    url = f'{GRAPH_URL}/me/mailFolders'
    res = requests.post(url, headers=_headers(), json={'displayName': name})
    res.raise_for_status()
    return res.json()

def delete_folder(folder_id: str) -> bool:
    url = f'{GRAPH_URL}/me/mailFolders/{folder_id}'
    res = requests.delete(url, headers=_headers())
    return res.status_code in (200, 202, 204)

def delete_message(message_id: str) -> bool:
    url = f'{GRAPH_URL}/me/messages/{message_id}/move'
    res = requests.post(url, headers=_headers(), json={'destinationId': 'deleteditems'})
    return res.status_code == 201
