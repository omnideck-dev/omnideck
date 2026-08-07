# Manual release check

One pass per operating system, on hardware you can reset. Everything here is
something CI genuinely cannot do — an elevation prompt with nobody to answer it
is not a test.

## What CI already covers, so you don't have to

Don't spend manual time on these; a red build already tells you.

- The setup state machine: which screen appears for which situation, resuming an
  interrupted install, how failures are classified.
- The application launching, its window reaching the screen, the bridge between
  the window and the setup screen, and every element the screen writes to.
- The failure screen: its title, its phase list, and both of its buttons.
- The fullest screen fitting the smallest allowed window.
- Which stream podman answers on and which exit codes mean "absent".
- macOS and Windows launch on their own runners, so window creation, path
  handling and theme selection are covered there too.

## What only you can check

| | why |
| --- | --- |
| The administrator prompt | needs someone to approve or dismiss it |
| Installing podman through the app | that install is behind the prompt |
| Preparing the secure space | macOS and Windows only, and slow to provision |
| Turning on Windows Subsystem for Linux | needs a real restart |
| Downloading and opening the actual installer | Gatekeeper and SmartScreen only react to a genuinely downloaded file |
| How it looks on your screen | your display is not the one CI renders on |

---

## Before you start

On Linux or macOS, confirm what the isolated reset is about to touch:

```bash
./reset-host.sh --inventory
```

Read the list. Anything marked `preserved` stays; anything marked `REMOVE`
belongs to the test namespace. If something you care about is listed as
`REMOVE`, stop — that means the namespace is wrong.

Then return the machine to a pre-install state:

```bash
./reset-host.sh
```

On the disposable Windows test computer, use the destructive reset. It removes
all WSL distributions and features, all Podman and omnideck state, and then
restarts Windows. Nothing related to WSL or Podman is preserved.

```powershell
.\reset-host.ps1 -Inventory
.\reset-host.ps1 -Yes -Restart
```

After sign-in, run `.\reset-host.ps1 -Inventory` again. Do not begin the pass
until it reports no WSL, Podman, omnideck application, or installed state.

---

## Pass 1 — a clean first install

This is the pass that matters. Everything else is cheap by comparison.

```bash
./linux.sh --scenario first-run      # or ./macos.sh, or .\windows.ps1 -Scenario FirstRun
```

Work through the screens in order and check each one.

### 1. Opening

- [ ] A window appears **immediately** — not after a pause.
- [ ] It reads **Starting omnideck**, not "Welcome", for the moment before the
      checks finish.
- [ ] Light or dark matches your system setting.

### 2. Welcome

- [ ] Title is **Welcome to omnideck**, with one button: **Set up omnideck**.
- [ ] The note about Agent Dash is visible.

Click **Set up omnideck**.

### 3. Getting your computer ready

- [ ] One line reads **Getting your computer ready…** above a progress bar.
- [ ] There is no list of components anywhere on screen.
- [ ] Agent Dash becomes playable. Play it — it should be smooth while the
      install runs, not stuttery.

### 4. The permission prompt — the important one

- [ ] The screen changes to **Waiting for your permission** *before* the system
      prompt appears.
- [ ] It names what is being installed, and says omnideck never sees your
      password.

> **macOS** — a native authorization dialog naming the installer.
> **Windows** — a User Account Control prompt.
> **Linux** — a polkit dialog. Some desktops have no polkit agent running; if no
> dialog appears at all, that is the failure to report.

Now **dismiss it** rather than approving it.

- [ ] The failure screen says **omnideck needs your permission** — not a generic
      message, and not a download or network error.
- [ ] **Try again** is offered.

Click **Try again** and approve it this time.

### 5. Preparing a secure space — macOS and Windows only

- [ ] The line reads **Preparing a secure space to run in…**
- [ ] On Linux this step does **not** appear at all. If it does, that is a bug.

> **Windows** — if WSL 2 was not already on, expect **Restart needed** here. It
> should say your progress is saved and setup continues on its own. Restart, open
> omnideck, and confirm it picks up without asking anything.

### 6. Downloading

- [ ] The line reads **Downloading omnideck's files…**
- [ ] A percentage advances. It should move steadily, not sit still and jump.
- [ ] This is the long step — roughly 670 MB.

### 7. Ready

- [ ] **omnideck is ready**, with **Open omnideck**.
- [ ] Clicking it opens the application in the same window.

---

## Pass 2 — the cheap ones

No reset needed; podman is installed now. Each takes under a minute.

```bash
./linux.sh --scenario returning
```

- [ ] Briefly shows **Starting omnideck**, then goes straight to the
      application.
- [ ] It never shows Welcome, a progress bar, or the note about Agent Dash.

```bash
./linux.sh --scenario doctor
```

- [ ] The failure screen names the step that failed.
- [ ] Steps before it are marked done; steps after it are not started.
- [ ] **Show diagnostic log** opens the log.

```bash
./linux.sh --scenario resume
```

- [ ] Eyebrow reads **CONTINUING SETUP**.
- [ ] The line says work already finished was kept.
- [ ] It continues on its own — no button to press.

```bash
./linux.sh --scenario update
```

- [ ] Reads **Bringing omnideck up to date**.
- [ ] Nothing asks permission and nothing blocks opening.

---

## Pass 3 — the installer itself

Only meaningful with the real published artifact, downloaded through a browser.

> **macOS** — Gatekeeper. Unsigned builds need Control-click → Open. Confirm the
> warning text names omnideck. Confirm the app runs from `/Applications` and not
> from the mounted disk image.
>
> **Windows** — Microsoft Defender SmartScreen. Confirm "More info" → "Run
> anyway" works, and that the installer does not leave a second copy of omnideck
> running afterwards.
>
> **Linux** — check the format you ship for that distribution: `.deb`, `.rpm`, or
> the `.AppImage`. The AppImage needs the executable bit set.

---

## Look at it

Things CI measures but cannot judge.

- [ ] Resize the window down to its smallest. Nothing is cut off; every button
      stays clickable.
- [ ] Switch your system between light and dark while it is open. Both look
      deliberate.
- [ ] Text is comfortable at your display's scaling, not just legible.

---

## Sign-off

| | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Pass 1 — clean install | | | |
| Pass 2 — the cheap ones | | | |
| Pass 3 — the installer | | | |
| Look at it | | | |

Record the version, the machine, and anything that surprised you — including
things that worked but felt wrong. Those are the notes worth keeping.
