//! Own only short-lived CLI operations. The detached application container is
//! deliberately outside this registry and is never stopped when a window closes.
use std::{
    collections::HashMap,
    io,
    process::Command,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    process::Child,
    sync::{watch, Notify},
};

#[derive(Clone, Default)]
pub(crate) struct Lifecycle(Arc<Inner>);

#[derive(Default)]
struct Inner {
    registry: Mutex<Registry>,
    changed: Notify,
    complete: AtomicBool,
}

#[derive(Default)]
struct Registry {
    shutting_down: bool,
    children: HashMap<u32, (watch::Sender<bool>, Arc<ProcessTree>)>,
}

impl Lifecycle {
    pub(crate) fn begin_shutdown(&self) -> bool {
        let mut registry = self
            .0
            .registry
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if registry.shutting_down {
            return false;
        }
        registry.shutting_down = true;
        for (cancel, _) in registry.children.values() {
            let _ = cancel.send(true);
        }
        true
    }

    pub(crate) fn is_complete(&self) -> bool {
        self.0.complete.load(Ordering::Acquire)
    }

    pub(crate) async fn shutdown(&self) {
        let drained = async {
            loop {
                let changed = self.0.changed.notified();
                if self
                    .0
                    .registry
                    .lock()
                    .unwrap_or_else(|error| error.into_inner())
                    .children
                    .is_empty()
                {
                    return;
                }
                changed.await;
            }
        };
        if tokio::time::timeout(Duration::from_secs(7), drained)
            .await
            .is_err()
        {
            let registry = self
                .0
                .registry
                .lock()
                .unwrap_or_else(|error| error.into_inner());
            for (_, tree) in registry.children.values() {
                tree.force_stop();
            }
        }
        self.0.complete.store(true, Ordering::Release);
    }

    pub(crate) fn spawn(&self, mut command: Command) -> io::Result<(Child, Operation)> {
        let mut registry = self
            .0
            .registry
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if registry.shutting_down {
            return Err(io::Error::new(
                io::ErrorKind::Interrupted,
                "omnideck is closing",
            ));
        }
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            use windows_sys::Win32::System::Threading::{CREATE_NO_WINDOW, CREATE_SUSPENDED};
            command.creation_flags(CREATE_NO_WINDOW | CREATE_SUSPENDED);
        }
        let mut command = tokio::process::Command::from(command);
        command.kill_on_drop(true);
        let child = command.spawn()?;
        let pid = child
            .id()
            .ok_or_else(|| io::Error::other("CLI has no process ID"))?;
        let tree = Arc::new(ProcessTree::new(pid, &child)?);
        let (cancel, cancellation) = watch::channel(false);
        registry.children.insert(pid, (cancel, tree.clone()));
        drop(registry);
        let operation = Operation {
            owner: self.clone(),
            pid,
            tree,
            cancellation,
        };
        #[cfg(windows)]
        resume_child(pid)?;
        Ok((child, operation))
    }
}

#[cfg(windows)]
fn resume_child(pid: u32) -> io::Result<()> {
    use windows_sys::Win32::{
        Foundation::{CloseHandle, INVALID_HANDLE_VALUE},
        System::{
            Diagnostics::ToolHelp::{
                CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD,
                THREADENTRY32,
            },
            Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME},
        },
    };
    // CREATE_SUSPENDED prevents CLI code (and descendant creation) until its
    // private job is assigned. std/tokio expose the process handle but not the
    // primary thread handle, so find that still-suspended thread by owned PID.
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if snapshot == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let mut entry: THREADENTRY32 = std::mem::zeroed();
        entry.dwSize = std::mem::size_of::<THREADENTRY32>() as u32;
        let mut present = Thread32First(snapshot, &mut entry);
        let mut result = Err(io::Error::other("Suspended CLI thread not found"));
        while present != 0 {
            if entry.th32OwnerProcessID == pid {
                let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                if thread.is_null() {
                    result = Err(io::Error::last_os_error());
                } else {
                    result = if ResumeThread(thread) == u32::MAX {
                        Err(io::Error::last_os_error())
                    } else {
                        Ok(())
                    };
                    CloseHandle(thread);
                }
                break;
            }
            present = Thread32Next(snapshot, &mut entry);
        }
        CloseHandle(snapshot);
        result
    }
}

