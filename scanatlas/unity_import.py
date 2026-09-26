"""Copy local asset files to Unity and queue work for the bundled Editor helper.

No download or Unity process is started here. Requests become visible only after
all source files have been copied; Unity reports are the authority on completion.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
import uuid
import zipfile

from .downloads import LEVELS

HELPER = Path(__file__).parent / 'assets/unity/AtlasImporter.cs'
HELPER_MARKER = '// Atlas Unity Importer'
MAX_UNPACKED_BYTES = 2 * 1024**3
MAX_FILES = 10000
DISK_RESERVE_BYTES = 64 * 1024**2
SUPPORTED = {'.fbx', '.obj', '.mtl', '.png', '.jpg', '.jpeg', '.tga', '.tiff', '.tif', '.exr', '.hdr', '.bmp'}
MODELS = {'.fbx', '.obj'}
TEXTURES = SUPPORTED - MODELS - {'.mtl'}
RIGS = {'auto', 'humanoid', 'generic', 'none'}
_RUNNING_PROJECT_CACHE = {'expires': 0.0, 'paths': None}


def _project(project):
    if not project:
        raise ValueError('Choose a Unity project first.')
    root = Path(project).expanduser().resolve()
    if not (root / 'Assets').is_dir() or not (root / 'ProjectSettings/ProjectVersion.txt').is_file():
        raise ValueError('Choose a Unity project containing Assets and ProjectSettings/ProjectVersion.txt.')
    if (root / 'Assets').is_symlink():
        raise ValueError('The Unity Assets folder must not be a symbolic link.')
    return root


def _process_running_project_paths(proc_root=Path('/proc')):
    """Find Unity Editor projects launched outside the Unity CLI/Hub integration.

    Linux process arguments are inspected in memory only. In particular, never
    log or return full command lines because Unity arguments can contain secrets.
    """
    if not sys.platform.startswith('linux'):
        return None
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    switches = {'-projectpath', '--project-path', '-createproject'}
    paths = []
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            executable = os.readlink(entry / 'exe').casefold()
            if 'unity' not in executable or 'editor' not in executable:
                continue
            args = (entry / 'cmdline').read_bytes().split(b'\0')
            args = [value.decode(errors='replace') for value in args if value]
            candidates = []
            for index, arg in enumerate(args):
                key, separator, value = arg.partition('=')
                key = key.casefold()
                if key in switches:
                    if separator:
                        candidates.append(value)
                    elif index + 1 < len(args):
                        candidates.append(args[index + 1])
            for candidate in candidates:
                if not candidate or not Path(candidate).is_absolute():
                    continue
                try:
                    root = _project(candidate)
                except (OSError, ValueError):
                    continue
                if str(root) not in paths:
                    paths.append(str(root))
        except OSError:
            continue
    return paths


def _running_project_paths(refresh=False):
    """Return open Unity project paths, including Editors launched from Hub."""
    now = time.monotonic()
    if not refresh and now < _RUNNING_PROJECT_CACHE['expires']:
        cached = _RUNNING_PROJECT_CACHE['paths']
        return list(cached) if isinstance(cached, list) else None
    paths = []
    cli_paths = None
    cli = shutil.which('unity')
    if cli:
        try:
            completed = subprocess.run(
                [cli, 'editors', 'running', '--format', 'json', '--non-interactive',
                 '--no-banner', '--no-pager'],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=2.5)
            payload = json.loads(completed.stdout)
            if completed.returncode == 0 and isinstance(payload, dict) and payload.get('success') is True:
                data = payload.get('data')
                instances = data.get('instances', []) if isinstance(data, dict) else data
                if isinstance(instances, list):
                    cli_paths = []
                    for instance in instances:
                        if not isinstance(instance, dict):
                            continue
                        path = instance.get('projectPath')
                        if not isinstance(path, str) or not path:
                            candidate = instance.get('project')
                            path = candidate if isinstance(candidate, str) and Path(candidate).is_absolute() else None
                        if not path:
                            continue
                        try:
                            root = _project(path)
                        except (OSError, ValueError):
                            continue
                        if str(root) not in cli_paths:
                            cli_paths.append(str(root))
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            pass

    process_paths = _process_running_project_paths()
    if cli_paths is None and process_paths is None:
        _RUNNING_PROJECT_CACHE.update(expires=now + 0.5, paths=None)
        return None
    for path in (cli_paths or []) + (process_paths or []):
        if path not in paths:
            paths.append(path)
    _RUNNING_PROJECT_CACHE.update(expires=time.monotonic() + 3.0, paths=paths)
    return paths


def _select_project(c, project=None):
    """Prefer the sole open Unity project; preserve an explicit project choice."""
    if project:
        return _project(project), 'explicit'
    saved = c.setting('unity_project')
    running = _running_project_paths()
    if running is not None:
        if len(running) == 1:
            return _project(running[0]), 'open'
        if len(running) > 1:
            raise ValueError('Multiple Unity Editor projects are open. Choose the target project in Atlas before importing.')
    return _project(saved), 'configured'


def _safe_destination(root, relative, create=False):
    """Check every existing component before creating controlled directories."""
    current = root
    for part in PurePosixPath(relative).parts:
        if part in ('..', '.') or '/' in part or '\\' in part:
            raise ValueError('Unsafe Unity destination.')
        current = current / part
        if current.is_symlink():
            raise ValueError('Unity destination contains a symbolic link.')
        if create:
            current.mkdir(exist_ok=True)
        elif current.exists() and not current.is_dir():
            raise ValueError('Unity destination is not a directory.')
    return current


def _install_helper(root):
    if not HELPER.is_file():
        raise ValueError('The bundled Unity importer is missing. Reinstall Atlas.')
    content = HELPER.read_bytes()
    folder = _safe_destination(root, 'Assets/Atlas/Editor', create=True)
    destination = folder / 'AtlasImporter.cs'
    if destination.is_symlink():
        raise ValueError('The Unity importer path must not be a symbolic link.')
    if destination.exists():
        existing = destination.read_bytes()
        if existing == content:
            return
        if not existing.startswith(HELPER_MARKER.encode()):
            raise FileExistsError('Assets/Atlas/Editor/AtlasImporter.cs already contains a different script. Move it before configuring Atlas.')
    _atomic_bytes(destination, content)


def _pipeline_package_installed(root):
    manifest = root / 'Packages/manifest.json'
    try:
        payload = json.loads(manifest.read_text())
        dependencies = payload.get('dependencies', {}) if isinstance(payload, dict) else {}
        return isinstance(dependencies, dict) and bool(dependencies.get('com.unity.pipeline'))
    except (OSError, ValueError, TypeError):
        return False


def _ensure_pipeline_package(root):
    """Provision Unity's CLI bridge when available; the importer also works without it."""
    if _pipeline_package_installed(root):
        return True, None
    cli = shutil.which('unity')
    if not cli:
        return False, 'Unity CLI is unavailable; the Atlas Editor importer still works without the optional Pipeline package.'
    try:
        completed = subprocess.run(
            [cli, 'pipeline', 'install', '--project-path', str(root), '--format', 'json',
             '--non-interactive', '--no-banner', '--no-pager'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=90)
        payload = json.loads(completed.stdout)
        if (completed.returncode == 0 and isinstance(payload, dict) and payload.get('success') is True
                and _pipeline_package_installed(root)):
            return True, None
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        pass
    return False, 'Unity Pipeline package setup did not complete; the Atlas Editor importer remains installed and can process the queue.'


def configure(c, project):
    """Remember a project and provision the Atlas importer and optional CLI bridge."""
    root = _project(project)
    _install_helper(root)
    pipeline_installed, pipeline_note = _ensure_pipeline_package(root)
    c.set_setting('unity_project', str(root))
    result = project_info(c, refresh=True, project=root)
    result['pipeline_package_installed'] = pipeline_installed
    if pipeline_note:
        result['pipeline_package_note'] = pipeline_note
    return result


def project_info(c, refresh=False, project=None):
    explicit = project is not None
    project = str(_project(project)) if explicit else c.setting('unity_project')
    running = [] if explicit else _running_project_paths(refresh=refresh)
    source = 'configured' if project else None
    if running and len(running) == 1:
        project, source = running[0], 'open'
    elif running and len(running) > 1:
        return {'project': None, 'valid': False, 'helper_installed': False,
                'source': 'ambiguous', 'open_projects': running,
                'note': 'Multiple Unity projects are open. Choose the target project with the Unity project control.'}
    result = {'project': project or None, 'valid': False, 'helper_installed': False,
              'source': source, 'open_projects': running or []}
    if not project:
        result['note'] = 'Open a Unity project or choose one to enable Import to Unity.'
        return result
    try:
        root = _project(project)
        helper = root / 'Assets/Atlas/Editor/AtlasImporter.cs'
        result.update(project=str(root), valid=True,
                      helper_installed=helper.is_file() and not helper.is_symlink() and helper.read_bytes().startswith(HELPER_MARKER.encode()),
                      pipeline_package_installed=_pipeline_package_installed(root))
        if source == 'open':
            result['note'] = ('Connected to the open Unity project; Atlas will process queued imports as the Editor refreshes.'
                              if result['helper_installed'] else 'Detected the open Unity project. Atlas will install its importer when you import.')
        else:
            result['note'] = ('Open this project in Unity; the Editor processes queued imports automatically.' if result['helper_installed']
                              else 'Configure this project again to install the Atlas Unity importer.')
    except (ValueError, OSError) as error:
        result['note'] = str(error)
    return result


def _relative(name):
    """Reject ambiguous paths as well as traversal on Unix and Windows."""
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise ValueError('Unsafe source path.')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or ':' in name or not path.parts:
        raise ValueError('Unsafe source path: ' + name)
    return path


def _local_file(root, name):
    path = root
    for part in _relative(name).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('The local source contains a symbolic link.')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('The local source is incomplete or contains an unsupported file.')
    return path


def _read_manifest(root, asset_id, quality):
    manifest = root / 'download.json'
    if not manifest.exists():
        return None
    if manifest.is_symlink() or manifest.stat().st_size > 4 * 1024**2:
        raise ValueError('Unsafe download manifest.')
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict) or data.get('id') != asset_id or data.get('quality') != quality:
        raise ValueError('The local download does not match this asset and selected quality.')
    names = data.get('files')
    if not isinstance(names, list) or not names:
        raise ValueError('The local download manifest has no files.')
    for name in names:
        _local_file(root, name)
    return names


