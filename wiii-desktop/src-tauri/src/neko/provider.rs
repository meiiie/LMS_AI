use serde::{Deserialize, Serialize};
#[cfg(windows)]
use std::ffi::OsString;
use std::fs::{File, OpenOptions};
use std::io::{self, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};
use std::thread;
use std::time::{Duration, Instant};
use uuid::Uuid;

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const PROBE_TIMEOUT: Duration = Duration::from_secs(3);
const MAX_PROBE_OUTPUT_BYTES: usize = 64 * 1024;

struct ProbeOutput {
    status: ExitStatus,
    stdout: Vec<u8>,
}

struct ProbeCapture {
    path: PathBuf,
    file: Option<File>,
}

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
}

impl Drop for ProbeCapture {
    fn drop(&mut self) {
        self.file.take();
        let _ = std::fs::remove_file(&self.path);
    }
}

/// Run a discovery command without allowing a broken provider shim to hang
/// the desktop. A temporary file avoids a reader thread that can outlive a
/// broken descendant holding stdout open; only a bounded prefix is returned.
fn run_probe(mut command: Command) -> io::Result<ProbeOutput> {
    let mut capture = ProbeCapture::create()?;
    command
        .stdin(Stdio::null())
        .stdout(capture.stdio()?)
        .stderr(Stdio::null());
    hidden(&mut command);
    let mut child = command.spawn()?;
    let deadline = Instant::now() + PROBE_TIMEOUT;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "provider probe timed out",
            ));
        }
        thread::sleep(Duration::from_millis(25));
    };
    let stdout = capture.read_bounded()?;
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
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
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
