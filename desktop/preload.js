const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('samidaDesktop', {
  pickFolder: () => ipcRenderer.invoke('pick-folder'),
});
