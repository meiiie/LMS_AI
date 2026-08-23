use serde::{Deserialize, Serialize};
#[cfg(windows)]
use std::collections::HashSet;
#[cfg(windows)]
use std::ffi::OsString;
#[cfg(unix)]
use std::fs::{File, OpenOptions};
use std::io::{self, Read};
#[cfg(unix)]
use std::io::{Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
#[cfg(windows)]
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};
#[cfg(unix)]
use uuid::Uuid;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
const PROBE_TIMEOUT: Duration = Duration::from_secs(3);
const PROCESS_TERMINATION_TIMEOUT: Duration = Duration::from_secs(2);
#[cfg(windows)]
const PROBE_READER_DRAIN_TIMEOUT: Duration = Duration::from_secs(1);
const PROCESS_POLL_INTERVAL: Duration = Duration::from_millis(25);
const MAX_PROBE_OUTPUT_BYTES: usize = 64 * 1024;

struct ProbeOutput {
    status: ExitStatus,
    stdout: Vec<u8>,
}

#[cfg(unix)]
struct ProbeCapture {
    path: PathBuf,
    file: Option<File>,
}

#[cfg(unix)]
impl ProbeCapture {
    fn create() -> io::Result<Self> {
        let path = std::env::temp_dir().join(format!("wiii-neko-probe-{}.tmp", Uuid::new_v4()));
        let mut options = OpenOptions::new();
        options.create_new(true).read(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            // Provider version/profile output may expose local configuration.
            // Do not inherit a permissive process umask for this capture file.
            options.mode(0o600);
        }
        let file = options.open(&path)?;
        Ok(Self {
            path,
            file: Some(file),
        })
    }

    fn stdio(&self) -> io::Result<Stdio> {
        self.file
            .as_ref()
            .ok_or_else(|| io::Error::other("provider probe capture is closed"))?
            .try_clone()
            .map(Stdio::from)
    }

    fn read_bounded(&mut self) -> io::Result<Vec<u8>> {
        let file = self
            .file
            .as_mut()
            .ok_or_else(|| io::Error::other("provider probe capture is closed"))?;
        file.seek(SeekFrom::Start(0))?;
        let mut captured = Vec::new();
        file.take(MAX_PROBE_OUTPUT_BYTES as u64)
            .read_to_end(&mut captured)?;
        Ok(captured)
    }

    fn len(&self) -> io::Result<u64> {
        self.file
            .as_ref()
            .ok_or_else(|| io::Error::other("provider probe capture is closed"))?
            .metadata()
            .map(|metadata| metadata.len())
    }

    fn truncate_to_limit(&mut self) {
        if let Some(file) = self.file.as_mut() {
            let _ = file.set_len(MAX_PROBE_OUTPUT_BYTES as u64);
        }
    }
}

#[cfg(unix)]
impl Drop for ProbeCapture {
    fn drop(&mut self) {
        self.file.take();
        let _ = std::fs::remove_file(&self.path);
    }
}

fn probe_failure_after_cleanup(child: &mut Child, original: io::Error) -> io::Error {
    match terminate_child_tree(child) {
        Ok(()) => original,
        Err(cleanup) => io::Error::other(format!(
            "{original}; provider probe process-tree termination was not proven: {cleanup}"
        )),
    }
}

