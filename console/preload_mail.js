/**
 * preload_mail.js — preload per mail_window.html
 */
const { contextBridge, ipcRenderer, shell } = require('electron');

contextBridge.exposeInMainWorld('mailWindowAPI', {
  onLoadMail:    (cb) => ipcRenderer.on('load-mail', (_, data) => cb(data)),
  close:         ()  => ipcRenderer.send('mail-window-close'),
  minimize:      ()  => ipcRenderer.send('mail-window-minimize'),
  maximize:      ()  => ipcRenderer.send('mail-window-maximize'),
  openReply:     (data) => ipcRenderer.send('mail-window-open-reply', data),
  openForward:   (data) => ipcRenderer.send('mail-window-open-reply', data),
  openExternal:  (url)  => ipcRenderer.invoke('mail-window-open-external', url),
  dockBack:      (data) => ipcRenderer.send('mail-window-dock-back', data),

  // ── Allegati ──
  // Apre l'allegato: scrive i bytes in un file temp e lo apre con l'app di sistema.
  openAttachment: (name, bytes) =>
    ipcRenderer.invoke('mail-attachment-open', { name, bytes }),
  // Salva con nome: apre il dialog di salvataggio e scrive i bytes.
  saveAttachmentAs: (name, bytes) =>
    ipcRenderer.invoke('mail-attachment-save-as', { name, bytes }),
});

