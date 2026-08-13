const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('marketingWindowAPI', {
  close:    () => ipcRenderer.send('marketing-window-close'),
  minimize: () => ipcRenderer.send('marketing-window-minimize'),
  maximize: () => ipcRenderer.send('marketing-window-maximize'),
});
