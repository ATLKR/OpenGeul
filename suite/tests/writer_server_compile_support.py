"""Bounded portable fixtures; compiler absence never certifies a Windows engine."""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from native_executable_cleanup import remove_completed_image


def require_compiler():
    for name in ('c++','g++','clang++'):
        compiler=shutil.which(name)
        if compiler:return compiler
    raise unittest.SkipTest('Portable C++ compiler unavailable; actual Windows engine verification remains pending')


class CompletedFixture:
    def __init__(self,image):
        self.image=image
        self.last=None

    def run(self,*,input=None,seconds=5):
        if not 0<seconds<=15:raise ValueError('Portable run limit must be within15 seconds')
        self.last=subprocess.run([str(self.image)],input=input,cwd=self.image.parent,
            capture_output=True,text=True,timeout=seconds)
        return self.last


@contextmanager
def compiled_fixture(case,source,*,includes=(),extra_flags=()):
    compiler=require_compiler()
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        image=root/('writer-fixture.exe' if os.name=='nt' else 'writer-fixture')
        command=[compiler,'-std=c++17','-Wall','-Wextra','-Werror','-pthread',*extra_flags]
        for path in includes:command.extend(['-I',str(path)])
        command.extend([str(source),'-o',str(image)])
        built=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=30)
        case.assertEqual(built.returncode,0,built.stdout+built.stderr)
        fixture=CompletedFixture(image)
        try:yield fixture
        finally:
            if fixture.last is not None and image.exists():remove_completed_image(root,image,fixture.last)
