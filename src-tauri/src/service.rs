use serde::Deserialize;
use std::{
    io::{BufRead, BufReader, Read, Write},
    path::Path,
    process::{Child, Command, Stdio},
    sync::mpsc,
    thread,
    time::{Duration, Instant},
};

#[derive(Deserialize)]
struct Readiness {
    port: u16,
    pid: u32,
    instance_id: String,
}

fn ready_url(line: &str, owned_pid: u32) -> Result<String, String> {
    let ready: Readiness =
        serde_json::from_str(line).map_err(|_| "Handshake del servizio non valido.")?;
    if ready.port == 0 || ready.pid != owned_pid || ready.instance_id.is_empty() {
        return Err("Il servizio non corrisponde al processo avviato.".into());
    }
    Ok(format!("http://127.0.0.1:{}", ready.port))
}

pub struct Service {
    child: Child,
    pub url: String,
}

impl Service {
    pub fn start(binary: &Path, ui: &Path, data: &Path) -> Result<Self, String> {
        if !ui.join("index.html").is_file() {
            return Err("Asset React mancanti: eseguire la build del frontend.".into());
        }
        std::fs::create_dir_all(data).map_err(|_| "Directory dati dell'app non disponibile.")?;
        let mut child = Command::new(binary)
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
        let pid = child.id();
        let stdout = match child.stdout.take() {
            Some(stdout) => stdout,
            None => {
                let _ = child.kill();
                let _ = child.wait();
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
        match receive.recv_timeout(Duration::from_secs(15)) {
            Ok(Ok(url)) => Ok(Self { child, url }),
            result => {
                let _ = child.kill();
                let _ = child.wait();
                Err(match result {
                    Ok(Err(error)) => error,
                    _ => "Timeout nell'avvio del servizio locale.".into(),
                })
            }
        }
    }

    pub fn shutdown(&mut self) {
        if let Some(mut input) = self.child.stdin.take() {
            let _ = input.write_all(b"shutdown\n");
            let _ = input.flush();
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(30));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
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
        for line in [
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
