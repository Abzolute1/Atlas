import json
import os
from pathlib import Path
import stat
import sys
import zipfile

import pytest

from scanatlas.catalog import Catalog
from scanatlas import unity_import as unity


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(unity.shutil, 'which', lambda name: None)
    monkeypatch.setattr(unity, '_process_running_project_paths', lambda proc_root=Path('/proc'): [])
    c = Catalog(tmp_path / 'catalog.sqlite')
    a = dict(id='rock', name='Rock', kind='3D Assets', subtype='', categories='', tags='',
             maxres=2048, preview='', tiny='', detail={'source': 'polyhaven', 'files': [
                 {'name': 'textures/color.png', 'type': 'albedo'}]})
    c.upsert(a)
    c.c.commit()
    project = tmp_path / 'Unity Project'
    (project / 'Assets').mkdir(parents=True)
    (project / 'ProjectSettings').mkdir()
    (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.0.0f1')
    helper = tmp_path / 'AtlasImporter.cs'
    helper.write_text(unity.HELPER_MARKER + '\n// test helper')
    monkeypatch.setattr(unity, 'HELPER', helper)
    downloads = tmp_path / 'OS Downloads'
    downloads.mkdir()
    yield c, project, downloads
    c.close()


def downloaded(c, folder, quality='Medium', files=None):
    folder.mkdir(exist_ok=True)
    files = files or {'Rock.fbx': b'FBX bytes', 'textures/color.png': b'PNG bytes'}
    for name, content in files.items():
        path = folder / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(content)
    (folder / 'download.json').write_text(json.dumps({'id': 'rock', 'quality': quality, 'files': list(files)}))
    c.record_download('rock', quality, folder)
    return folder


def archive(folder, entries):
    path = folder / 'rock.zip'
    with zipfile.ZipFile(path, 'w') as out:
        for name, value in entries.items():
            out.writestr(name, value)
    return path


def snapshot(project):
    return {p.relative_to(project).as_posix(): p.read_bytes() for p in project.rglob('*') if p.is_file()}


def test_configure_validates_and_protects_foreign_helpers(setup):
    c, project, _ = setup
    assert not unity.project_info(c)['valid']
    with pytest.raises(ValueError):
        unity.configure(c, project.parent)
    assert c.setting('unity_project') == ''
    folder = project / 'Assets/Atlas/Editor'
    folder.mkdir(parents=True)
    helper = folder / 'AtlasImporter.cs'
    helper.write_text('// different user code')
    with pytest.raises(FileExistsError, match='different script'):
        unity.configure(c, project)
    assert helper.read_text() == '// different user code'
    helper.write_text(unity.HELPER_MARKER + '\n// old version')
    result = unity.configure(c, project)
    assert result['valid'] and result['helper_installed']
    assert helper.read_bytes() == unity.HELPER.read_bytes()
    assert c.setting('unity_project') == str(project)


def test_configure_installs_pipeline_bridge_when_unity_cli_is_available(setup, monkeypatch, tmp_path):
    c, project, _ = setup
    cli = tmp_path / 'unity'
    cli.write_text(
        '#!' + sys.executable + '\n'
        'import json, pathlib, sys\n'
        'root = pathlib.Path(sys.argv[sys.argv.index("--project-path") + 1])\n'
        'manifest = root / "Packages/manifest.json"\n'
        'manifest.parent.mkdir(parents=True, exist_ok=True)\n'
        'manifest.write_text(json.dumps({"dependencies": {"com.unity.pipeline": "0.8.0-exp.1"}}))\n'
        'print(json.dumps({"success": True}))\n')
    cli.chmod(0o755)
    monkeypatch.setattr(unity.shutil, 'which', lambda name: str(cli) if name == 'unity' else None)

    result = unity.configure(c, project)

    assert result['helper_installed'] and result['pipeline_package_installed']
    assert json.loads((project / 'Packages/manifest.json').read_text())['dependencies']['com.unity.pipeline']


def test_hub_editor_process_scan_finds_project_without_exposing_command_line(tmp_path, monkeypatch):
    project = tmp_path / 'Open Project'
    (project / 'Assets').mkdir(parents=True)
    (project / 'ProjectSettings').mkdir()
    (project / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.0.0f1')
    proc = tmp_path / 'proc'
    process = proc / '1234'
    process.mkdir(parents=True)
    (process / 'exe').symlink_to('/opt/Unity/Hub/Editor/6000.6.2f1/Editor/Unity')
    (process / 'cmdline').write_bytes(
        b'/opt/Unity/Hub/Editor/6000.6.2f1/Editor/Unity\0-projectPath\0' +
        os.fsencode(project) + b'\0-licenseToken\0private-value\0')
    monkeypatch.setattr(unity.sys, 'platform', 'linux')

    assert unity._process_running_project_paths(proc) == [str(project)]


def test_multiple_open_projects_require_an_explicit_target(setup, monkeypatch, tmp_path):
    c, project, _ = setup
    other = tmp_path / 'Other Unity Project'
    (other / 'Assets').mkdir(parents=True)
    (other / 'ProjectSettings').mkdir()
    (other / 'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: 6000.0.0f1')
    monkeypatch.setattr(unity, '_running_project_paths', lambda refresh=False: [str(project), str(other)])

    assert unity.project_info(c, refresh=True)['source'] == 'ambiguous'
    with pytest.raises(ValueError, match='Multiple Unity Editor projects'):
        unity.submit(c, 'rock')
    assert unity._select_project(c, other)[0] == other


def test_dry_run_has_no_mutations_or_network(setup, monkeypatch):
    c, project, downloads = setup
    downloaded(c, downloads)
    before = snapshot(project)
    monkeypatch.setattr('requests.get', lambda *a, **kw: pytest.fail('Import cannot download assets'))
    result = unity.submit(c, 'rock', project)
    assert result['dry_run'] and result['status'] == 'planned'
    assert result['files'] == [{'path': 'Source/Rock.fbx', 'role': 'mesh'},
                               {'path': 'Source/textures/color.png', 'role': 'albedo'}]
    assert snapshot(project) == before
    assert c.setting('unity_project') == '' and c.setting('unity_import_jobs') == ''


def test_atomic_request_preserves_download_and_reuses_job(setup, monkeypatch):
    c, project, downloads = setup
    downloaded(c, downloads)
    original = snapshot(downloads)
    replace = os.replace
    published = []
    def checked_replace(src, dst):
        if Path(dst).parent.name == 'requests':
            assert Path(src).suffix == '.tmp'
            assert not list(Path(dst).parent.glob('*.json'))
            request = json.loads(Path(src).read_text())
            for entry in request['files']:
                assert (project / request['asset_folder'] / entry['path']).is_file()
            published.append(dst)
        return replace(src, dst)
    monkeypatch.setattr(unity.os, 'replace', checked_replace)
    result = unity.submit(c, 'rock', project, execute=True)
    assert result['status'] == 'queued' and len(published) == 1
    copied = project / result['asset_folder'] / 'Source/Rock.fbx'
    assert copied.read_bytes() == (downloads / 'Rock.fbx').read_bytes()
    assert copied.stat().st_ino != (downloads / 'Rock.fbx').stat().st_ino
    again = unity.submit(c, 'rock', execute=True)
    assert again['reused'] and again['job_id'] == result['job_id']
    assert snapshot(downloads) == original
    report = project / 'AtlasImports/reports' / (result['job_id'] + '.json')
    report.write_text(json.dumps({'job_id': result['job_id'], 'status': 'complete', 'prefab': 'result.prefab'}))
    done = unity.job_status(c, result['job_id'])['jobs'][0]
    assert done['status'] == 'complete' and done['prefab'] == 'result.prefab'
    assert unity.submit(c, 'rock', execute=True)['status'] == 'complete'


def test_exact_quality_and_incomplete_download_handling(setup):
    c, project, downloads = setup
    downloaded(c, downloads / 'high', 'High')
    assert not unity.available_local(c, 'rock')['available']
    assert unity.available_local(c, 'rock', 'High')['available']
    with pytest.raises(ValueError, match='Medium'):
        unity.submit(c, 'rock', project)
    medium = downloaded(c, downloads / 'medium')
    (medium / 'Rock.fbx').unlink()
    assert not unity.available_local(c, 'rock')['available']
    with pytest.raises(ValueError, match='quality'):
        unity.submit(c, 'rock', project, source=downloads / 'high')
    with pytest.raises(ValueError, match='Unknown quality'):
        unity.available_local(c, 'rock', 'Unexpected')


@pytest.mark.parametrize('name', ['../escape.fbx', '/absolute.fbx', 'C:/drive.fbx', 'folder\\escape.fbx'])
def test_zip_traversal_is_rejected_before_mutations(setup, name):
    c, project, downloads = setup
    source = archive(downloads, {'Rock.fbx': b'fbx', name: b'unsafe'})
    before = snapshot(project)
    with pytest.raises(ValueError, match='Unsafe'):
        unity.submit(c, 'rock', project, source=source, execute=True)
    assert snapshot(project) == before


def test_zip_allowlist_and_nested_archives_preserve_paths(setup):
    c, project, downloads = setup
    source = archive(downloads, {'model/Rock.obj': b'obj', 'model/Rock.mtl': b'mtl',
                                'model/Textures/color.png': b'png', 'evil.cs': b'code',
                                'model/Rock.obj.meta': b'guid', 'package.unitypackage': b'package',
                                'scene.prefab': b'prefab', 'mesh.asset': b'asset', 'source.blend': b'blend',
                                'nested.zip': b'zip', 'run.exe': b'exe'})
    result = unity.submit(c, 'rock', project, source=source, execute=True)
    copied = project / result['asset_folder'] / 'Source'
    assert set(snapshot(copied)) == {'model/Rock.obj', 'model/Rock.mtl', 'model/Textures/color.png'}
    assert any('Nested ZIP' in warning for warning in result['warnings'])
    assert source.is_file()


def test_zip_symlinks_and_size_limits_are_rejected(setup, monkeypatch):
    c, project, downloads = setup
    source = downloads / 'unsafe.zip'
    with zipfile.ZipFile(source, 'w') as out:
        link = zipfile.ZipInfo('bad.fbx')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        out.writestr(link, '../target')
    with pytest.raises(ValueError, match='symbolic'):
        unity.submit(c, 'rock', project, source=source, execute=True)
    source = archive(downloads, {'Rock.fbx': b'12345678'})
    monkeypatch.setattr(unity, 'MAX_UNPACKED_BYTES', 4)
    with pytest.raises(ValueError, match='limit'):
        unity.submit(c, 'rock', project, source=source, execute=True)
    assert not (project / 'AtlasImports').exists()


def test_no_false_success_for_unsupported_or_texture_only_model(setup):
    c, project, downloads = setup
    source = archive(downloads, {'Rock.blend': b'blend'})
    with pytest.raises(ValueError, match='No supported'):
        unity.submit(c, 'rock', project, source=source, execute=True)
    source = archive(downloads, {'texture.png': b'png'})
    with pytest.raises(ValueError, match='no supported FBX or OBJ'):
        unity.submit(c, 'rock', project, source=source, execute=True)
    assert not (project / 'AtlasImports').exists()


def test_changed_source_and_failed_report_create_separate_imports(setup):
    c, project, downloads = setup
    downloaded(c, downloads)
    first = unity.submit(c, 'rock', project, execute=True)
    (downloads / 'Rock.fbx').write_bytes(b'new FBX')
    second = unity.submit(c, 'rock', execute=True)
    assert first['asset_folder'] != second['asset_folder']
    assert (project / first['asset_folder'] / 'Source/Rock.fbx').read_bytes() == b'FBX bytes'
    assert (project / second['asset_folder'] / 'Source/Rock.fbx').read_bytes() == b'new FBX'
    report = project / 'AtlasImports/reports' / (second['job_id'] + '.json')
    report.write_text(json.dumps({'status': 'failed', 'error': 'Bad model'}))
    assert unity.job_status(c, second['job_id'])['jobs'][0]['error'] == 'Bad model'
    third = unity.submit(c, 'rock', execute=True)
    assert third['job_id'] not in (first['job_id'], second['job_id'])
    assert unity.job_status(c)['jobs'][0]['job_id'] == third['job_id']


def test_mixamo_bundle_uses_original_quality_and_excludes_sources(setup):
    c, project, downloads = setup
    (downloads / 'Character.fbx').write_bytes(b'fbx')
    (downloads / 'Character.blend').write_bytes(b'blend')
    a = c.get('rock')
    a['kind'] = 'Characters'
    a['detail'] = {'source': 'mixamo', 'local_file': str(downloads / 'Character.fbx'),
                   'bundle_root': str(downloads), 'bundle_files': [{'name': 'Character.fbx'}, {'name': 'Character.blend'}]}
    c.upsert(a)
    c.c.commit()
    assert unity.available_local(c, a)['quality'] == 'Original'
    result = unity.submit(c, 'rock', project, execute=True)
    assert result['quality'] == 'Original'
    assert result['files'] == [{'path': 'Source/Character.fbx', 'role': 'mesh'}]
    (downloads / 'Character.fbx').unlink()
    assert not unity.available_local(c, a)['available']


def test_destination_symlink_and_low_disk_space_are_rejected(setup, monkeypatch):
    c, project, downloads = setup
    downloaded(c, downloads)
    (project / 'AtlasImports').symlink_to(downloads, target_is_directory=True)
    with pytest.raises(ValueError, match='symbolic'):
        unity.submit(c, 'rock', project, execute=True)
    (project / 'AtlasImports').unlink()
    usage = unity.shutil.disk_usage(project)
    monkeypatch.setattr(unity.shutil, 'disk_usage', lambda _: type(usage)(100, 100, 0))
    with pytest.raises(ValueError, match='free space'):
        unity.submit(c, 'rock', project, execute=True)
    assert not (project / 'AtlasImports').exists()


def test_manifest_rejects_linked_parent_even_when_target_is_inside_source(setup):
    c, project, downloads = setup
    downloaded(c, downloads)
    (downloads / 'alias').symlink_to(downloads / 'textures', target_is_directory=True)
    (downloads / 'download.json').write_text(json.dumps({'id': 'rock', 'quality': 'Medium',
                                                       'files': ['Rock.fbx', 'alias/color.png']}))
    assert not unity.available_local(c, 'rock')['available']
    with pytest.raises(ValueError, match='symbolic'):
        unity.submit(c, 'rock', project, source=downloads, execute=True)
    assert not (project / 'AtlasImports').exists()


def test_queue_publication_failure_cleans_copy_and_job_record(setup, monkeypatch):
    c, project, downloads = setup
    downloaded(c, downloads)
    original = snapshot(downloads)
    replace = os.replace
    def fail_request(src, dst):
        if Path(dst).parent.name == 'requests':
            raise OSError('simulated queue write error')
        return replace(src, dst)
    monkeypatch.setattr(unity.os, 'replace', fail_request)
    with pytest.raises(OSError, match='queue write error'):
        unity.submit(c, 'rock', project, execute=True)
    assert not list((project / 'AtlasImports/requests').iterdir())
    assert not list((project / 'AtlasImports/staging').iterdir())
    assert not list((project / 'Assets/Atlas/Imported/rock').iterdir())
    assert unity.job_status(c)['jobs'] == []
    assert snapshot(downloads) == original


def test_helper_update_invalidates_completed_import_reuse(setup):
    c, project, downloads = setup
    downloaded(c, downloads)
    first = unity.submit(c, 'rock', project, execute=True)
    report = project / 'AtlasImports/reports' / (first['job_id'] + '.json')
    report.write_text(json.dumps({'job_id': first['job_id'], 'status': 'complete'}))
    assert unity.submit(c, 'rock', execute=True)['job_id'] == first['job_id']
    unity.HELPER.write_text(unity.HELPER_MARKER + '\n// fixed material handling')
    second = unity.submit(c, 'rock', execute=True)
    assert second['job_id'] != first['job_id']
    assert second['helper_sha256'] != first['helper_sha256']
    assert unity.submit(c, 'rock', execute=True)['job_id'] == second['job_id']
    assert (project / 'Assets/Atlas/Editor/AtlasImporter.cs').read_bytes() == unity.HELPER.read_bytes()
    assert (project / first['asset_folder']).is_dir()


def test_explicit_material_bindings_are_queued_and_invalidate_reuse(setup):
    c, project, downloads = setup
    downloaded(c, downloads)
    first = unity.submit(c, 'rock', project, execute=True)
    a = c.get('rock')
    bindings = [{'material': 'Ch15_body', 'texture_set': 'Ch15_1001'},
                {'material': 'Ch15_body1', 'texture_set': 'Ch15_1002'}]
    a['detail']['unity_material_bindings'] = bindings
    c.upsert(a)
    c.c.commit()
    second = unity.submit(c, 'rock', execute=True)
    assert second['job_id'] != first['job_id']
    assert json.loads(Path(second['queue_path']).read_text())['material_bindings'] == bindings
    assert unity.submit(c, 'rock', execute=True)['job_id'] == second['job_id']
    a['detail']['unity_material_bindings'] = list(reversed(bindings))
    c.upsert(a)
    c.c.commit()
    assert unity.submit(c, 'rock', execute=True)['job_id'] == second['job_id']


@pytest.mark.parametrize('bindings', [None, 'invalid', [{}], [{'material': 'Body', 'texture_set': 2}],
    [{'material': '', 'texture_set': 'Body'}], [{'material': 'Body\n', 'texture_set': 'Body'}],
    [{'material': 'Body', 'texture_set': 'A'}, {'material': 'Body', 'texture_set': 'B'}]])
def test_invalid_material_bindings_fail_before_mutations(setup, bindings):
    c, project, downloads = setup
    downloaded(c, downloads)
    a = c.get('rock')
    a['detail']['unity_material_bindings'] = bindings
    c.upsert(a)
    c.c.commit()
    before = snapshot(project)
    with pytest.raises(ValueError, match='binding'):
        unity.submit(c, 'rock', project, execute=True)
    assert snapshot(project) == before


def test_transfer_progress_uses_actual_bytes_then_waits_for_unity(setup, monkeypatch):
    c, project, downloads = setup
    source = archive(downloads, {'Rock.fbx': b'x' * 800000, 'color.png': b'y' * 300000})
    events = []
    monkeypatch.setattr(unity.time, 'monotonic', lambda: 1.0)
    result = unity.submit(c, 'rock', project, source=source, execute=True,
                          progress=lambda done, total, stage: events.append((done, total, stage)))
    assert events[:2] == [(None, None, 'Checking local source'), (None, None, 'Planning import')]
    copies = [event for event in events if event[2] == 'Copying and extracting files']
    assert copies == [(0, 1100000, 'Copying and extracting files'),
                      (1100000, 1100000, 'Copying and extracting files')]
    assert events[-2:] == [(None, None, 'Verifying copied source'), (0, 100, 'Waiting for Unity')]
    assert result['progress_percent'] == 0 and result['progress_estimated']
    report = Path(result['report_path'])
    report.write_text(json.dumps({'status': 'complete'}))
    complete = unity.job_status(c, result['job_id'])['jobs'][0]
    assert complete['progress_percent'] == 100 and complete['stage'] == 'Complete'


def test_download_cli_progress_known_unknown_and_complete(setup, monkeypatch, capsys):
    from scanatlas import agent
    c, _, downloads = setup
    a = c.get('rock')
    jobs = [agent.new_job(c, a, {'quality': 'Medium', 'bytes': total}, downloads) for total in (400, 0, 0)]
    agent.job_update(c, jobs[0], status='downloading', bytes_done=100)
    agent.job_update(c, jobs[1], status='downloading', bytes_done=100)
    agent.job_update(c, jobs[2], status='complete', bytes_done=100)
    monkeypatch.setattr('sys.argv', ['atlas', '--database', str(c.path), 'status'])
    agent.main()
    rows = {row['id']: row for row in json.loads(capsys.readouterr().out)['jobs']}
    assert [rows[job]['progress_percent'] for job in jobs] == [25, None, 100]


def test_editor_wakeup_targets_ready_project_once_and_persists_acknowledgement(setup, monkeypatch):
    from types import SimpleNamespace
    c, project, downloads = setup
    downloaded(c, downloads)
    (project / 'Packages').mkdir()
    (project / 'Packages/manifest.json').write_text(json.dumps({'dependencies': {'com.unity.pipeline': '0.8.0-exp.1'}}))
    monkeypatch.setattr(unity.shutil, 'which', lambda name: '/mock/unity')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert args[args.index('--project-path') + 1] == str(project)
        assert args[args.index('--timeout') + 1] == '2' and kwargs['timeout'] == 2.5
        assert kwargs['stdin'] == unity.subprocess.DEVNULL and kwargs['capture_output']
        result = ({'status': 'ready', 'projectPath': str(project), 'playMode': 'stopped',
                   'compiling': False, 'domainReloadInProgress': False} if args[2] == 'editor_status'
                  else {'status': 'compiling'})
        return SimpleNamespace(returncode=0, stdout=json.dumps({'success': True, 'data': {'success': True, 'result': result}}))
    monkeypatch.setattr(unity.subprocess, 'run', run)
    result = unity.submit(c, 'rock', project, execute=True, editor_open=True)
    assert [args[2] for args in calls] == ['editor_status', 'recompile']
    assert result['status'] == 'queued' and result['editor_wakeup']['status'] == 'requested'
    assert result['editor_wakeup']['reason'] == 'refresh_acknowledged'
    assert 'acknowledged' in result['note']
    assert unity.job_status(c, result['job_id'])['jobs'][0]['editor_wakeup'] == result['editor_wakeup']
    assert unity.submit(c, 'rock', execute=True)['reused']
    assert len(calls) == 2


def test_open_editor_without_cli_gets_refresh_fallback(setup):
    _, project, _ = setup
    result = unity._wake_editor(project, editor_open=True)
    assert result['status'] == 'requested' and result['reason'] == 'open_editor_watch'
    assert 'Assets > Refresh' in result['note']


@pytest.mark.parametrize('state,play,reason', [('playing', 'playing', 'play_mode'),
    ('playing', 'paused', 'play_mode'), ('compiling', 'stopped', 'editor_busy')])
def test_editor_wakeup_never_refreshes_playing_or_busy_editor(setup, monkeypatch, state, play, reason):
    from types import SimpleNamespace
    _, project, _ = setup
    monkeypatch.setattr(unity.shutil, 'which', lambda name: '/mock/unity')
    def run(args, **kwargs):
        assert args[2] == 'editor_status'
        result = {'status': state, 'playMode': play, 'projectPath': str(project)}
        return SimpleNamespace(returncode=0, stdout=json.dumps({'success': True, 'data': {'result': result}}))
    monkeypatch.setattr(unity.subprocess, 'run', run)
    result = unity._wake_editor(project)
    assert result['status'] == 'deferred' and result['reason'] == reason


def test_editor_wakeup_timeout_keeps_queued_assets_and_actionable_note(setup, monkeypatch):
    c, project, downloads = setup
    downloaded(c, downloads)
    monkeypatch.setattr(unity.shutil, 'which', lambda name: '/mock/unity')
    def run(args, **kwargs):
        raise unity.subprocess.TimeoutExpired(args, kwargs['timeout'])
    monkeypatch.setattr(unity.subprocess, 'run', run)
    result = unity.submit(c, 'rock', project, execute=True)
    assert result['status'] == 'queued' and result['editor_wakeup']['reason'] == 'timeout'
    assert Path(result['queue_path']).is_file()
    assert (project / result['asset_folder'] / 'Source/Rock.fbx').is_file()
    assert 'Assets > Refresh' in result['note']