/// Unix discovery uses an owner-only file plus an inherited kernel file-size
/// limit. The file avoids a reader thread that can outlive a broken descendant
/// holding stdout open, and only a bounded prefix is returned.
#[cfg(unix)]
fn run_probe(mut command: Command) -> io::Result<ProbeOutput> {
    let mut capture = ProbeCapture::create()?;
    command
        .stdin(Stdio::null())
        .stdout(capture.stdio()?)
        .stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        // Provider probes are read-only discovery calls. Apply an inherited
        // kernel file-size ceiling so a broken producer or descendant cannot
        // allocate unbounded capture storage between monitor polls.
        unsafe {
            command.pre_exec(|| {
                let limit = libc::rlimit {
                    rlim_cur: MAX_PROBE_OUTPUT_BYTES as libc::rlim_t,
                    rlim_max: MAX_PROBE_OUTPUT_BYTES as libc::rlim_t,
                };
                if libc::setrlimit(libc::RLIMIT_FSIZE, &limit) == 0 {
                    Ok(())
                } else {
                    Err(io::Error::last_os_error())
                }
            });
        }
    }
    hidden(&mut command);
    let mut child = command.spawn()?;
    let deadline = Instant::now() + PROBE_TIMEOUT;
    let status = loop {
        let capture_len = match capture.len() {
            Ok(capture_len) => capture_len,
            Err(error) => {
                return Err(probe_failure_after_cleanup(&mut child, error));
            }
        };
        if capture_len > MAX_PROBE_OUTPUT_BYTES as u64 {
            capture.truncate_to_limit();
            let error = io::Error::new(
                io::ErrorKind::InvalidData,
                "provider probe exceeded the output limit",
            );
            return Err(probe_failure_after_cleanup(&mut child, error));
        }
        let child_status = match child.try_wait() {
            Ok(child_status) => child_status,
            Err(error) => {
                return Err(probe_failure_after_cleanup(&mut child, error));
            }
        };
        if let Some(status) = child_status {
            // A probe is not allowed to leave descendants behind. On Unix the
            // dedicated process group remains addressable after its leader
            // exits. Cleanup is checked before the output becomes trusted.
            terminate_child_tree(&mut child)?;
            break status;
        }
        if Instant::now() >= deadline {
            let error = io::Error::new(io::ErrorKind::TimedOut, "provider probe timed out");
            return Err(probe_failure_after_cleanup(&mut child, error));
        }
        thread::sleep(PROCESS_POLL_INTERVAL);
    };
    let stdout = capture.read_bounded()?;
    Ok(ProbeOutput { status, stdout })
}

/// Windows discovery uses a bounded anonymous-pipe consumer instead of a
/// capture file. The reader closes the pipe after MAX+1 bytes, so a producer
/// cannot allocate unbounded disk space between monitor polls. Process-tree
/// cleanup is checked before any output is trusted.
#[cfg(windows)]
fn run_probe(mut command: Command) -> io::Result<ProbeOutput> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    hidden(&mut command);
    let mut child = command.spawn()?;
    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => {
            let error = io::Error::other("provider probe stdout is unavailable");
            return Err(probe_failure_after_cleanup(&mut child, error));
        }
    };
    let (sender, receiver) = mpsc::sync_channel(1);
    if let Err(error) = thread::Builder::new()
        .name("neko-probe-output".into())
        .spawn(move || {
            let mut captured = Vec::new();
            let result = stdout
                .take((MAX_PROBE_OUTPUT_BYTES + 1) as u64)
                .read_to_end(&mut captured)
                .map(|_| captured);
            let _ = sender.send(result);
        })
    {
        return Err(probe_failure_after_cleanup(&mut child, error));
    }

    let deadline = Instant::now() + PROBE_TIMEOUT;
    let mut captured = None;
    let status = loop {
        if captured.is_none() {
            match receiver.try_recv() {
                Ok(Ok(output)) if output.len() > MAX_PROBE_OUTPUT_BYTES => {
                    let error = io::Error::new(
                        io::ErrorKind::InvalidData,
                        "provider probe exceeded the output limit",
                    );
                    return Err(probe_failure_after_cleanup(&mut child, error));
                }
                Ok(Ok(output)) => captured = Some(output),
                Ok(Err(error)) => {
                    return Err(probe_failure_after_cleanup(&mut child, error));
                }
                Err(mpsc::TryRecvError::Disconnected) => {
                    let error = io::Error::new(
                        io::ErrorKind::BrokenPipe,
                        "provider probe output reader disconnected",
                    );
                    return Err(probe_failure_after_cleanup(&mut child, error));
                }
                Err(mpsc::TryRecvError::Empty) => {}
            }
        }

        match child.try_wait() {
            Ok(Some(status)) => {
                terminate_child_tree(&mut child)?;
                break status;
            }
            Ok(None) => {}
            Err(error) => return Err(probe_failure_after_cleanup(&mut child, error)),
        }
        if Instant::now() >= deadline {
            let error = io::Error::new(io::ErrorKind::TimedOut, "provider probe timed out");
            return Err(probe_failure_after_cleanup(&mut child, error));
        }
        thread::sleep(PROCESS_POLL_INTERVAL);
    };

    let stdout = match captured {
        Some(output) => output,
        None => match receiver.recv_timeout(PROBE_READER_DRAIN_TIMEOUT) {
            Ok(Ok(output)) => output,
            Ok(Err(error)) => return Err(error),
            Err(error) => {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    format!("provider probe output did not close after termination: {error}"),
                ));
            }
        },
    };
    if stdout.len() > MAX_PROBE_OUTPUT_BYTES {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "provider probe exceeded the output limit",
        ));
    }
    Ok(ProbeOutput { status, stdout })
}

