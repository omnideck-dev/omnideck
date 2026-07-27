const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('omnideckDesktop', {
  beginSetup: () => ipcRenderer.invoke('omnideck:begin-setup'),
  doctorAction: (action) => ipcRenderer.invoke('omnideck:doctor-action', action),
  openApp: () => ipcRenderer.invoke('omnideck:open-app'),
  retry: () => ipcRenderer.invoke('omnideck:retry'),
  showLogs: () => ipcRenderer.invoke('omnideck:show-logs'),
  onState: (listener) => {
    const wrapped = (_event, state) => listener(state);
    ipcRenderer.on('omnideck:state', wrapped);
    return () => ipcRenderer.removeListener('omnideck:state', wrapped);
  },
});