def available_local(c, a, quality='Medium'):
    """Describe an exact completed download or indexed local Mixamo source."""
    if isinstance(a, str):
        a = c.get(a)
    if not a:
        return {'available': False, 'path': None, 'quality': quality, 'reason': 'Unknown asset.'}
    detail = a.get('detail', {})
    if detail.get('source') == 'mixamo' and detail.get('local_file'):
        quality = 'Original'
        path = Path(detail.get('bundle_root') or detail['local_file']).expanduser()
        files = detail.get('bundle_files') or [{'name': Path(detail['local_file']).name}]
        root = path if path.is_dir() else path.parent
        try:
            available = path.exists() and not path.is_symlink() and all(
                _local_file(root, f['name']) for f in files)
        except (OSError, ValueError, KeyError):
            available = False
        return {'available': available, 'path': str(path.resolve()) if available else None, 'quality': quality,
                'source': 'mixamo', 'reason': None if available else 'The local Mixamo file or bundle is missing.'}
    if quality not in LEVELS:
        raise ValueError('Unknown quality.')
    reason = 'Download this asset at ' + quality + ' quality first.'
    rows = c.c.execute("SELECT path FROM downloads WHERE asset_id=? AND quality=? AND status='complete' ORDER BY id DESC", (a['id'], quality))
    for row in rows:
        path = Path(row['path']).expanduser()
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            _read_manifest(path.resolve(), a['id'], quality)
        except (OSError, ValueError):
            reason = 'The recorded ' + quality + ' download is incomplete or does not match this asset.'
            continue
        return {'available': True, 'path': str(path.resolve()), 'quality': quality, 'source': 'download', 'reason': None}
    return {'available': False, 'path': None, 'quality': quality, 'reason': reason}