fn candidate_paths(candidate: &str) -> Vec<PathBuf> {
    let candidate = Path::new(candidate);
    if candidate.is_absolute() || candidate.components().count() > 1 {
        return std::fs::canonicalize(candidate).into_iter().collect();
    }
    let Some(path) = std::env::var_os("PATH") else {
        return Vec::new();
    };
    #[cfg(windows)]
    let names = {
        let mut names = vec![candidate.as_os_str().to_os_string()];
        if candidate.extension().is_none() {
            let extensions = std::env::var_os("PATHEXT")
                .unwrap_or_else(|| OsString::from(".COM;.EXE;.BAT;.CMD"));
            names.extend(
                extensions
                    .to_string_lossy()
                    .split(';')
                    .filter(|extension| !extension.is_empty())
                    .map(|extension| {
                        let mut name = candidate.as_os_str().to_os_string();
                        name.push(extension);
                        name
                    }),
            );
        }
        names
    };
    #[cfg(not(windows))]
    let names = vec![candidate.as_os_str().to_os_string()];
    let mut resolved = Vec::new();
    for directory in std::env::split_paths(&path) {
        for name in &names {
            if let Ok(path) = std::fs::canonicalize(directory.join(name)) {
                if !resolved.contains(&path) {
                    resolved.push(path);
                }
            }
        }
    }
    resolved
}

pub(crate) fn hidden(command: &mut Command) -> &mut Command {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
    }
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    command
}

fn reap_child_before(child: &mut Child, deadline: Instant) -> io::Result<()> {
    loop {
        match child.try_wait()? {
            Some(_) => return Ok(()),
            None if Instant::now() >= deadline => {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "provider process leader did not reap before the termination deadline",
                ));
            }
            None => thread::sleep(PROCESS_POLL_INTERVAL),
        }
    }
}

#[cfg(windows)]
fn windows_process_snapshot() -> io::Result<Vec<(u32, u32)>> {
    use windows_sys::Win32::Foundation::{
        CloseHandle, GetLastError, ERROR_NO_MORE_FILES, INVALID_HANDLE_VALUE,
    };
    use windows_sys::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
        TH32CS_SNAPPROCESS,
    };

    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    let mut entries = Vec::new();
    let mut entry = PROCESSENTRY32W {
        dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32,
        ..Default::default()
    };
    let first = unsafe { Process32FirstW(snapshot, &mut entry) };
    if first == 0 {
        let code = unsafe { GetLastError() };
        unsafe { CloseHandle(snapshot) };
        return if code == ERROR_NO_MORE_FILES {
            Ok(entries)
        } else {
            Err(io::Error::from_raw_os_error(code as i32))
        };
    }
    loop {
        entries.push((entry.th32ProcessID, entry.th32ParentProcessID));
        if unsafe { Process32NextW(snapshot, &mut entry) } == 0 {
            let code = unsafe { GetLastError() };
            unsafe { CloseHandle(snapshot) };
            return if code == ERROR_NO_MORE_FILES {
                Ok(entries)
            } else {
                Err(io::Error::from_raw_os_error(code as i32))
            };
        }
    }
}

