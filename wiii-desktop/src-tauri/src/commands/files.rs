use base64::{engine::general_purpose::STANDARD as BASE64, Engine as _};
use serde::Serialize;
use std::{
    collections::HashSet,
    fs,
    path::{Component, Path, PathBuf},
    process::Command,
    time::UNIX_EPOCH,
};

const MAX_WORKSPACE_FILES: usize = 2_500;
const MAX_TEXT_BYTES: u64 = 3 * 1024 * 1024;
const MAX_MEDIA_BYTES: u64 = 8 * 1024 * 1024;
const SKIPPED_DIRECTORIES: &[&str] = &[
    ".git",
    ".next",
    ".turbo",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "target",
];

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceEntry {
    path: String,
    name: String,
    size: u64,
    modified_at: Option<u64>,
    language: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceListing {
    entries: Vec<WorkspaceEntry>,
    truncated: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceFile {
    path: String,
    name: String,
    kind: String,
    language: String,
    mime_type: String,
    size: u64,
    modified_at: Option<u64>,
    content: Option<String>,
    data_url: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceChange {
    path: String,
    status: String,
    staged: bool,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceChanges {
    is_git: bool,
    changes: Vec<WorkspaceChange>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkspaceDiff {
    path: String,
    status: String,
    language: String,
    original: String,
    modified: String,
    binary: bool,
}

/// Open a native file dialog to select a document (PDF) for upload.
#[tauri::command]
pub async fn pick_document() -> Result<Option<String>, String> {
    Ok(None)
}

fn canonical_workspace(workspace: &str) -> Result<PathBuf, String> {
    let root =
        fs::canonicalize(workspace).map_err(|error| format!("Không thể mở workspace: {error}"))?;
    if !root.is_dir() {
        return Err("Workspace không phải là một thư mục.".into());
    }
    Ok(root)
}

fn safe_relative(path: &str) -> Result<PathBuf, String> {
    let candidate = Path::new(path);
    if candidate.is_absolute()
        || candidate.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err("Đường dẫn file không hợp lệ.".into());
    }
    Ok(candidate.to_path_buf())
}

fn resolve_existing_file(root: &Path, path: &str) -> Result<(PathBuf, PathBuf), String> {
    let requested = Path::new(path);
    let candidate = if requested.is_absolute() {
        requested.to_path_buf()
    } else {
        root.join(safe_relative(path)?)
    };
    let canonical =
        fs::canonicalize(&candidate).map_err(|error| format!("Không thể mở file: {error}"))?;
    if !canonical.starts_with(root) || !canonical.is_file() {
        return Err("File nằm ngoài workspace hoặc không phải file thường.".into());
    }
    let relative = canonical
        .strip_prefix(root)
        .map_err(|_| "File nằm ngoài workspace.".to_string())?
        .to_path_buf();
    Ok((canonical, relative))
}

fn slash_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

fn modified_millis(metadata: &fs::Metadata) -> Option<u64> {
    metadata
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_millis() as u64)
}

fn language_for(path: &Path) -> String {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "css" => "css",
        "go" => "go",
        "html" | "htm" => "html",
        "java" => "java",
        "js" | "cjs" | "mjs" => "javascript",
        "json" | "jsonl" => "json",
        "jsx" => "javascript",
        "md" | "mdx" => "markdown",
        "py" => "python",
        "rb" => "ruby",
        "rs" => "rust",
        "sh" | "bash" | "zsh" => "shell",
        "sql" => "sql",
        "svg" => "xml",
        "toml" => "toml",
        "ts" => "typescript",
        "tsx" => "typescript",
        "xml" => "xml",
        "yaml" | "yml" => "yaml",
        _ => "plaintext",
    }
    .into()
}

fn media_type(path: &Path) -> Option<(&'static str, &'static str)> {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "gif" => Some(("image", "image/gif")),
        "jpeg" | "jpg" => Some(("image", "image/jpeg")),
        "png" => Some(("image", "image/png")),
        "webp" => Some(("image", "image/webp")),
        "pdf" => Some(("pdf", "application/pdf")),
        _ => None,
    }
}

fn visit_workspace(
    root: &Path,
    directory: &Path,
    entries: &mut Vec<WorkspaceEntry>,
    visited: &mut HashSet<PathBuf>,
    truncated: &mut bool,
) {
    let Ok(canonical_directory) = fs::canonicalize(directory) else {
        return;
    };
    if !canonical_directory.starts_with(root) || !visited.insert(canonical_directory.clone()) {
        return;
    }
    let Ok(children) = fs::read_dir(canonical_directory) else {
        return;
    };
    let mut children = children.flatten().collect::<Vec<_>>();
    children.sort_by_key(|entry| entry.file_name().to_string_lossy().to_ascii_lowercase());
    for child in children {
        if entries.len() >= MAX_WORKSPACE_FILES {
            *truncated = true;
            return;
        }
        let path = child.path();
        let Ok(file_type) = child.file_type() else {
            continue;
        };
        if file_type.is_symlink() {
            continue;
        }
        if file_type.is_dir() {
            let name = child.file_name();
            if !SKIPPED_DIRECTORIES.contains(&name.to_string_lossy().as_ref()) {
                visit_workspace(root, &path, entries, visited, truncated);
            }
            continue;
        }
        if !file_type.is_file() {
            continue;
        }
        let Ok(metadata) = child.metadata() else {
            continue;
        };
        let Ok(relative) = path.strip_prefix(root) else {
            continue;
        };
        entries.push(WorkspaceEntry {
            path: slash_path(relative),
            name: child.file_name().to_string_lossy().into_owned(),
            size: metadata.len(),
            modified_at: modified_millis(&metadata),
            language: language_for(&path),
        });
    }
}

#[tauri::command]
pub fn neko_list_workspace_files(workspace: String) -> Result<WorkspaceListing, String> {
    let root = canonical_workspace(&workspace)?;
    let mut entries = Vec::new();
    let mut visited = HashSet::new();
    let mut truncated = false;
    visit_workspace(&root, &root, &mut entries, &mut visited, &mut truncated);
    Ok(WorkspaceListing { entries, truncated })
}

#[tauri::command]
pub fn neko_read_workspace_file(workspace: String, path: String) -> Result<WorkspaceFile, String> {
    let root = canonical_workspace(&workspace)?;
    let (absolute, relative) = resolve_existing_file(&root, &path)?;
    let metadata = fs::metadata(&absolute).map_err(|error| error.to_string())?;
    let name = absolute
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("file")
        .to_string();

    if let Some((kind, mime_type)) = media_type(&absolute) {
        if metadata.len() > MAX_MEDIA_BYTES {
            return Err("File media lớn hơn giới hạn xem trước 8 MiB.".into());
        }
        let bytes = fs::read(&absolute).map_err(|error| format!("Không thể đọc file: {error}"))?;
        return Ok(WorkspaceFile {
            path: slash_path(&relative),
            name,
            kind: kind.into(),
            language: language_for(&absolute),
            mime_type: mime_type.into(),
            size: metadata.len(),
            modified_at: modified_millis(&metadata),
            content: None,
            data_url: Some(format!("data:{mime_type};base64,{}", BASE64.encode(bytes))),
        });
    }

    if metadata.len() > MAX_TEXT_BYTES {
        return Err("File lớn hơn giới hạn xem trước 3 MiB.".into());
    }
    let bytes = fs::read(&absolute).map_err(|error| format!("Không thể đọc file: {error}"))?;
    let content = String::from_utf8(bytes)
        .map_err(|_| "File nhị phân này chưa có trình xem an toàn.".to_string())?;
    let language = language_for(&absolute);
    let mime_type = if language == "html" {
        "text/html"
    } else if language == "markdown" {
        "text/markdown"
    } else {
        "text/plain"
    };
    Ok(WorkspaceFile {
        path: slash_path(&relative),
        name,
        kind: "text".into(),
        language,
        mime_type: mime_type.into(),
        size: metadata.len(),
        modified_at: modified_millis(&metadata),
        content: Some(content),
        data_url: None,
    })
}

fn git(root: &Path, args: &[&str]) -> Result<std::process::Output, String> {
    Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .map_err(|error| format!("Không thể chạy git: {error}"))
}

fn change_status(code: &str) -> &'static str {
    if code == "??" {
        "untracked"
    } else if code.contains('D') {
        "deleted"
    } else if code.contains('A') {
        "added"
    } else if code.contains('R') {
        "renamed"
    } else {
        "modified"
    }
}

