import os
from pathlib import Path
import shutil
import subprocess
import pytest

def test_native_usb_standby_policy(tmp_path):
    """Execute the actual firmware state machine on the host compiler."""
    source=Path(__file__).parent/'cpp/test_monitor_power.cpp'
    include=Path(__file__).resolve().parents[2]/'firmware/rlcd_client'
    binary=tmp_path/('power-test.exe' if os.name=='nt' else 'power-test')
    compiler=shutil.which('g++') or shutil.which('clang++')
    if compiler:
        result=subprocess.run([compiler,'-std=c++11','-I',str(include),str(source),'-o',str(binary)],capture_output=True,text=True)
    else:
        vswhere=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft Visual Studio/Installer/vswhere.exe'
        if not vswhere.exists(): pytest.skip('C++ compiler not installed')
        install=subprocess.check_output([str(vswhere),'-latest','-products','*','-requires','Microsoft.VisualStudio.Component.VC.Tools.x86.x64','-property','installationPath'],text=True).strip()
        if not install: pytest.skip('MSVC not installed')
        setup=Path(install)/'VC/Auxiliary/Build/vcvars64.bat'
        command=f'call "{setup}" >nul && cl /nologo /EHsc /I"{include}" "{source}" /Fe:"{binary}" /Fo:"{tmp_path / "power.obj"}"'
        (tmp_path/'build-power-test.cmd').write_text('@echo off\n'+command+'\n',encoding='utf-8')
        result=subprocess.run(['cmd','/d','/c','build-power-test.cmd'],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    subprocess.run([str(binary)],check=True,timeout=10)