#[cfg(windows)]
fn windows_live_descendants(root_pid: u32, known: &mut HashSet<u32>) -> io::Result<Vec<u32>> {
    let entries = windows_process_snapshot()?;
    known.insert(root_pid);
    loop {
        let mut changed = false;
        for (pid, parent) in &entries {
            if *pid != root_pid && known.contains(parent) && known.insert(*pid) {
                changed = true;
            }
        }
        if !changed {
            break;
        }
    }
    Ok(entries
        .into_iter()
        .map(|(pid, _)| pid)
        .filter(|pid| *pid != root_pid && known.contains(pid))
        .collect())
}

#[cfg(windows)]
fn terminate_windows_process(pid: u32) -> io::Result<()> {
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, ERROR_INVALID_PARAMETER};
    use windows_sys::Win32::System::Threading::{OpenProcess, TerminateProcess, PROCESS_TERMINATE};

    let handle = unsafe { OpenProcess(PROCESS_TERMINATE, 0, pid) };
    if handle.is_null() {
        let code = unsafe { GetLastError() };
        return if code == ERROR_INVALID_PARAMETER {
            Ok(())
        } else {
            Err(io::Error::from_raw_os_error(code as i32))
        };
    }
    let terminated = unsafe { TerminateProcess(handle, 1) };
    let error = (terminated == 0).then(io::Error::last_os_error);
    unsafe { CloseHandle(handle) };
    error.map_or(Ok(()), Err)
}

#[cfg(windows)]
pub(crate) fn terminate_child_tree(child: &mut Child) -> io::Result<()> {
    let root_pid = child.id();
    let deadline = Instant::now() + PROCESS_TERMINATION_TIMEOUT;
    if child.try_wait()?.is_none() {
        child.kill()?;
    }
    reap_child_before(child, deadline)?;

    // A terminated Windows parent can disappear before taskkill can address
    // its tree. Preserve every discovered parent PID and repeatedly snapshot
    // descendants until none remain; this also catches a child spawned while
    // an earlier snapshot was being terminated.
    let mut known = HashSet::from([root_pid]);
    loop {
        let descendants = windows_live_descendants(root_pid, &mut known)?;
        if descendants.is_empty() {
            return Ok(());
        }
        for pid in descendants {
            terminate_windows_process(pid)?;
        }
        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "provider process descendants did not terminate before the deadline",
            ));
        }
        thread::sleep(PROCESS_POLL_INTERVAL);
    }
}

#[cfg(unix)]
pub(crate) fn terminate_child_tree(child: &mut Child) -> io::Result<()> {
    // All approved provider commands are placed in a dedicated process group
    // by hidden(). A negative PID targets that complete group. ESRCH is the
    // only safe non-success result: it proves the isolated group is absent.
    let result = unsafe { libc::kill(-(child.id() as i32), libc::SIGKILL) };
    if result != 0 {
        let error = io::Error::last_os_error();
        if error.raw_os_error() != Some(libc::ESRCH) {
            return Err(error);
        }
    }
    let deadline = Instant::now() + PROCESS_TERMINATION_TIMEOUT;
    reap_child_before(child, deadline)?;
    loop {
        let group = unsafe { libc::kill(-(child.id() as i32), 0) };
        if group != 0 {
            let error = io::Error::last_os_error();
            if error.raw_os_error() == Some(libc::ESRCH) {
                return Ok(());
            }
            return Err(error);
        }
        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "provider process group did not disappear before the deadline",
            ));
        }
        thread::sleep(PROCESS_POLL_INTERVAL);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProviderDefinition {
    pub id: &'static str,
    pub name: &'static str,
    windows_candidates: &'static [&'static str],
    unix_candidates: &'static [&'static str],
    version_arg: &'static str,
    launch_args: &'static [&'static str],
    profile_argument: Option<&'static str>,
}