fn parse_porcelain_changes(output: &[u8]) -> Vec<WorkspaceChange> {
    let records = output.split(|byte| *byte == 0).collect::<Vec<_>>();
    let mut changes = Vec::new();
    let mut index = 0;
    while index < records.len() {
        let record = String::from_utf8_lossy(records[index]);
        if record.len() < 4 {
            index += 1;
            continue;
        }
        let code = &record[..2];
        // With `--porcelain=v1 -z`, rename/copy records are `XY to\0from\0`.
        // Keep the first (current) path and consume the following old path.
        let path = record[3..].replace('\\', "/");
        if (code.contains('R') || code.contains('C')) && index + 1 < records.len() {
            index += 1;
        }
        changes.push(WorkspaceChange {
            path,
            status: change_status(code).into(),
            staged: code.as_bytes()[0] != b' ' && code != "??",
        });
        index += 1;
    }
    changes
}

fn collect_changes(root: &Path) -> Result<WorkspaceChanges, String> {
    let probe = git(root, &["rev-parse", "--is-inside-work-tree"])?;
    if !probe.status.success() {
        return Ok(WorkspaceChanges {
            is_git: false,
            changes: Vec::new(),
        });
    }
    let output = git(
        root,
        &["status", "--porcelain=v1", "-z", "--untracked-files=all"],
    )?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let mut changes = parse_porcelain_changes(&output.stdout);
    changes.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(WorkspaceChanges {
        is_git: true,
        changes,
    })
}

