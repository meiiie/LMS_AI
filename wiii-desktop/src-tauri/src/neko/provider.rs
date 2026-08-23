use serde::{Deserialize, Serialize};
#[cfg(windows)]
use std::ffi::OsString;
use std::fmt;
use std::io;
#[cfg(windows)]
use std::io::Read;
use std::path::{Path, PathBuf};
#[cfg(windows)]
use std::process::Stdio;
use std::process::{Child, Command, ExitStatus};
#[cfg(windows)]
use std::sync::mpsc;
#[cfg(windows)]
use std::thread;
#[cfg(windows)]
use std::time::{Duration, Instant};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(windows)]
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
#[cfg(windows)]
const CREATE_SUSPENDED: u32 = 0x0000_0004;
#[cfg(windows)]
const PROBE_TIMEOUT: Duration = Duration::from_secs(3);
#[cfg(windows)]
const PROCESS_TERMINATION_TIMEOUT: Duration = Duration::from_secs(2);
#[cfg(windows)]
const PROBE_READER_DRAIN_TIMEOUT: Duration = Duration::from_secs(1);
#[cfg(windows)]
const PROCESS_POLL_INTERVAL: Duration = Duration::from_millis(25);
#[cfg(windows)]
const MAX_PROBE_OUTPUT_BYTES: usize = 64 * 1024;

struct ProbeOutput {
    status: ExitStatus,
    stdout: Vec<u8>,
}

/// An approved provider process plus its non-escapable host containment.
/// Windows uses a Job Object. Unix hosts reject the launch before spawn until
/// Wiii has an approved boundary that the same-UID provider cannot migrate out
/// of; a process group or writable cgroup leaf is not treated as proof.
pub(crate) struct OwnedChild {
    pub(crate) child: Child,
    #[cfg(windows)]
    job: WindowsJob,
}

/// Distinguishes a launch rejection that leaves no child behind from a
/// post-spawn failure whose cleanup was either proven or uncertain. Callers
/// must retain the proven terminal fact and must never turn an uncertain
/// cleanup into permission to retry the side effect.
#[derive(Debug)]
pub(crate) struct SpawnOwnedError {
    error: io::Error,
    disposition: SpawnFailureDisposition,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SpawnFailureDisposition {
    PreSpawn,
    PostSpawnCleanupProven,
    PostSpawnCleanupUnproven,
}

impl SpawnOwnedError {
    fn safe(error: io::Error) -> Self {
        Self {
            error,
            disposition: SpawnFailureDisposition::PreSpawn,
        }
    }

    fn after_proven_cleanup(error: io::Error) -> Self {
        Self {
            error,
            disposition: SpawnFailureDisposition::PostSpawnCleanupProven,
        }
    }

    fn after_unproven_cleanup(error: io::Error) -> Self {
        Self {
            error,
            disposition: SpawnFailureDisposition::PostSpawnCleanupUnproven,
        }
    }

    pub(crate) fn cleanup_unproven(&self) -> bool {
        self.disposition == SpawnFailureDisposition::PostSpawnCleanupUnproven
    }

    pub(crate) fn post_spawn_cleanup_proven(&self) -> bool {
        self.disposition == SpawnFailureDisposition::PostSpawnCleanupProven
    }

    #[cfg(test)]
    pub(crate) fn kind(&self) -> io::ErrorKind {
        self.error.kind()
    }
}

impl fmt::Display for SpawnOwnedError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.error.fmt(formatter)
    }
}

impl std::error::Error for SpawnOwnedError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(&self.error)
    }
}

impl From<io::Error> for SpawnOwnedError {
    fn from(error: io::Error) -> Self {
        Self::safe(error)
    }
}

#[cfg(windows)]
struct WindowsJob {
    // Store the owned kernel handle as its pointer-sized scalar representation
    // so the supervisor can move it between Rust worker threads. Windows
    // handles are thread-safe kernel object references; all access stays owned.
    handle: isize,
}

#[cfg(windows)]
impl WindowsJob {
    fn raw(&self) -> windows_sys::Win32::Foundation::HANDLE {
        self.handle as windows_sys::Win32::Foundation::HANDLE
    }
}

#[cfg(windows)]
impl Drop for WindowsJob {
    fn drop(&mut self) {
        if self.handle != 0 {
            unsafe {
                windows_sys::Win32::Foundation::CloseHandle(self.raw());
            }
        }
    }
}