impl ProviderDefinition {
    fn candidates(self) -> &'static [&'static str] {
        if cfg!(windows) {
            self.windows_candidates
        } else {
            self.unix_candidates
        }
    }

    pub fn launch_args(self, profile_id: Option<&str>) -> Result<Vec<String>, String> {
        let mut args = self
            .launch_args
            .iter()
            .map(|value| (*value).to_string())
            .collect::<Vec<_>>();
        if let Some(profile_id) = profile_id {
            let flag = self
                .profile_argument
                .ok_or_else(|| format!("provider '{}' does not support profiles", self.id))?;
            validate_profile_id(profile_id)?;
            args.push(flag.to_string());
            args.push(profile_id.to_string());
        }
        Ok(args)
    }

    pub fn supports_profiles(self) -> bool {
        self.profile_argument.is_some()
    }
}

const PROVIDERS: &[ProviderDefinition] = &[
    ProviderDefinition {
        id: "neko",
        name: "Neko Core",
        windows_candidates: &["neko.exe", "neko.cmd", "neko"],
        unix_candidates: &["neko"],
        version_arg: "--version",
        launch_args: &["acp"],
        profile_argument: Some("--profile"),
    },
    ProviderDefinition {
        id: "gemini",
        name: "Gemini CLI",
        windows_candidates: &["gemini.cmd", "gemini"],
        unix_candidates: &["gemini"],
        version_arg: "--version",
        launch_args: &["--experimental-acp"],
        profile_argument: None,
    },
    ProviderDefinition {
        id: "codex",
        name: "Codex",
        windows_candidates: &["codex.exe", "codex.cmd", "codex"],
        unix_candidates: &["codex"],
        version_arg: "--version",
        launch_args: &["app-server"],
        profile_argument: None,
    },
];

pub fn definition(provider_id: &str) -> Option<ProviderDefinition> {
    PROVIDERS
        .iter()
        .copied()
        .find(|provider| provider.id == provider_id)
}

#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct AgentInfo {
    pub id: String,
    pub name: String,
    pub version: Option<String>,
    pub found: bool,
    pub supports_profiles: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedProvider {
    pub definition: ProviderDefinition,
    pub program: PathBuf,
    pub version: Option<String>,
}

fn probe_definition(provider: ProviderDefinition) -> Option<ResolvedProvider> {
    for candidate in provider.candidates() {
        for program in candidate_paths(candidate) {
            let mut command = Command::new(&program);
            command.arg(provider.version_arg);
            if let Ok(output) = run_probe(command) {
                if output.status.success() {
                    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
                    return Some(ResolvedProvider {
                        definition: provider,
                        program,
                        version: (!version.is_empty()).then_some(version),
                    });
                }
            }
        }
    }
    None
}

pub fn resolve(provider_id: &str) -> Result<ResolvedProvider, String> {
    let provider =
        definition(provider_id).ok_or_else(|| format!("unknown Neko provider '{provider_id}'"))?;
    probe_definition(provider)
        .ok_or_else(|| format!("provider '{}' is not available on this host", provider.name))
}

pub fn list() -> Vec<AgentInfo> {
    PROVIDERS
        .iter()
        .copied()
        .map(|provider| {
            let resolved = probe_definition(provider);
            AgentInfo {
                id: provider.id.to_string(),
                name: provider.name.to_string(),
                version: resolved.as_ref().and_then(|item| item.version.clone()),
                found: resolved.is_some(),
                supports_profiles: provider.supports_profiles(),
            }
        })
        .collect()
}

