# Folder apps spike

Enable the integrated spike with:

```text
Enable **Custom Apps** in **Settings → System → Experimental**.
```

Omnideck discovers the packaged samples in this directory and user-editable
apps under `/home/omnideck/apps`. A direct child is an app when it has this
shape:

```text
my-app/
  omnideck.json
  web/
    index.html
  app.py          # optional
```

The direct child may also be a directory symlink. Omnideck uses the link name
as the app slug, resolves the target, and validates the same structure there.
This makes a separate app monorepo an optional source of truth without making
that layout mandatory:

```bash
ln -s /home/omnideck/custom-apps-repo/my-app /home/omnideck/apps/my-app
```

Broken or looping links are ignored.

`app.py` exports an `actions` dictionary whose values are normal Python
functions. The frontend calls them with `window.omnideck.invoke(name, args)`.
Each invocation loads the current files in a new Python subprocess, so edits
take effect without registering or rebuilding the app. Actions may run for up
to 120 seconds and should return JSON; write large outputs to app-owned files
and return their URLs rather than encoding the files in the action result.

App-hosted, `data:`, and `blob:` images, audio, and video are allowed. Apps may
offer user-initiated downloads directly or ask the shell to download a file
beneath their own `web/` directory:

```js
window.omnideck.download({
  url: './generated/example.png',
  filename: 'example.png',
});
```

An app can explicitly open the current conversation beside itself with
`window.omnideck.chat.open()`, or seed the composer with
`window.omnideck.chat.compose({ text, context })`. These calls never read chat
history or send a message automatically.

Open an app from **Apps** and choose **Set as Home** to make it the default
landing view on the next page load. The shell keeps a trusted toolbar around
the app for reloading it, returning to Apps, or removing it from Home. **New
chat** opens a fresh conversation beside any currently open app.

Apps can open full-space or as a shell-scoped tab beside Chat. App tabs remain
mounted when conversations change; browser, file, terminal, desktop, and
generation tabs remain conversation-scoped. Closing the app tab discards its
in-memory iframe state without deleting the app or changing its Home setting.

This is a trusted-local-code experiment. The subprocess has a clean environment,
an invocation timeout, and no in-process access to the Omnideck server, but it is
not a filesystem or network sandbox. Keep the flag off for untrusted or imported
apps.