pub(crate) struct Operation {
    owner: Lifecycle,
    pid: u32,
    tree: Arc<ProcessTree>,
    cancellation: watch::Receiver<bool>,
}

impl Operation {
    pub(crate) async fn cancelled(&mut self) {
        if !*self.cancellation.borrow() {
            let _ = self.cancellation.changed().await;
        }
    }

    pub(crate) async fn stop(&self, child: &mut Child) {
        self.tree.request_stop();
        let _ = tokio::time::timeout(Duration::from_secs(3), child.wait()).await;
        // Also catch descendants that outlived their CLI parent or ignored TERM.
        self.tree.force_stop();
        let _ = tokio::time::timeout(Duration::from_secs(2), child.wait()).await;
        self.complete();
    }

    pub(crate) fn complete(&self) {
        self.tree.armed.store(false, Ordering::Release);
    }
}

impl Drop for Operation {
    fn drop(&mut self) {
        self.tree.force_stop();
        self.owner
            .0
            .registry
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .children
            .remove(&self.pid);
        self.owner.0.changed.notify_waiters();
    }
}

struct ProcessTree {
    armed: AtomicBool,
    #[cfg(unix)]
    pid: u32,
    #[cfg(target_os = "macos")]
    helpers: DirectHelpers,
    #[cfg(windows)]
    job: windows_sys::Win32::Foundation::HANDLE,
}

// A job handle is an owned, thread-safe kernel reference, never a Rust pointer.
#[cfg(windows)]
unsafe impl Send for ProcessTree {}
#[cfg(windows)]
unsafe impl Sync for ProcessTree {}

impl ProcessTree {
    fn new(pid: u32, _child: &Child) -> io::Result<Self> {
        #[cfg(unix)]
        return Ok(Self {
            armed: AtomicBool::new(true),
            pid,
            #[cfg(target_os = "macos")]
            helpers: DirectHelpers::new(pid)?,
        });
        #[cfg(windows)]
        {
            use windows_sys::Win32::{
                Foundation::CloseHandle,
                System::JobObjects::{AssignProcessToJobObject, CreateJobObjectW},
            };
            let _ = pid;
            // SAFETY: null attributes/name request a private unnamed job. The
            // child handle is valid for the lifetime of the borrowed Child.
            let job = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
            if job.is_null() {
                return Err(io::Error::last_os_error());
            }
            let handle = _child
                .raw_handle()
                .ok_or_else(|| io::Error::other("CLI handle unavailable"));
            let assigned = handle.and_then(|handle| {
                if unsafe { AssignProcessToJobObject(job, handle as _) } == 0 {
                    Err(io::Error::last_os_error())
                } else {
                    Ok(())
                }
            });
            if let Err(error) = assigned {
                unsafe {
                    CloseHandle(job);
                }
                return Err(error);
            }
            Ok(Self {
                armed: AtomicBool::new(true),
                job,
            })
        }
    }

    fn request_stop(&self) {
        if !self.armed.load(Ordering::Acquire) {
            return;
        }
        #[cfg(target_os = "macos")]
        self.helpers.signal(libc::SIGTERM);
        #[cfg(unix)]
        // SAFETY: the child was spawned into its own process group. A negative
        // PID signals only that group, never the desktop or user's other tasks.
        unsafe {
            libc::kill(-(self.pid as i32), libc::SIGTERM);
        }
        #[cfg(windows)]
        // Windows sidecars have no console to receive Ctrl-Break. Terminate the
        // private job, including descendants, rather than just the CLI parent.
        self.force_stop();
    }

    fn force_stop(&self) {
        if !self.armed.load(Ordering::Acquire) {
            return;
        }
        #[cfg(target_os = "macos")]
        self.helpers.signal(libc::SIGKILL);
        #[cfg(unix)]
        unsafe {
            libc::kill(-(self.pid as i32), libc::SIGKILL);
        }
        #[cfg(windows)]
        unsafe {
            windows_sys::Win32::System::JobObjects::TerminateJobObject(self.job, 1);
        }
    }
}

