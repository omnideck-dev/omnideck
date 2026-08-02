const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('omnideckHost', {
  beginSetup: () => ipcRenderer.invoke('omnideck:begin-setup'),
  openApp: () => ipcRenderer.invoke('omnideck:open-app'),
  retry: () => ipcRenderer.invoke('omnideck:retry'),
  runAction: (action) => ipcRenderer.invoke('omnideck:action', action),
  onState: (listener) => {
    const wrapped = (_event, state) => listener(state);
    ipcRenderer.on('omnideck:state', wrapped);
    return () => ipcRenderer.removeListener('omnideck:state', wrapped);
  },
  // Used by omnideck itself rather than by the setup screen. Both pages load in
  // the same window and so see the same bridge; which calls are allowed is
  // decided by where the call came from, not by what is on offer here.
  onUpdate: (listener) => {
    const wrapped = (_event, update) => listener(update);
    ipcRenderer.on('omnideck:update', wrapped);
    return () => ipcRenderer.removeListener('omnideck:update', wrapped);
  },
  // Asked for on load, because a page that was not listening yet cannot have
  // been told. Everything after that arrives through onUpdate.
  currentUpdate: () => ipcRenderer.invoke('omnideck:update-current'),
  checkForUpdate: () => ipcRenderer.invoke('omnideck:update-check'),
  installUpdate: () => ipcRenderer.invoke('omnideck:update-action', 'install'),
  deferUpdate: () => ipcRenderer.invoke('omnideck:update-action', 'later'),
  skipUpdate: () => ipcRenderer.invoke('omnideck:update-action', 'skip'),
});
