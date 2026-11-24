use serde::Deserialize;
use std::{
    io::{BufRead, BufReader, Read, Write},
    path::Path,
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

#[derive(Deserialize)]
struct Readiness {
    port: u16,
    pid: u32,
    supervisor_pid: Option<u32>,
    instance_id: String,
}

/// Windows has no process groups: the sidecar and every process it creates are put in a Job Object
/// that kills them all when terminated or when the shell's handle closes (also if the shell crashes).
#[cfg(windows)]
mod job {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    pub struct Job(HANDLE);
    // The handle is only used for kernel calls that are safe from any thread.
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        /// Children created by the sidecar after this call inherit the job.
        pub fn assign(child: &std::process::Child) -> Option<Job> {
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if handle.is_null() {
                    return None;
                }
                let job = Job(handle);
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let configured = SetInformationJobObject(
                    job.0,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if configured == 0 || AssignProcessToJobObject(job.0, child.as_raw_handle() as HANDLE) == 0 {
                    return None;
                }
                Some(job)
            }
        }

        pub fn terminate(&self) {
            unsafe {
                TerminateJobObject(self.0, 1);
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

#[cfg(not(windows))]
mod job {
    pub struct Job;
    impl Job {
        pub fn assign(_child: &std::process::Child) -> Option<Job> {
            None
        }
        pub fn terminate(&self) {}
    }
}

/// Kill the owned sidecar and everything it started: Windows Job Object, or on Unix its own
/// process group, so the PyInstaller worker cannot be orphaned while blocked (AUDIT-L3).
fn kill_owned(child: &mut Child, job: Option<&job::Job>) {
    if let Some(job) = job {
        job.terminate();
    }
    #[cfg(unix)]
    {
        extern "C" {
            fn kill(pid: i32, sig: i32) -> i32;
        }
        // Still unreaped here, so the pid (= pgid) cannot have been reused.
        if let Ok(pgid) = i32::try_from(child.id()) {
            unsafe {
                kill(-pgid, 9);
            }
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn ready_url(line: &str, owned_pid: u32) -> Result<String, String> {
    let ready: Readiness =
        serde_json::from_str(line).map_err(|_| "Handshake del servizio non valido.")?;
    // PyInstaller onefile reports the Python worker PID and its owned bootloader supervisor.
    if ready.port == 0
        || ready.pid == 0
        || (ready.pid != owned_pid && ready.supervisor_pid != Some(owned_pid))
        || ready.instance_id.is_empty()
    {
        return Err("Il servizio non corrisponde al processo avviato.".into());
    }
    Ok(format!("http://127.0.0.1:{}", ready.port))
}

pub struct Service {
    child: Arc<Mutex<Child>>,
    job: Option<job::Job>,
    stopping: Arc<AtomicBool>,
    pub url: String,
}

impl Service {
    #[cfg(test)]
    fn from_child(child: Child, url: String) -> Self {
        let job = job::Job::assign(&child);
        Self::with_job(child, url, job)
    }

    fn with_job(child: Child, url: String, job: Option<job::Job>) -> Self {
        Self {
            child: Arc::new(Mutex::new(child)),
            job,
            stopping: Arc::new(AtomicBool::new(false)),
            url,
        }
    }

    pub fn monitor(&self, on_exit: impl FnOnce() + Send + 'static) {
        let child = Arc::downgrade(&self.child);
        let stopping = self.stopping.clone();
        thread::spawn(move || loop {
            if stopping.load(Ordering::SeqCst) {
                return;
            }
            let Some(child) = child.upgrade() else {
                return;
            };
            let running = child
                .lock()
                .map(|mut child| matches!(child.try_wait(), Ok(None)))
                .unwrap_or(false);
            if !running {
                if !stopping.load(Ordering::SeqCst) {
                    on_exit();
                }
                return;
            }
            drop(child);
            thread::sleep(Duration::from_millis(100));
        });
    }

    pub fn start(binary: &Path, ui: &Path, data: &Path) -> Result<Self, String> {
        if !ui.join("index.html").is_file() {
            return Err("Asset React mancanti: eseguire la build del frontend.".into());
        }
        std::fs::create_dir_all(data).map_err(|_| "Directory dati dell'app non disponibile.")?;
        let mut command = Command::new(binary);
        #[cfg(unix)]
        std::os::unix::process::CommandExt::process_group(&mut command, 0);
        let mut child = command
            .arg("--port")
            .arg("0")
            .arg("--ui-dir")
            .arg(ui)
            .arg("--data-dir")
            .arg(data)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| {
                "Backend confezionato non disponibile. Preparare il sidecar per questa piattaforma."
            })?;
        // Assigned before the handshake: PyInstaller's worker is created after extraction and inherits it.
        let job = job::Job::assign(&child);
        let pid = child.id();
        let stdout = match child.stdout.take() {
            Some(stdout) => stdout,
            None => {
                kill_owned(&mut child, job.as_ref());
                return Err("Stdout del servizio non disponibile.".into());
            }
        };
        let (send, receive) = mpsc::sync_channel(1);
        thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            let mut line = String::new();
            let result = (&mut reader)
                .take(4097)
                .read_line(&mut line)
                .map_err(|_| "Handshake non leggibile.".to_string())
                .and_then(|n| {
                    if n == 0 || n > 4096 {
                        Err("Handshake mancante o troppo lungo.".into())
                    } else {
                        ready_url(&line, pid)
                    }
                });
            let _ = send.send(result);
            // Drain stdout so future status output cannot block the owned backend.
            let _ = std::io::copy(&mut reader, &mut std::io::sink());
        });
        // First launch after install/update includes OS scanning and PyInstaller extraction: 13 s was
        // measured on an M5, so 15 s failed spuriously. Still fail-closed: kill + exit 1, no trading.
        match receive.recv_timeout(Duration::from_secs(30)) {
            Ok(Ok(url)) => Ok(Self::with_job(child, url, job)),
            result => {
                kill_owned(&mut child, job.as_ref());
                Err(match result {
                    Ok(Err(error)) => error,
                    _ => "Timeout nell'avvio del servizio locale.".into(),
                })
            }
        }
    }

    pub fn shutdown(&mut self) {
        // Two bounded 5s native reads plus a 5s close and cleanup need up to 18s.
        self.shutdown_within(Duration::from_secs(20));
    }

    fn shutdown_within(&mut self, grace: Duration) {
        self.stopping.store(true, Ordering::SeqCst);
        let Ok(mut child) = self.child.lock() else {
            return;
        };
        if let Some(mut input) = child.stdin.take() {
            let _ = input.write_all(b"shutdown\n");
            let _ = input.flush();
        }
        let deadline = Instant::now() + grace;
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(30));
        }
        kill_owned(&mut child, self.job.as_ref());
    }
}
impl Drop for Service {
    fn drop(&mut self) {
        self.shutdown();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accepts_only_the_owned_process_and_an_actual_port() {
        assert_eq!(
            ready_url(r#"{"port":12345,"pid":42,"instance_id":"fixture"}"#, 42).unwrap(),
            "http://127.0.0.1:12345"
        );
        assert_eq!(
            ready_url(
                r#"{"port":12345,"pid":43,"supervisor_pid":42,"instance_id":"frozen-fixture"}"#,
                42
            )
            .unwrap(),
            "http://127.0.0.1:12345"
        );
        for line in [
            r#"{"port":1234,"pid":0,"supervisor_pid":42,"instance_id":"fixture"}"#,
            r#"{"port":1234,"pid":43,"supervisor_pid":41,"instance_id":"fixture"}"#,
            r#"{"port":0,"pid":42,"instance_id":"fixture"}"#,
            r#"{"port":1234,"pid":43,"instance_id":"fixture"}"#,
            r#"{"port":1234,"pid":42}"#,
            r#"{"port":65536,"pid":42,"instance_id":"fixture"}"#,
            "not json",
        ] {
            assert!(ready_url(line, 42).is_err());
        }
    }
}

#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    #[test]
    fn shutdown_allows_bounded_native_cleanup_before_killing_child() {
        let mut command = if cfg!(windows) {
            // cmd.exe starts in milliseconds; powershell.exe cold starts on CI runners exceeded the
            // 20 s grace and made this test intermittent. Same contract: read one line, ~3 s cleanup, exit 0.
            let mut cmd = Command::new("cmd.exe");
            cmd.args(["/D", "/C", "set /p message= & ping -n 4 127.0.0.1 >nul & exit /b 0"]);
            cmd
        } else {
            let mut cmd = Command::new("sh");
            cmd.args(["-c", "read message; sleep 3; exit 0"]);
            cmd
        };
        command.stdin(Stdio::piped());
        let mut service = Service::from_child(command.spawn().unwrap(), "fixture".into());
        service.shutdown();
        assert!(service.child.lock().unwrap().try_wait().unwrap().unwrap().success());
    }

    #[cfg(unix)]
    #[test]
    fn forced_shutdown_kills_the_whole_owned_process_group() {
        let marker = std::env::temp_dir().join(format!("aitb-l3-{}", std::process::id()));
        let mut command = Command::new("sh");
        // Like the PyInstaller bootloader: a forked worker that ignores TERM and keeps running.
        command.args(["-c", &format!("(trap '' TERM; exec sleep 60) & echo $! > '{}'; wait", marker.display())]);
        command.stdin(Stdio::piped());
        std::os::unix::process::CommandExt::process_group(&mut command, 0);
        let mut service = Service::from_child(command.spawn().unwrap(), "fixture".into());
        let deadline = Instant::now() + Duration::from_secs(5);
        while !marker.is_file() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(20));
        }
        let worker = std::fs::read_to_string(&marker).unwrap().trim().to_string();
        let _ = std::fs::remove_file(&marker);
        service.shutdown_within(Duration::from_millis(300));
        thread::sleep(Duration::from_millis(200));
        let alive = Command::new("kill").args(["-0", &worker]).status().unwrap().success();
        assert!(!alive, "worker {worker} survived the forced shutdown");
    }

    #[cfg(windows)]
    #[test]
    fn forced_shutdown_terminates_the_whole_windows_job() {
        // A sidecar that starts its own child (like PyInstaller's worker) and never exits.
        fn waitfor_running() -> bool {
            let out = Command::new("tasklist")
                .args(["/FI", "IMAGENAME eq waitfor.exe", "/NH"])
                .output()
                .unwrap();
            String::from_utf8_lossy(&out.stdout).to_lowercase().contains("waitfor.exe")
        }
        assert!(!waitfor_running(), "precondition: no waitfor.exe already running");
        let mut command = Command::new("cmd.exe");
        command.args(["/D", "/C", "start /B waitfor /T 120 aitbjobprobe & ping -n 120 127.0.0.1 >nul"]);
        command.stdin(Stdio::piped());
        let mut service = Service::from_child(command.spawn().unwrap(), "fixture".into());
        assert!(service.job.is_some(), "sidecar must be inside a job object");
        let deadline = Instant::now() + Duration::from_secs(10);
        while !waitfor_running() && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(100));
        }
        assert!(waitfor_running(), "grandchild started");
        service.shutdown_within(Duration::from_millis(300));
        thread::sleep(Duration::from_millis(500));
        assert!(!waitfor_running(), "grandchild survived the forced shutdown");
    }

    #[test]
    fn reports_owned_child_exit_after_handshake() {
        let mut command = if cfg!(windows) {
            let mut cmd = Command::new("cmd");
            cmd.args(["/C", "exit", "0"]);
            cmd
        } else {
            let mut cmd = Command::new("sh");
            cmd.args(["-c", "exit 0"]);
            cmd
        };
        let service = Service::from_child(command.spawn().unwrap(), "fixture".into());
        let (send, receive) = mpsc::channel();
        service.monitor(move || {
            let _ = send.send(());
        });
        receive
            .recv_timeout(Duration::from_secs(3))
            .expect("Child exit must be reported");
    }
}
