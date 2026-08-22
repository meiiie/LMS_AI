use serde::{Deserialize, Serialize};
use std::process::{Command, Stdio};

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

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
    pub program: String,
    pub version: Option<String>,
}

fn probe_definition(provider: ProviderDefinition) -> Option<ResolvedProvider> {
    for candidate in provider.candidates() {
        let mut command = Command::new(candidate);
        hidden(
            command
                .arg(provider.version_arg)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::null()),
        );
        if let Ok(output) = command.output() {
            if output.status.success() {
                let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
                return Some(ResolvedProvider {
                    definition: provider,
                    program: (*candidate).to_string(),
                    version: (!version.is_empty()).then_some(version),
                });
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
    hidden(
        command
            .arg("profiles")
            .current_dir(cwd_path)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null()),
    );
    let output = command
        .output()
        .map_err(|error| format!("profile probe failed: {error}"))?;
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
}