#[cfg(windows)]
fn probe_failure_after_cleanup(child: &mut OwnedChild, original: io::Error) -> SpawnOwnedError {
    match terminate_child_tree(child) {
        Ok(()) => SpawnOwnedError::after_proven_cleanup(original),
        Err(cleanup) => SpawnOwnedError::after_unproven_cleanup(io::Error::other(format!(
            "{original}; provider probe process-tree termination was not proven: {cleanup}"
        ))),
    }
}

/// Unix provider discovery is staged behind the same non-escapable containment
/// primitive as provider execution. Do not probe by spawning an unowned child.
#[cfg(unix)]
fn run_probe(_command: Command) -> Result<ProbeOutput, SpawnOwnedError> {
    Err(SpawnOwnedError::safe(unix_containment_unavailable()))
}

/// Windows discovery uses a bounded anonymous-pipe consumer instead of a
/// capture file. The reader closes the pipe after MAX+1 bytes, so a producer
/// cannot allocate unbounded disk space between monitor polls. Process-tree
/// cleanup is checked before any output is trusted.
#[cfg(windows)]
fn run_probe(mut command: Command) -> Result<ProbeOutput, SpawnOwnedError> {
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = spawn_owned(&mut command)?;
    let stdout = match child.child.stdout.take() {
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

        match child.child.try_wait() {
            Ok(Some(status)) => {
                terminate_child_tree(&mut child).map_err(|cleanup| {
                    SpawnOwnedError::after_unproven_cleanup(io::Error::other(format!(
                        "provider probe leader exited but process-tree termination was not proven: {cleanup}"
                    )))
                })?;
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
            Ok(Err(error)) => return Err(SpawnOwnedError::after_proven_cleanup(error)),
            Err(error) => {
                return Err(SpawnOwnedError::after_proven_cleanup(io::Error::new(
                    io::ErrorKind::TimedOut,
                    format!("provider probe output did not close after termination: {error}"),
                )));
            }
        },
    };
    if stdout.len() > MAX_PROBE_OUTPUT_BYTES {
        return Err(SpawnOwnedError::after_proven_cleanup(io::Error::new(
            io::ErrorKind::InvalidData,
            "provider probe exceeded the output limit",
        )));
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

#[cfg(windows)]
fn create_windows_job() -> io::Result<WindowsJob> {
    use windows_sys::Win32::System::JobObjects::{
        CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
    if handle.is_null() {
        return Err(io::Error::last_os_error());
    }
    let job = WindowsJob {
        handle: handle as isize,
    };
    let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    let configured = unsafe {
        SetInformationJobObject(
            job.raw(),
            JobObjectExtendedLimitInformation,
            std::ptr::from_ref(&limits).cast(),
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    };
    if configured == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(job)
}

#[cfg(windows)]
fn resume_suspended_process(pid: u32) -> io::Result<()> {
    use windows_sys::Win32::Foundation::{
        CloseHandle, GetLastError, ERROR_NO_MORE_FILES, INVALID_HANDLE_VALUE,
    };
    use windows_sys::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
    };
    use windows_sys::Win32::System::Threading::{OpenThread, ResumeThread, THREAD_SUSPEND_RESUME};

    let snapshot = unsafe { CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0) };
    if snapshot == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    let mut entry = THREADENTRY32 {
        dwSize: std::mem::size_of::<THREADENTRY32>() as u32,
        ..Default::default()
    };
    let mut found = false;
    let mut current = unsafe { Thread32First(snapshot, &mut entry) };
    while current != 0 {
        if entry.th32OwnerProcessID == pid {
            let thread = unsafe { OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID) };
            if thread.is_null() {
                let error = io::Error::last_os_error();
                unsafe { CloseHandle(snapshot) };
                return Err(error);
            }
            let resumed = unsafe { ResumeThread(thread) };
            let resume_error = (resumed == u32::MAX).then(io::Error::last_os_error);
            unsafe { CloseHandle(thread) };
            if let Some(error) = resume_error {
                unsafe { CloseHandle(snapshot) };
                return Err(error);
            }
            found = true;
            break;
        }
        current = unsafe { Thread32Next(snapshot, &mut entry) };
    }
    let iteration_error = if !found && current == 0 {
        let code = unsafe { GetLastError() };
        (code != ERROR_NO_MORE_FILES).then(|| io::Error::from_raw_os_error(code as i32))
    } else {
        None
    };
    unsafe { CloseHandle(snapshot) };
    if let Some(error) = iteration_error {
        return Err(error);
    }
    if !found {
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            "suspended provider primary thread was not found",
        ));
    }
    Ok(())
}

