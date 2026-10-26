const { contextBridge, ipcRenderer } = require('electron');
const GIGAMAIL_API = ((process.argv || []).find((a) => a.startsWith('--gigamail-api=')) || '').slice('--gigamail-api='.length) || 'http://127.0.0.1:8002';
contextBridge.exposeInMainWorld('GIGAMAIL_API', GIGAMAIL_API);
contextBridge.exposeInMainWorld('replyAlertWindowAPI', {
  onLoad:   (cb) => ipcRenderer.on('load-reply-alert', (_, data) => cb(data)),
  close:    ()   => ipcRenderer.send('approval-window-close'),
  minimize: ()   => ipcRenderer.send('approval-window-minimize'),
  resizeTo: (w, h) => ipcRenderer.send('window-resize', { w, h }),
});
