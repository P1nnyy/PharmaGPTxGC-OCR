import os
import argparse
import fnmatch
import sys
from pathlib import Path

# --- Configuration ---

INCLUDE_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.json', '.yaml', '.yml', '.md', '.sh'
}

INCLUDE_FILES = {
    'Dockerfile', '.env.example', 'requirements.txt', 'docker-compose.yml'
}

EXCLUDE_DIRS = {
    '.git', 'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache',
    '.mypy_cache', 'dist', 'build', 'outputs', 'datasets', 'test_images',
    'results', 'logs', 'coverage'
}

EXCLUDE_FILE_PATTERNS = [
    '.DS_Store', '*.pyc', '*.pyo',
    '*.jpg', '*.jpeg', '*.png', '*.webp', '*.pdf',
    '*.zip', '*.tar', '*.gz',
    '*.mp4', '*.mov',
    '*.csv', '*.parquet',
    '*.pt', '*.pth', '*.bin', '*.safetensors', '*.onnx' # Model weights
]

MAX_LINES = 2000
MAX_SIZE_BYTES = 500 * 1024  # 500 KB

def is_included(file_path: Path) -> bool:
    # Check directory exclusions
    for part in file_path.parts:
        if part in EXCLUDE_DIRS:
            return False
            
    name = file_path.name
    
    # Check file patterns
    for pattern in EXCLUDE_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return False
            
    # Check includes
    if name in INCLUDE_FILES:
        return True
        
    if file_path.suffix.lower() in INCLUDE_EXTENSIONS:
        return True
        
    return False

def build_tree(root_dir: Path, valid_files: set) -> str:
    """Build a text-based tree representation of the valid files."""
    tree_str = []
    
    def _walk(current_dir: Path, prefix: str = ''):
        try:
            # Sort items: directories first, then files
            items = sorted(os.listdir(current_dir))
            
            # Filter and categorize
            dirs = []
            files = []
            for item in items:
                path = current_dir / item
                if path.is_dir() and item not in EXCLUDE_DIRS:
                    # Only include dir if it contains valid files
                    if any(f.is_relative_to(path) for f in valid_files):
                        dirs.append(item)
                elif path in valid_files:
                    files.append(item)
                    
            all_items = dirs + files
            for i, item in enumerate(all_items):
                path = current_dir / item
                is_last = (i == len(all_items) - 1)
                
                connector = '└── ' if is_last else '├── '
                tree_str.append(f"{prefix}{connector}{item}")
                
                if path.is_dir():
                    new_prefix = prefix + ('    ' if is_last else '│   ')
                    _walk(path, new_prefix)
                    
        except PermissionError:
            pass
            
    tree_str.append(root_dir.name + "/")
    _walk(root_dir)
    return '\n'.join(tree_str)

def process_file(file_path: Path, root_dir: Path, out_file) -> None:
    relative_path = file_path.relative_to(root_dir)
    size_bytes = file_path.stat().st_size
    
    # Count lines efficiently
    try:
        with open(file_path, 'rb') as f:
            line_count = sum(1 for _ in f)
    except Exception:
        line_count = 0
        
    # Write header
    banner = f"FILE: {relative_path}"
    out_file.write(f"{'=' * 50}\n")
    out_file.write(f"{banner}\n")
    out_file.write(f"{'=' * len(banner)}\n")
    out_file.write(f"Size: {size_bytes} bytes | Lines: {line_count}\n\n")
    
    # Process contents
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            if size_bytes > MAX_SIZE_BYTES or line_count > MAX_LINES:
                out_file.write(f"!!! WARNING: FILE TRUNCATED !!!\n")
                out_file.write(f"File exceeds limits (Max lines: {MAX_LINES}, Max size: {MAX_SIZE_BYTES} bytes).\n\n")
                
                lines_written = 0
                for line in f:
                    out_file.write(line)
                    lines_written += 1
                    if lines_written >= MAX_LINES:
                        out_file.write("\n... [CONTENT TRUNCATED] ...\n")
                        break
            else:
                for line in f:
                    out_file.write(line)
                    
    except UnicodeDecodeError:
        out_file.write("[BINARY OR NON-UTF8 CONTENT SKIPPED]\n")
    except Exception as e:
        out_file.write(f"[ERROR READING FILE: {e}]\n")
        
    out_file.write("\n\n")

def main():
    parser = argparse.ArgumentParser(description="Export project codebase for LLMs")
    parser.add_argument("--include-tree-only", action="store_true", help="Only output the directory tree")
    parser.add_argument("--output", type=str, default="~/Desktop/codebase/codebase.txt", help="Output file path")
    args = parser.parse_args()
    
    project_root = Path.cwd()
    output_path = Path(args.output).expanduser().resolve()
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Scanning project root: {project_root}")
    
    # 1. Gather all valid files
    valid_files = set()
    for root, dirs, files in os.walk(project_root):
        # Modify dirs in-place to prevent os.walk from descending into excluded dirs
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        
        for file in files:
            path = Path(root) / file
            if is_included(path):
                valid_files.add(path)
                
    valid_files_sorted = sorted(list(valid_files))
    
    print(f"Found {len(valid_files_sorted)} relevant files.")
    
    # 2. Build Tree
    tree_content = build_tree(project_root, valid_files)
    
    # 3. Write Output
    print(f"Writing to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as out:
        out.write("PROJECT DIRECTORY TREE\n")
        out.write("======================\n")
        out.write(tree_content)
        out.write("\n\n")
        
        if not args.include_tree_only:
            for file_path in valid_files_sorted:
                process_file(file_path, project_root, out)
                
    print("Done!")

if __name__ == "__main__":
    main()