pub(crate) fn spawn_owned(command: &mut Command) -> Result<OwnedChild, SpawnOwnedError> {
    #[cfg(windows)]
    {
        use std::os::windows::io::AsRawHandle;
        use std::os::windows::process::CommandExt;
        use windows_sys::Win32::System::JobObjects::{
            AssignProcessToJobObject, TerminateJobObject,
        };

        let job = create_windows_job()?;
        command.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_SUSPENDED);
        let mut child = command.spawn()?;
        let assigned = unsafe { AssignProcessToJobObject(job.raw(), child.as_raw_handle()) };
        if assigned == 0 {
            let error = io::Error::last_os_error();
            let termination = child.kill();
            let cleanup = finish_failed_spawn_cleanup(&mut child, termination);
            return Err(match cleanup {
                Ok(()) => SpawnOwnedError::after_proven_cleanup(error),
                Err(cleanup) => SpawnOwnedError::after_unproven_cleanup(spawn_cleanup_error(
                    error,
                    Err(cleanup),
                )),
            });
        }
        if let Err(error) = resume_suspended_process(child.id()) {
            let termination = if unsafe { TerminateJobObject(job.raw(), 1) } == 0 {
                Err(io::Error::last_os_error())
            } else {
                Ok(())
            };
            let cleanup = finish_failed_spawn_cleanup(&mut child, termination);
            return Err(match cleanup {
                Ok(()) => SpawnOwnedError::after_proven_cleanup(error),
                Err(cleanup) => SpawnOwnedError::after_unproven_cleanup(spawn_cleanup_error(
                    error,
                    Err(cleanup),
                )),
            });
        }
        Ok(OwnedChild { child, job })
    }
    #[cfg(unix)]
    {
        let _ = command;
        Err(SpawnOwnedError::safe(unix_containment_unavailable()))
    }
}

#[cfg(windows)]
fn finish_failed_spawn_cleanup(child: &mut Child, termination: io::Result<()>) -> io::Result<()> {
    let reaped = reap_child_before(child, Instant::now() + PROCESS_TERMINATION_TIMEOUT);
    match (termination, reaped) {
        (_, Ok(())) => Ok(()),
        (Ok(()), Err(reap)) => Err(reap),
        (Err(termination), Err(reap)) => Err(io::Error::new(
            termination.kind(),
            format!("provider termination failed: {termination}; reap also failed: {reap}"),
        )),
    }
}

#[cfg(windows)]
fn spawn_cleanup_error(primary: io::Error, cleanup: io::Result<()>) -> io::Error {
    match cleanup {
        Ok(()) => primary,
        Err(cleanup) => io::Error::new(
            primary.kind(),
            format!("{primary}; suspended provider cleanup also failed: {cleanup}"),
        ),
    }
}

#[cfg(unix)]
fn unix_containment_unavailable() -> io::Error {
    io::Error::new(
        io::ErrorKind::Unsupported,
        "local Neko providers require non-escapable process containment; Unix execution is disabled until an approved primitive prevents same-UID migration",
    )
}

#[cfg(windows)]
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
pub(crate) fn terminate_child_tree(owned: &mut OwnedChild) -> io::Result<()> {
    use windows_sys::Win32::System::JobObjects::{
        JobObjectBasicAccountingInformation, QueryInformationJobObject, TerminateJobObject,
        JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    };

    let deadline = Instant::now() + PROCESS_TERMINATION_TIMEOUT;
    if unsafe { TerminateJobObject(owned.job.raw(), 1) } == 0 {
        return Err(io::Error::last_os_error());
    }
    reap_child_before(&mut owned.child, deadline)?;
    loop {
        let mut accounting = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION::default();
        let queried = unsafe {
            QueryInformationJobObject(
                owned.job.raw(),
                JobObjectBasicAccountingInformation,
                std::ptr::from_mut(&mut accounting).cast(),
                std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                std::ptr::null_mut(),
            )
        };
        if queried == 0 {
            return Err(io::Error::last_os_error());
        }
        if accounting.ActiveProcesses == 0 {
            return Ok(());
        }
        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "provider Job Object did not become empty before the deadline",
            ));
        }
        thread::sleep(PROCESS_POLL_INTERVAL);
    }
}