def _source_files(root, names=None):
    if root.is_file():
        return [(root, root.name)]
    if not root.is_dir():
        raise ValueError('The local source does not exist.')
    paths = (root.joinpath(*_relative(name).parts) for name in names) if names else root.rglob('*')
    result = []
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('The local source contains a symbolic link.')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('The local source contains a missing or unsupported file.')
        relative = path.relative_to(root).as_posix()
        _local_file(root, relative)
        result.append((path, relative))
        if len(result) > MAX_FILES:
            raise ValueError('The import contains too many files.')
    return sorted(result, key=lambda item: item[1])


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _role(name, a):
    files = a.get('detail', {}).get('files', [])
    matches = [item for item in files if item.get('name') == name]
    if not matches:
        matches = [item for item in files if Path(item.get('name', '')).name == Path(name).name]
    if len(matches) == 1:
        role = matches[0].get('type', '')
        if role and role not in ('dependency', 'package', 'zip'):
            return role
    suffix = Path(name).suffix.lower()
    return 'mesh' if suffix in MODELS else 'material' if suffix == '.mtl' else 'texture'


def _plan(a, root, quality):
    names = _read_manifest(root, a['id'], quality) if root.is_dir() and (root / 'download.json').exists() else None
    detail = a.get('detail', {})
    if root.is_dir() and detail.get('bundle_root') and root == Path(detail['bundle_root']).expanduser().resolve():
        names = [entry['name'] for entry in detail.get('bundle_files', [])] or names
    sources = _source_files(root, names)
    entries, warnings, hashes, used = [], [], {}, set()
    unpacked, count = 0, 0
    def add(path, name, size, member=None):
        nonlocal unpacked, count
        count += 1
        unpacked += size
        if count > MAX_FILES or unpacked > MAX_UNPACKED_BYTES:
            raise ValueError('Import exceeds the limit of 10,000 files or 2 GiB unpacked.')
        suffix = Path(name).suffix.lower()
        if suffix == '.zip':
            warnings.append('Nested ZIP archive is unsupported: ' + name)
            return
        if suffix not in SUPPORTED:
            if suffix not in ('.json', '.txt', '.md', '.meta'):
                warnings.append('Excluded unsupported file: ' + name)
            return
        key = name.casefold()
        if key in used:
            raise ValueError('The source contains conflicting filenames: ' + name)
        used.add(key)
        entries.append({'source': path, 'member': member, 'name': name, 'size': size, 'role': _role(name, a)})
    for path, relative in sources:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED and suffix != '.zip':
            add(path, relative, path.stat().st_size)
            continue
        hashes[relative] = _digest(path)
        if suffix != '.zip':
            add(path, relative, path.stat().st_size)
            continue
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES:
                raise ValueError('ZIP archive contains too many files.')
            for info in members:
                safe = _relative(info.filename)
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise ValueError('ZIP archive contains a symbolic link or special file.')
                if info.flag_bits & 1:
                    raise ValueError('Encrypted ZIP archives are unsupported.')
                if info.is_dir():
                    continue
                # Keep package paths intact so OBJ/MTL and model texture links work.
                parent = PurePosixPath(relative).parent
                name = (parent / safe).as_posix()
                add(path, name, info.file_size, info.filename)
    if not entries:
        raise ValueError('No supported Unity model or texture files were found in the local source.')
    if a.get('kind') in ('3D Assets', '3D Plants', 'Characters', 'Animations') and not any(Path(e['name']).suffix.lower() in MODELS for e in entries):
        raise ValueError('This asset has no supported FBX or OBJ model. Download a supported model before importing.')
    if not any(Path(e['name']).suffix.lower() in MODELS | TEXTURES for e in entries):
        raise ValueError('No usable model or texture was found in the local source.')
    fingerprint = hashlib.sha256(json.dumps({'hashes': hashes, 'quality': quality}, sort_keys=True).encode()).hexdigest()
    return entries, list(dict.fromkeys(warnings)), hashes, fingerprint