#[cfg(any(target_os = "macos", all(test, unix)))]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct ProcessIdentity {
    pid: u32,
    parent: u32,
    started: (u64, u64),
}

#[cfg(any(target_os = "macos", all(test, unix)))]
impl ProcessIdentity {
    fn is_same_process(self, current: Option<Self>) -> bool {
        current.is_some_and(|current| self.pid == current.pid && self.started == current.started)
    }
}

#[cfg(any(target_os = "macos", all(test, unix)))]
fn remember_direct_helpers(
    root: ProcessIdentity,
    known: &mut Vec<ProcessIdentity>,
    read: impl Fn(u32) -> Option<ProcessIdentity>,
    children: impl Fn(u32) -> Vec<u32>,
) {
    if !root.is_same_process(read(root.pid)) {
        return;
    }
    for pid in children(root.pid) {
        if let Some(helper) = read(pid).filter(|helper| helper.parent == root.pid) {
            if !known
                .iter()
                .any(|known| known.is_same_process(Some(helper)))
            {
                known.push(helper);
            }
        }
    }
}

#[cfg(target_os = "macos")]
struct DirectHelpers {
    root: ProcessIdentity,
    known: Mutex<Vec<ProcessIdentity>>,
}

#[cfg(target_os = "macos")]
impl DirectHelpers {
    fn new(pid: u32) -> io::Result<Self> {
        Ok(Self {
            root: Self::identity(pid)
                .ok_or_else(|| io::Error::other("CLI process identity unavailable"))?,
            known: Mutex::new(Vec::new()),
        })
    }

    fn identity(pid: u32) -> Option<ProcessIdentity> {
        // SAFETY: proc_pidinfo writes into an initialized correctly sized BSD
        // info structure for this PID. No returned pointer is retained.
        let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
        let size = std::mem::size_of_val(&info) as i32;
        let read = unsafe {
            libc::proc_pidinfo(
                pid as i32,
                libc::PROC_PIDTBSDINFO,
                0,
                (&mut info as *mut libc::proc_bsdinfo).cast(),
                size,
            )
        };
        (read == size).then_some(ProcessIdentity {
            pid: info.pbi_pid,
            parent: info.pbi_ppid,
            started: (info.pbi_start_tvsec, info.pbi_start_tvusec),
        })
    }

    fn children(pid: u32) -> Vec<u32> {
        // The pinned CLI creates its macOS helpers with setsid(), outside the
        // CLI group. Snapshot only direct helpers, never their persistent VM
        // descendants. The root and each helper are checked against birth time.
        let count = unsafe { libc::proc_listchildpids(pid as i32, std::ptr::null_mut(), 0) }.max(0)
            as usize;
        let mut children = vec![0i32; (count + 16).min(4096)];
        let count = unsafe {
            libc::proc_listchildpids(
                pid as i32,
                children.as_mut_ptr().cast(),
                std::mem::size_of_val(children.as_slice()) as i32,
            )
        }
        .max(0) as usize;
        children
            .into_iter()
            .take(count)
            .filter(|pid| *pid > 0)
            .map(|pid| pid as u32)
            .collect()
    }

    fn signal(&self, signal: i32) {
        let mut known = self.known.lock().unwrap_or_else(|error| error.into_inner());
        remember_direct_helpers(self.root, &mut known, Self::identity, Self::children);
        for helper in known.iter() {
            if helper.is_same_process(Self::identity(helper.pid)) {
                unsafe {
                    libc::kill(helper.pid as i32, signal);
                }
            }
        }
    }
}