#[cfg(unix)]
pub(crate) fn terminate_child_tree(_owned: &mut OwnedChild) -> io::Result<()> {
    Err(io::Error::new(
        io::ErrorKind::Unsupported,
        "non-escapable provider containment is unavailable on this host",
    ))
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
#[serde(rename_all = "snake_case")]
pub enum AgentAvailability {
    Available,
    NotInstalled,
    HostUnsupported,
}

#[derive(Deserialize, Serialize, Clone, Debug, Eq, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct AgentInfo {
    pub id: String,
    pub name: String,
    pub version: Option<String>,
    pub found: bool,
    pub availability: AgentAvailability,
    pub supports_profiles: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResolvedProvider {
    pub definition: ProviderDefinition,
    pub program: PathBuf,
    pub version: Option<String>,
}

fn probe_definition(
    provider: ProviderDefinition,
) -> Result<Option<ResolvedProvider>, SpawnOwnedError> {
    for candidate in provider.candidates() {
        for program in candidate_paths(candidate) {
            let mut command = Command::new(&program);
            command.arg(provider.version_arg);
            match run_probe(command) {
                Ok(output) if output.status.success() => {
                    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
                    return Ok(Some(ResolvedProvider {
                        definition: provider,
                        program,
                        version: (!version.is_empty()).then_some(version),
                    }));
                }
                Err(error) if error.cleanup_unproven() || error.post_spawn_cleanup_proven() => {
                    return Err(error);
                }
                Ok(_) | Err(_) => {}
            }
        }
    }
    Ok(None)
}

fn host_supports_provider_containment() -> bool {
    cfg!(windows)
}

fn format_discovery_failure(provider_name: &str, error: &SpawnOwnedError) -> String {
    if error.cleanup_unproven() {
        format!("provider discovery cleanup could not be proven for '{provider_name}': {error}")
    } else if error.post_spawn_cleanup_proven() {
        format!(
            "provider discovery failed after process-tree cleanup was proven for '{provider_name}': {error}"
        )
    } else {
        format!("provider discovery failed before spawn for '{provider_name}': {error}")
    }
}

pub fn resolve(provider_id: &str) -> Result<ResolvedProvider, SpawnOwnedError> {
    let provider = definition(provider_id).ok_or_else(|| {
        SpawnOwnedError::safe(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("unknown Neko provider '{provider_id}'"),
        ))
    })?;
    #[cfg(unix)]
    {
        return Err(SpawnOwnedError::safe(unix_containment_unavailable()));
    }
    #[cfg(windows)]
    {
        probe_definition(provider)?.ok_or_else(|| {
            SpawnOwnedError::safe(io::Error::new(
                io::ErrorKind::NotFound,
                format!("provider '{}' is not available on this host", provider.name),
            ))
        })
    }
}

