const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('replyWindowAPI', {
  onLoadReply: (cb) => ipcRenderer.on('load-reply', (_, data) => cb(data)),
  ready:       ()   => ipcRenderer.send('reply-window-ready'),
  close:       ()   => ipcRenderer.send('reply-window-close'),
  minimize:    ()   => ipcRenderer.send('reply-window-minimize'),
  maximize:    ()   => ipcRenderer.send('reply-window-maximize'),
  resizeTo:    (w, h) => ipcRenderer.send('window-resize', { w, h }),
  followupSave: (data) => ipcRenderer.invoke('followup-save', data),
});