impl Drop for ProcessTree {
    fn drop(&mut self) {
        self.force_stop();
        #[cfg(windows)]
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.job);
        }
    }
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::process::Stdio;
    use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};

    #[test]
    fn separated_session_helpers_exclude_vm_descendants_and_reused_pids() {
        let root = ProcessIdentity {
            pid: 10,
            parent: 1,
            started: (1, 0),
        };
        let helper = ProcessIdentity {
            pid: 20,
            parent: 10,
            started: (2, 0),
        };
        let vm = ProcessIdentity {
            pid: 30,
            parent: 20,
            started: (3, 0),
        };
        let processes = HashMap::from([(10, root), (20, helper), (30, vm)]);
        let mut known = Vec::new();
        remember_direct_helpers(
            root,
            &mut known,
            |pid| processes.get(&pid).copied(),
            |pid| {
                processes
                    .values()
                    .filter(|process| process.parent == pid)
                    .map(|process| process.pid)
                    .collect()
            },
        );
        assert_eq!(known, [helper]);
        assert!(
            helper.is_same_process(Some(ProcessIdentity {
                parent: 1,
                ..helper
            })),
            "reparenting preserves identity"
        );
        assert!(
            !helper.is_same_process(Some(ProcessIdentity {
                started: (99, 0),
                ..helper
            })),
            "reused PIDs must not be signaled"
        );
        remember_direct_helpers(
            root,
            &mut known,
            |_| {
                Some(ProcessIdentity {
                    started: (99, 0),
                    ..root
                })
            },
            |_| panic!("must not inspect a reused CLI PID"),
        );
        assert_eq!(known, [helper]);
    }

    #[tokio::test]
    async fn shutdown_cancels_and_reaps_an_owned_process() {
        let lifecycle = Lifecycle::default();
        let mut command = Command::new("sh");
        command
            .args(["-c", "sleep 60"])
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let (mut child, mut operation) = lifecycle.spawn(command).unwrap();
        assert!(lifecycle.begin_shutdown());
        operation.cancelled().await;
        operation.stop(&mut child).await;
        assert!(child.try_wait().unwrap().is_some());
        drop(operation);
        lifecycle.shutdown().await;
        assert!(lifecycle.is_complete());
        assert!(lifecycle.spawn(Command::new("true")).is_err());
    }

    #[tokio::test]
    async fn successful_operation_leaves_its_background_work_alone() {
        let lifecycle = Lifecycle::default();
        let mut command = Command::new("sh");
        command
            .args(["-c", "sleep 60 >/dev/null 2>&1 & echo $!"])
            .stdout(Stdio::piped());
        let (mut child, operation) = lifecycle.spawn(command).unwrap();
        let mut output = String::new();
        child
            .stdout
            .take()
            .unwrap()
            .read_to_string(&mut output)
            .await
            .unwrap();
        let descendant: i32 = output.trim().parse().unwrap();
        assert!(child.wait().await.unwrap().success());
        operation.complete();
        drop(operation);
        lifecycle.begin_shutdown();
        lifecycle.shutdown().await;
        let alive = unsafe { libc::kill(descendant, 0) } == 0;
        unsafe {
            libc::kill(descendant, libc::SIGKILL);
        }
        assert!(
            alive,
            "normal completion or desktop shutdown killed background runtime work"
        );
    }

    #[cfg(target_os = "linux")]
    #[tokio::test]
    async fn cancellation_kills_descendants_that_ignore_term() {
        let lifecycle = Lifecycle::default();
        let mut command = Command::new("sh");
        command
            .args(["-c", "trap '' TERM; sleep 60 & echo $!; wait"])
            .stdout(Stdio::piped());
        let (mut child, operation) = lifecycle.spawn(command).unwrap();
        let mut output = String::new();
        BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut output)
            .await
            .unwrap();
        let descendant: u32 = output.trim().parse().unwrap();
        operation.stop(&mut child).await;
        // An orphan can briefly remain a zombie until PID 1 reaps it. It must
        // never still be executing after the process group's cancellation.
        tokio::time::timeout(Duration::from_secs(1), async {
            loop {
                let Ok(status) = std::fs::read_to_string(format!("/proc/{descendant}/stat")) else {
                    return;
                };
                let state = status
                    .rsplit_once(')')
                    .unwrap()
                    .1
                    .split_whitespace()
                    .next()
                    .unwrap();
                if matches!(state, "Z" | "X") {
                    return;
                }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("descendant still running after cancellation");
    }
}