def _atomic_bytes(destination, content):
    fd, name = tempfile.mkstemp(prefix='.' + destination.name + '-', suffix='.tmp', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def _jobs(c):
    try:
        jobs = json.loads(c.setting('unity_import_jobs', '[]'))
        return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else []
    except ValueError:
        return []


def _save_job(c, job):
    jobs = [j for j in _jobs(c) if j.get('job_id') != job['job_id']]
    c.set_setting('unity_import_jobs', json.dumps((jobs + [job])[-100:]))


def _material_bindings(a):
    bindings = a.get('detail', {}).get('unity_material_bindings', [])
    if not isinstance(bindings, list) or len(bindings) > 1024:
        raise ValueError('Unity material bindings must be a list of at most 1024 material/texture_set pairs.')
    result, seen = [], set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise ValueError('Each Unity material binding must contain material and texture_set strings.')
        pair = {key: binding.get(key) for key in ('material', 'texture_set')}
        if any(not isinstance(value, str) or not value.strip() or len(value) > 512 or
               any(ord(character) < 32 for character in value) for value in pair.values()):
            raise ValueError('Unity material binding names must be nonempty strings without control characters.')
        if pair['material'] in seen:
            raise ValueError('Duplicate Unity material binding: ' + pair['material'])
        seen.add(pair['material'])
        result.append(pair)
    return sorted(result, key=lambda pair: pair['material'])


def _wake_editor(root, editor_open=False):
    """Ask a ready Editor to refresh; fall back to its file watcher if needed."""
    cli = shutil.which('unity')
    if not cli:
        if editor_open:
            return {'status': 'requested', 'reason': 'open_editor_watch', 'editor_status': 'running',
                    'note': 'Atlas queued this import in the open project. Unity should pick it up on refresh; choose Assets > Refresh if it stays queued.'}
        return {'status': 'unavailable', 'reason': 'missing_cli',
                'note': 'Automatic refresh is unavailable. Focus Unity or choose Assets > Refresh to start this queued import.'}

    def command(name):
        completed = subprocess.run(
            [cli, 'command', name, '--project-path', str(root), '--timeout', '2',
             '--format', 'json', '--non-interactive', '--no-banner', '--no-pager'],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=2.5)
        payload = json.loads(completed.stdout)
        if completed.returncode or not isinstance(payload, dict) or payload.get('success') is not True:
            return None
        data = payload.get('data')
        if not isinstance(data, dict) or data.get('success') is False:
            return None
        result = data.get('result')
        if isinstance(result, str):
            result = json.loads(result)
        return result if isinstance(result, dict) else None

    try:
        status = command('editor_status')
        if not status:
            if editor_open:
                return {'status': 'unavailable', 'reason': 'editor_unavailable',
                        'note': 'Atlas detected the open Editor but could not confirm its bridge. Choose Assets > Refresh if the import remains queued.'}
            return {'status': 'unavailable', 'reason': 'editor_unavailable',
                    'note': 'The Editor connection is unavailable. Open this project in Unity and choose Assets > Refresh if it remains queued.'}
        if not status.get('projectPath') or Path(status['projectPath']).resolve() != root:
            return {'status': 'deferred', 'reason': 'project_mismatch',
                    'note': 'The Editor connection did not confirm this project. Focus the selected project and choose Assets > Refresh.'}
        if status.get('playMode') != 'stopped':
            return {'status': 'deferred', 'reason': 'play_mode',
                    'note': 'Automatic refresh waits while Play Mode is active. Exit Play Mode, then choose Assets > Refresh if the import remains queued.'}
        if status.get('status') != 'ready' or status.get('compiling') or status.get('domainReloadInProgress'):
            return {'status': 'deferred', 'reason': 'editor_busy',
                    'note': 'Unity is compiling or refreshing. Let it finish, then choose Assets > Refresh if this import remains queued.'}
        response = command('recompile')
        if response and response.get('status') in ('compiling', 'triggered', 'completed', 'up_to_date'):
            return {'status': 'requested', 'reason': 'refresh_acknowledged', 'editor_status': 'ready',
                    'recompile_status': response['status'],
                    'note': 'Unity acknowledged the refresh request. The queued import will run when compilation and asset refresh finish.'}
        return {'status': 'failed', 'reason': 'refresh_not_acknowledged',
                'note': 'Unity did not acknowledge the refresh. Check the Unity Console for compilation errors and choose Assets > Refresh.'}
    except subprocess.TimeoutExpired:
        return {'status': 'unconfirmed', 'reason': 'timeout',
                'note': 'The Editor refresh acknowledgement timed out. The import remains queued; focus Unity or choose Assets > Refresh if it does not start.'}
    except (OSError, ValueError, TypeError):
        return {'status': 'unavailable', 'reason': 'connection_error',
                'note': 'Automatic Editor refresh could not be confirmed. Focus Unity or choose Assets > Refresh to process this queued import.'}


def _status(record):
    result = dict(record)
    root = Path(record['project'])
    report = root / 'AtlasImports/reports' / (record['job_id'] + '.json')
    request = root / 'AtlasImports/requests' / (record['job_id'] + '.json')
    result['report_path'] = str(report)
    result.update(status='queued', progress_percent=0, stage='Waiting for Unity', progress_estimated=True)
    if report.is_file() and not report.is_symlink():
        try:
            if report.stat().st_size > 8 * 1024**2:
                raise ValueError('Unity report is too large.')
            payload = json.loads(report.read_text())
            if not isinstance(payload, dict) or payload.get('status') not in ('queued', 'processing', 'complete', 'failed'):
                raise ValueError('Unity report has an invalid status.')
            if payload.get('job_id', record['job_id']) != record['job_id']:
                raise ValueError('Unity report belongs to a different job.')
            result['report'] = payload
            for key, value in payload.items():
                if key not in ('job_id', 'project', 'asset_id', 'asset_folder', 'source', 'fingerprint'):
                    result[key] = value
        except (ValueError, OSError) as error:
            result.update(status='failed', error='Cannot read Unity import report: ' + str(error))
    elif not request.exists():
        result['note'] = 'No Unity report is available yet. Open the project and check the Unity Console.'
    if result['status'] in ('queued', 'processing'):
        helper = root / 'Assets/Atlas/Editor/AtlasImporter.cs'
        result['note'] = ('Atlas Unity importer is missing. Configure the project again.' if not helper.is_file()
                          else ('Unity is processing this import: ' + str(result.get('stage') or 'Preparing assets')) if result['status'] == 'processing' else 'Waiting for Unity. Open this project in the Editor; resolve Console compilation errors if it remains queued.')
        if result['status'] == 'queued' and isinstance(result.get('editor_wakeup'), dict):
            result['note'] += ' ' + result['editor_wakeup'].get('note', '')
    if result['status'] == 'complete':
        result.update(progress_percent=100, stage='Complete', progress_estimated=False)
    elif result['status'] == 'failed' and result['stage'] == 'Waiting for Unity':
        result.update(progress_percent=None, stage='Failed')
    elif result['status'] == 'processing' and result['stage'] == 'Waiting for Unity':
        result.update(progress_percent=None, stage='Importing in Unity')
    return result


def job_status(c, job=None, project=None):
    """Read durable Editor reports without launching Unity or changing the catalog."""
    jobs = _jobs(c)
    if project:
        project = str(Path(project).expanduser().resolve())
        jobs = [record for record in jobs if record.get('project') == project]
    if job:
        record = next((record for record in reversed(jobs) if record.get('job_id') == job), None)
        if record is None:
            raise ValueError('Unknown Unity import job: ' + str(job))
        jobs = [record]
    return {'project': project or c.setting('unity_project') or None,
            'jobs': [_status(record) for record in reversed(jobs)]}


def submit(c, asset_id, project=None, quality='Medium', execute=False, source=None, rig='auto', progress=None,
           editor_open=None):
    """Plan or copy local assets; progress(done, total, stage) uses bytes or None."""
    progress = progress or (lambda done, total, stage: None)
    progress(None, None, 'Checking local source')
    a = c.get(asset_id)
    if not a:
        raise ValueError('Unknown asset: ' + str(asset_id))
    if rig not in RIGS:
        raise ValueError('Rig must be auto, humanoid, generic, or none.')
    root, project_source = _select_project(c, project)
    if editor_open is None:
        editor_open = project_source == 'open'
    local = available_local(c, a, quality)
    quality = local['quality']
    if source is None:
        if not local['available']:
            raise ValueError(local['reason'])
        source = local['path']
    source = Path(source).expanduser()
    if source.is_symlink():
        raise ValueError('The local source must not be a symbolic link.')
    source = source.resolve()
    progress(None, None, 'Planning import')
    entries, warnings, hashes, fingerprint = _plan(a, source, quality)
    if not HELPER.is_file():
        raise ValueError('The bundled Unity importer is missing. Reinstall Atlas.')
    helper_sha256 = _digest(HELPER)
    material_bindings = _material_bindings(a)
    fingerprint = hashlib.sha256(json.dumps({
        'source': fingerprint, 'rig': rig, 'helper_sha256': helper_sha256,
        'material_bindings': material_bindings,
    }, sort_keys=True).encode()).hexdigest()
    for record in reversed(_jobs(c)):
        if (record.get('project'), record.get('asset_id'), record.get('fingerprint')) == (str(root), asset_id, fingerprint):
            existing = _status(record)
            if existing['status'] in ('queued', 'processing', 'complete') and (root / record['asset_folder']).is_dir():
                existing.update(reused=True, dry_run=not execute)
                progress(existing.get('progress_percent'), 100, existing['stage'])
                return existing
    job_id = str(uuid.uuid4())
    safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', str(asset_id))[:100] or 'asset'
    asset_folder = 'Assets/Atlas/Imported/' + safe_id + '/' + job_id
    files = [{'path': 'Source/' + entry['name'], 'role': entry['role']} for entry in entries]
    request = {'job_id': job_id, 'asset_id': asset_id, 'name': a['name'], 'kind': a['kind'], 'quality': quality,
               'asset_folder': asset_folder, 'rig': rig, 'files': files, 'material_bindings': material_bindings}
    result = dict(request, project=str(root), source=str(source), fingerprint=fingerprint,
                  helper_sha256=helper_sha256,
                  status='planned', dry_run=not execute, size_bytes=sum(entry['size'] for entry in entries),
                  warnings=warnings, asset_files_downloaded=False,
                  created=datetime.now(timezone.utc).isoformat())
    if shutil.disk_usage(root).free < result['size_bytes'] + DISK_RESERVE_BYTES:
        raise ValueError('Not enough free space in the Unity project for this import.')
    _safe_destination(root, 'AtlasImports/requests')
    _safe_destination(root, 'AtlasImports/staging')
    _safe_destination(root, 'Assets/Atlas/Imported/' + safe_id)
    if not execute:
        return result
    # Installing the trusted helper is part of an explicitly executed import.
    configure(c, root)
    requests = _safe_destination(root, 'AtlasImports/requests', create=True)
    staging = _safe_destination(root, 'AtlasImports/staging', create=True)
    _safe_destination(root, 'AtlasImports/reports', create=True)
    destination_parent = _safe_destination(root, 'Assets/Atlas/Imported/' + safe_id, create=True)
    destination = destination_parent / job_id
    temporary = Path(tempfile.mkdtemp(prefix=job_id + '-', dir=staging))
    bytes_done, last_progress = 0, time.monotonic()
    copy_stage = 'Copying and extracting files' if any(entry['member'] for entry in entries) else 'Copying files'
    try:
        progress(0, result['size_bytes'], copy_stage)
        for entry in entries:
            output = temporary / 'Source' / entry['name']
            output.parent.mkdir(parents=True, exist_ok=True)
            copied = 0
            archive = zipfile.ZipFile(entry['source']) if entry['member'] else None
            try:
                with (archive.open(entry['member']) if archive else entry['source'].open('rb')) as inp, output.open('xb') as out:
                    while chunk := inp.read(256 * 1024):
                        copied += len(chunk)
                        if copied > entry['size'] or copied > MAX_UNPACKED_BYTES:
                            raise ValueError('Source size changed during import.')
                        out.write(chunk)
                        bytes_done += len(chunk)
                        now = time.monotonic()
                        if now - last_progress >= 0.1:
                            progress(bytes_done, result['size_bytes'], copy_stage)
                            last_progress = now
                if copied != entry['size']:
                    raise ValueError('Source size changed during import.')
            finally:
                if archive:
                    archive.close()
        progress(bytes_done, result['size_bytes'], copy_stage)
        progress(None, None, 'Verifying copied source')
        for relative, checksum in hashes.items():
            original = source / relative if source.is_dir() else source
            if original.is_symlink() or _digest(original) != checksum:
                raise ValueError('Source changed during import; retry with the completed local download.')
        temporary.rename(destination)
        result.update(status='queued', dry_run=False, queue_path=str(requests / (job_id + '.json')))
        # Save durable ownership before queue publication; remove it if publication fails.
        _save_job(c, result)
        _atomic_bytes(requests / (job_id + '.json'), json.dumps(request, indent=2).encode())
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(destination, ignore_errors=True)
        c.set_setting('unity_import_jobs', json.dumps([j for j in _jobs(c) if j.get('job_id') != job_id]))
        raise
    progress(0, 100, 'Waiting for Unity')
    result['editor_wakeup'] = _wake_editor(root, editor_open=editor_open)
    _save_job(c, result)
    return _status(result)