#[tauri::command]
pub fn neko_workspace_changes(workspace: String) -> Result<WorkspaceChanges, String> {
    let root = canonical_workspace(&workspace)?;
    collect_changes(&root)
}

#[tauri::command]
pub fn neko_workspace_diff(workspace: String, path: String) -> Result<WorkspaceDiff, String> {
    let root = canonical_workspace(&workspace)?;
    let relative = safe_relative(&path)?;
    let relative_string = slash_path(&relative);
    let changes = collect_changes(&root)?;
    if !changes.is_git {
        return Err("Workspace này chưa phải Git repository.".into());
    }
    let change = changes
        .changes
        .iter()
        .find(|candidate| candidate.path == relative_string)
        .cloned()
        .ok_or_else(|| "File không có thay đổi Git hiện tại.".to_string())?;

    let head_spec = format!("HEAD:{relative_string}");
    let original_output = git(&root, &["show", &head_spec])?;
    let original_bytes = if original_output.status.success() {
        original_output.stdout
    } else {
        Vec::new()
    };
    let modified_bytes = if change.status == "deleted" {
        Vec::new()
    } else {
        let (absolute, _) = resolve_existing_file(&root, &relative_string)?;
        fs::read(absolute).map_err(|error| format!("Không thể đọc file: {error}"))?
    };
    let original = String::from_utf8(original_bytes);
    let modified = String::from_utf8(modified_bytes);
    let binary = original.is_err() || modified.is_err();
    Ok(WorkspaceDiff {
        path: relative_string,
        status: change.status,
        language: language_for(&relative),
        original: original.unwrap_or_default(),
        modified: modified.unwrap_or_default(),
        binary,
    })
}

#[cfg(test)]
mod tests {
    use super::{parse_porcelain_changes, safe_relative};

    #[test]
    fn rejects_workspace_escape_paths() {
        assert!(safe_relative("../secret.txt").is_err());
        assert!(safe_relative("C:\\secret.txt").is_err());
        assert!(safe_relative("src/app.ts").is_ok());
    }

    #[test]
    fn keeps_the_current_path_for_zero_delimited_renames() {
        let changes =
            parse_porcelain_changes(b"R  src/new name.ts\0src/old name.ts\0?? notes/draft.txt\0");
        assert_eq!(changes.len(), 2);
        assert_eq!(changes[0].path, "src/new name.ts");
        assert_eq!(changes[0].status, "renamed");
        assert!(changes[0].staged);
        assert_eq!(changes[1].path, "notes/draft.txt");
        assert_eq!(changes[1].status, "untracked");
    }
}
