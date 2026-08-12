const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('calendarWindowAPI', {
  close:    () => ipcRenderer.send('calendar-window-close'),
  minimize: () => ipcRenderer.send('calendar-window-minimize'),
  maximize: () => ipcRenderer.send('calendar-window-maximize'),
});
