import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest
from model_fixture import write_forest
from app import startup

ROOT=Path(__file__).resolve().parents[2]
BASH=shutil.which("bash") if os.name!="nt" else r"C:\Program Files\Git\bin\bash.exe"

def environment(tmp_path,monkeypatch):
    model,c=write_forest(tmp_path)
    contract=tmp_path/"model.json";contract.write_text(json.dumps(c))
    monkeypatch.setenv("WILDFYRE_MODEL_CONTRACT",str(contract))
    monkeypatch.setenv("WILDFYRE_MODEL_ARTIFACT",str(model))
    monkeypatch.delenv("FIRMS_MAP_KEY",raising=False)
    return model

@pytest.mark.parametrize("flag",["--sample","--live"])
def test_startup_valid_cache_never_downloads_and_key_stays_private(tmp_path,monkeypatch,capsys,flag):
    environment(tmp_path,monkeypatch)
    monkeypatch.setattr(startup,"prepare_artifact",lambda *a:pytest.fail("valid cache downloaded"))
    monkeypatch.setattr(startup.getpass,"getpass",lambda *a:pytest.fail("unexpected prompt"))
    if flag=="--live":monkeypatch.setenv("FIRMS_MAP_KEY","test-secret")
    runs=[]
    monkeypatch.setattr(startup.uvicorn,"run",lambda app,**kwargs:runs.append((app,kwargs)))
    assert startup.main([flag])==0
    assert runs[0][1]=={"host":"127.0.0.1","port":8000}
    assert "test-secret" not in capsys.readouterr().out

def test_hidden_prompt_only_when_live_key_missing(tmp_path,monkeypatch,capsys):
    environment(tmp_path,monkeypatch)
    monkeypatch.setattr(startup.sys.stdin,"isatty",lambda:True)
    prompts=[]
    monkeypatch.setattr(startup.getpass,"getpass",lambda prompt:prompts.append(prompt) or "private-key")
    monkeypatch.setattr(startup.uvicorn,"run",lambda *a,**kw:None)
    assert startup.main(["--live"])==0
    assert len(prompts)==1
    assert "private-key" not in str(capsys.readouterr())

def test_noninteractive_missing_key_fails_without_echo_prompt(tmp_path,monkeypatch,capsys):
    environment(tmp_path,monkeypatch)
    monkeypatch.setattr(startup.sys.stdin,"isatty",lambda:False)
    monkeypatch.setattr(startup.getpass,"getpass",lambda *a:pytest.fail("unsafe prompt"))
    assert startup.main(["--live"])==1

def test_unknown_flag_has_no_side_effect(monkeypatch):
    monkeypatch.setattr(startup,"prepare_artifact",lambda *a:pytest.fail("prepared"))
    with pytest.raises(SystemExit) as err:startup.main(["--unknown"])
    assert err.value.code==2

@pytest.mark.parametrize("error",[ValueError("secret https://secret"),OSError("private-path")])
def test_failed_preparation_never_starts_server(tmp_path,monkeypatch,capsys,error):
    model=environment(tmp_path,monkeypatch);model.unlink()
    def fail(*args):raise error
    monkeypatch.setattr(startup,"prepare_artifact",fail)
    monkeypatch.setattr(startup.uvicorn,"run",lambda *a,**kw:pytest.fail("started"))
    assert startup.main(["--sample"])==1
    text=str(capsys.readouterr())
    assert "secret" not in text and "private-path" not in text

@pytest.mark.skipif(not BASH or not Path(BASH).exists(),reason="Bash unavailable")
@pytest.mark.parametrize("install",[False,True])
def test_launcher_resolves_spaces_other_cwd_and_installs_only_if_needed(tmp_path,install):
    repo=tmp_path/"repo with spaces";repo.mkdir()
    shutil.copyfile(ROOT/"run.sh",repo/"run.sh")
    backend=repo/"backend";(backend/".venv/bin").mkdir(parents=True)
    (backend/"requirements.txt").write_text("fastapi==0.143.3\n")
    fake=backend/".venv/bin/python"
    fake.write_text("""#!/usr/bin/env bash
case "$*" in
  *"app.startup"*) printf '%s\\n' "$PWD|$*" > "$WF_TEST_LOG"; exit 0 ;;
  *"-m pip"*) printf 'installed' > "$WF_TEST_PIP"; exit 0 ;;
  *) test "$WF_TEST_INSTALL" != 1 ;;
esac
""",newline="\n")
    fake.chmod(0o755)
    log=tmp_path/"started";pip=tmp_path/"pip"
    env={**os.environ,"WF_TEST_LOG":str(log),"WF_TEST_PIP":str(pip),"WF_TEST_INSTALL":"1" if install else "0"}
    result=subprocess.run([BASH,str(repo/"run.sh"),"--sample"],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert "backend|-m app.startup --sample" in log.read_text().replace("\\","/")
    assert pip.exists()==install