#[derive(Deserialize, Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AgentProfile {
    pub id: String,
    pub provider: String,
    pub model: Option<String>,
    pub active: bool,
}

pub fn validate_profile_id(profile_id: &str) -> Result<(), String> {
    if profile_id.is_empty()
        || profile_id.len() > 64
        || profile_id.starts_with('-')
        || !profile_id
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'-' | b'_' | b'.'))
    {
        return Err("invalid provider profile identity".to_string());
    }
    Ok(())
}

pub fn parse_neko_profiles(output: &str) -> Vec<AgentProfile> {
    output
        .lines()
        .filter_map(|line| {
            let trimmed = line.trim_start();
            let (active, body) = if let Some(rest) = trimmed.strip_prefix("* ") {
                (true, rest)
            } else {
                (false, trimmed)
            };
            let (id, details) = body.split_once(':')?;
            let id = id.trim();
            if id.is_empty()
                || id.eq_ignore_ascii_case(
                    "profiles (select with --profile name, neko_profile, or active_profile)",
                )
            {
                return None;
            }
            let mut provider = None;
            let mut model = None;
            for field in details.split_whitespace() {
                if let Some(value) = field.strip_prefix("provider=") {
                    if value != "?" && !value.is_empty() {
                        provider = Some(value.to_string());
                    }
                } else if let Some(value) = field.strip_prefix("model=") {
                    if value != "-" && !value.is_empty() {
                        model = Some(value.to_string());
                    }
                }
            }
            Some(AgentProfile {
                id: id.to_string(),
                provider: provider?,
                model,
                active,
            })
        })
        .collect()
}

