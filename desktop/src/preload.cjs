const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('omnideckDesktop', {
  beginSetup: () => ipcRenderer.invoke('omnideck:begin-setup'),
  openApp: () => ipcRenderer.invoke('omnideck:open-app'),
  retry: () => ipcRenderer.invoke('omnideck:retry'),
  runAction: (action) => ipcRenderer.invoke('omnideck:action', action),
  onState: (listener) => {
    const wrapped = (_event, state) => listener(state);
    ipcRenderer.on('omnideck:state', wrapped);
    return () => ipcRenderer.removeListener('omnideck:state', wrapped);
  },
});