pub fn list() -> Result<Vec<AgentInfo>, String> {
    PROVIDERS
        .iter()
        .copied()
        .map(|provider| {
            let resolved = if host_supports_provider_containment() {
                probe_definition(provider)
                    .map_err(|error| format_discovery_failure(provider.name, &error))?
            } else {
                None
            };
            let availability = if !host_supports_provider_containment() {
                AgentAvailability::HostUnsupported
            } else if resolved.is_some() {
                AgentAvailability::Available
            } else {
                AgentAvailability::NotInstalled
            };
            Ok(AgentInfo {
                id: provider.id.to_string(),
                name: provider.name.to_string(),
                version: resolved.as_ref().and_then(|item| item.version.clone()),
                found: resolved.is_some(),
                availability,
                supports_profiles: provider.supports_profiles(),
            })
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
    let resolved = resolve(provider_id).map_err(|error| error.to_string())?;
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

    #[cfg(windows)]
    #[test]
    fn probe_capture_never_returns_more_than_the_output_budget() {
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

        match run_probe(command) {
            Ok(output) => assert!(output.stdout.len() <= MAX_PROBE_OUTPUT_BYTES),
            Err(error) => {
                assert_eq!(error.kind(), io::ErrorKind::InvalidData);
                assert!(error.post_spawn_cleanup_proven());
            }
        }
    }

    #[cfg(unix)]
    #[test]
    fn provider_probe_rejects_before_spawn_without_containment() {
        let mut command = Command::new("sh");
        command.args(["-c", "exit 99"]);

        let error = match run_probe(command) {
            Ok(_) => panic!("Unix provider probe unexpectedly spawned without containment"),
            Err(error) => error,
        };
        assert_eq!(error.kind(), io::ErrorKind::Unsupported);
    }

    #[test]
    fn post_spawn_cleanup_outcome_is_machine_readable() {
        let safe = SpawnOwnedError::safe(io::Error::other("spawn rejected"));
        let proven = SpawnOwnedError::after_proven_cleanup(io::Error::other("cleanup proven"));
        let uncertain =
            SpawnOwnedError::after_unproven_cleanup(io::Error::other("cleanup unproven"));
        assert!(!safe.cleanup_unproven());
        assert!(!safe.post_spawn_cleanup_proven());
        assert!(proven.post_spawn_cleanup_proven());
        assert!(!proven.cleanup_unproven());
        assert!(!uncertain.post_spawn_cleanup_proven());
        assert!(uncertain.cleanup_unproven());
    }

    #[test]
    fn probe_propagates_every_post_spawn_failure_disposition() {
        let pre_spawn = SpawnOwnedError::safe(io::Error::other("spawn rejected"));
        let proven = SpawnOwnedError::after_proven_cleanup(io::Error::other("cleanup proven"));
        let uncertain =
            SpawnOwnedError::after_unproven_cleanup(io::Error::other("cleanup unproven"));

        assert!(!(pre_spawn.cleanup_unproven() || pre_spawn.post_spawn_cleanup_proven()));
        assert!(proven.cleanup_unproven() || proven.post_spawn_cleanup_proven());
        assert!(uncertain.cleanup_unproven() || uncertain.post_spawn_cleanup_proven());
    }

    #[test]
    fn discovery_error_reports_cleanup_proof_without_false_uncertainty() {
        let proven = SpawnOwnedError::after_proven_cleanup(io::Error::other("reader failed"));
        let uncertain =
            SpawnOwnedError::after_unproven_cleanup(io::Error::other("termination failed"));

        let proven_message = format_discovery_failure("Codex", &proven);
        assert!(proven_message.contains("cleanup was proven"));
        assert!(!proven_message.contains("could not be proven"));
        assert!(format_discovery_failure("Codex", &uncertain).contains("could not be proven"));
    }

    #[cfg(unix)]
    #[test]
    fn provider_roster_reports_host_containment_as_unsupported() {
        let providers = list().unwrap();
        assert!(!providers.is_empty());
        assert!(providers.iter().all(|provider| {
            !provider.found && provider.availability == AgentAvailability::HostUnsupported
        }));
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
        let Ok(mut child) = spawn_owned(&mut command) else {
            // Unix hosts reject before spawn instead of silently downgrading
            // to an escapable process group or writable cgroup leaf.
            #[cfg(unix)]
            return;
            #[cfg(windows)]
            panic!("Windows Job Object containment unexpectedly failed");
        };

        terminate_child_tree(&mut child).unwrap();
        assert!(child.child.try_wait().unwrap().is_some());
    }

    #[cfg(unix)]
    #[test]
    fn unix_without_unprivileged_non_escapable_containment_rejects_before_spawn() {
        let mut command = Command::new("sh");
        command.args(["-c", "sleep 30"]);
        let error = match spawn_owned(&mut command) {
            Ok(_) => panic!("provider launch unexpectedly bypassed strong containment"),
            Err(error) => error,
        };
        assert_eq!(error.kind(), io::ErrorKind::Unsupported);
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
        let mut child = spawn_owned(&mut command).unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while (!marker.exists() || child.child.try_wait().unwrap().is_none())
            && Instant::now() < deadline
        {
            thread::sleep(PROCESS_POLL_INTERVAL);
        }
        assert!(marker.exists());

        terminate_child_tree(&mut child).unwrap();
        let _ = std::fs::remove_file(marker);
    }

    #[cfg(windows)]
    #[test]
    fn job_owns_grandchild_after_intermediate_and_leader_exit() {
        let marker = std::env::temp_dir().join(format!(
            "wiii-neko-indirect-descendant-{}.pid",
            uuid::Uuid::new_v4()
        ));
        let escaped_marker = marker.to_string_lossy().replace('\'', "''");
        let intermediate = format!(
            "$g = Start-Process powershell.exe -WindowStyle Hidden -PassThru \
             -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-Command', \
             'Start-Sleep -Seconds 30'); \
             [IO.File]::WriteAllText('{escaped_marker}', [string]$g.Id)"
        );
        let escaped_intermediate = intermediate.replace('\'', "''");
        let script = format!(
            "$inner = '{escaped_intermediate}'; \
             $p = Start-Process powershell.exe -WindowStyle Hidden -PassThru \
             -ArgumentList @('-NoLogo','-NoProfile','-NonInteractive','-Command',$inner); \
             Wait-Process -Id $p.Id"
        );
        let mut command = Command::new("powershell.exe");
        command.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            &script,
        ]);
        let mut child = spawn_owned(&mut command).unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        while (!marker.exists() || child.child.try_wait().unwrap().is_none())
            && Instant::now() < deadline
        {
            thread::sleep(PROCESS_POLL_INTERVAL);
        }
        assert!(marker.exists());
        assert!(child.child.try_wait().unwrap().is_some());

        terminate_child_tree(&mut child).unwrap();
        let _ = std::fs::remove_file(marker);
    }
}