pub fn profiles(provider_id: &str, cwd: &str) -> Result<Vec<AgentProfile>, String> {
    let provider =
        definition(provider_id).ok_or_else(|| format!("unknown Neko provider '{provider_id}'"))?;
    if !provider.supports_profiles() {
        return Ok(Vec::new());
    }
    let cwd_path = std::path::Path::new(cwd);
    if !cwd_path.is_absolute() || !cwd_path.is_dir() {
        return Err("workspace must be an existing absolute directory".to_string());
    }
    let resolved = resolve(provider_id)?;
    let mut command = Command::new(&resolved.program);
    command.arg("profiles").current_dir(cwd_path);
    let output = run_probe(command).map_err(|error| format!("profile probe failed: {error}"))?;
    if !output.status.success() {
        return Err(format!("profile probe exited with {}", output.status));
    }
    Ok(parse_neko_profiles(&String::from_utf8_lossy(
        &output.stdout,
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registry_freezes_approved_launch_contracts() {
        assert_eq!(
            definition("neko")
                .unwrap()
                .launch_args(Some("chatgpt"))
                .unwrap(),
            ["acp", "--profile", "chatgpt"]
        );
        assert_eq!(
            definition("gemini").unwrap().launch_args(None).unwrap(),
            ["--experimental-acp"]
        );
        assert_eq!(
            definition("codex").unwrap().launch_args(None).unwrap(),
            ["app-server"]
        );
        assert!(definition("unknown").is_none());
    }

    #[test]
    fn profile_identity_cannot_become_an_option() {
        assert!(validate_profile_id("chatgpt-5.6").is_ok());
        assert!(validate_profile_id("--help").is_err());
        assert!(validate_profile_id("name with spaces").is_err());
        assert!(definition("codex").unwrap().launch_args(Some("x")).is_err());
    }

    #[test]
    fn parses_profile_provider_model_and_active_marker() {
        let output = r#"Profiles (select with --profile NAME, NEKO_PROFILE, or active_profile):
 * chatgpt: provider=chatgpt base_url=https://example.test model=gpt-5.6-luna
   local: provider=openai_compat base_url=http://127.0.0.1:8080/v1 model=local-model
   openrouter: provider=openai_compat base_url=https://openrouter.ai/api/v1 model=-
 malformed line
"#;
        let profiles = parse_neko_profiles(output);
        assert_eq!(profiles.len(), 3);
        assert_eq!(profiles[0].id, "chatgpt");
        assert_eq!(profiles[0].provider, "chatgpt");
        assert_eq!(profiles[0].model.as_deref(), Some("gpt-5.6-luna"));
        assert!(profiles[0].active);
        assert_eq!(profiles[2].model, None);
        assert!(!profiles[2].active);
    }

    #[test]
    fn approved_launch_paths_are_canonical_and_absolute() {
        let current = std::env::current_exe().unwrap();
        let resolved = candidate_paths(current.to_str().unwrap());
        assert_eq!(resolved.len(), 1);
        assert!(resolved[0].is_absolute());
        assert_eq!(resolved[0], std::fs::canonicalize(current).unwrap());
    }

    #[test]
    fn probe_capture_never_returns_more_than_the_output_budget() {
        #[cfg(windows)]
        let command = {
            let mut command = Command::new("powershell.exe");
            command.args([
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Console]::Out.Write('x' * 131072)",
            ]);
            command
        };
        #[cfg(unix)]
        let command = {
            let mut command = Command::new("sh");
            command.args(["-c", "dd if=/dev/zero bs=131072 count=1 2>/dev/null"]);
            command
        };

        match run_probe(command) {
            Ok(output) => assert!(output.stdout.len() <= MAX_PROBE_OUTPUT_BYTES),
            Err(error) => assert_eq!(error.kind(), io::ErrorKind::InvalidData),
        }
    }

    #[test]
    fn process_tree_termination_returns_a_verified_result() {
        #[cfg(windows)]
        let mut command = {
            let mut command = Command::new("powershell.exe");
            command.args([
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Start-Sleep -Seconds 30",
            ]);
            command
        };
        #[cfg(unix)]
        let mut command = {
            let mut command = Command::new("sh");
            command.args(["-c", "sleep 30"]);
            command
        };
        hidden(&mut command);
        let mut child = command.spawn().unwrap();

        terminate_child_tree(&mut child).unwrap();
        assert!(child.try_wait().unwrap().is_some());
    }

    #[cfg(windows)]
    #[test]
    fn process_tree_termination_finds_a_descendant_after_its_leader_exits() {
        let marker =
            std::env::temp_dir().join(format!("wiii-neko-descendant-{}.pid", uuid::Uuid::new_v4()));
        let escaped_marker = marker.to_string_lossy().replace('\'', "''");
        let script = format!(
            "$p = Start-Process powershell.exe -WindowStyle Hidden -PassThru \
             -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-Command', \
             'Start-Sleep -Seconds 30'); \
             [IO.File]::WriteAllText('{escaped_marker}', [string]$p.Id)"
        );
        let mut command = Command::new("powershell.exe");
        command.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            &script,
        ]);
        hidden(&mut command);
        let mut child = command.spawn().unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while (!marker.exists() || child.try_wait().unwrap().is_none()) && Instant::now() < deadline
        {
            thread::sleep(PROCESS_POLL_INTERVAL);
        }
        let descendant_pid: u32 = std::fs::read_to_string(&marker)
            .unwrap()
            .trim()
            .parse()
            .unwrap();

        terminate_child_tree(&mut child).unwrap();

        assert!(!windows_process_snapshot()
            .unwrap()
            .into_iter()
            .any(|(pid, _)| pid == descendant_pid));
        let _ = std::fs::remove_file(marker);
    }

    #[cfg(unix)]
    #[test]
    fn probe_capture_is_owner_only() {
        use std::os::unix::fs::PermissionsExt;

        let capture = ProbeCapture::create().unwrap();
        let mode = std::fs::metadata(&capture.path)
            .unwrap()
            .permissions()
            .mode()
            & 0o777;
        assert_eq!(mode, 0o600);
    }
}
