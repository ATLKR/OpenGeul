"""Test-only WebView2 debugging configuration for disposable Windows runners.

Runtime 150+ ignores user-scoped overrides for elevated hosts. Microsoft documents
an app-specific HKLM override for that case; no production code or security policy
is modified. Non-elevated local tests use process environment variables instead.
"""
from __future__ import annotations
from typing import Protocol


def debug_arguments(port: int, *, accessibility: bool=False) -> str:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Invalid loopback debugging port')
    if type(accessibility) is not bool:
        raise ValueError('Accessibility must be a boolean, not arbitrary browser arguments')
    return f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={port}' + (' --force-renderer-accessibility=complete' if accessibility else '')


class Registry(Protocol):
    def read(self, category: str, app: str) -> str: ...
    def write(self, category: str, app: str, value: str) -> None: ...
    def delete(self, category: str, app: str) -> None: ...


class MachineRegistry:
    """Access only the documented 64-bit WebView2 override subkeys."""
    @staticmethod
    def _path(category: str) -> str:
        if category not in ('AdditionalBrowserArguments', 'UserDataFolder'):
            raise ValueError('Unapproved WebView2 override category')
        return 'SOFTWARE\\Policies\\Microsoft\\Edge\\WebView2\\' + category

    def read(self, category: str, app: str) -> str:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self._path(category), 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, app)[0]

    def write(self, category: str, app: str, value: str) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, self._path(category), 0,
                               winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
            winreg.SetValueEx(key, app, 0, winreg.REG_SZ, value)

    def delete(self, category: str, app: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, self._path(category), 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as key:
            winreg.DeleteValue(key, app)


class ScopedDebugOverride:
    def __init__(self, registry: Registry, app: str, port: int, profile: str, *, runner: bool, accessibility: bool=False):
        if app != 'OpenGeul.exe':
            raise ValueError('Only the exact OpenGeul.exe test application is allowed')
        self.registry, self.app, self.runner = registry, app, runner
        self.values = [('AdditionalBrowserArguments', debug_arguments(port, accessibility=accessibility)), ('UserDataFolder', profile)]
        self.written: list[tuple[str, str]] = []

    def __enter__(self):
        if not self.runner:
            raise RuntimeError('Machine overrides are permitted only on a disposable GitHub runner; run local UI tests non-elevated')
        for category, _ in self.values:
            try:
                self.registry.read(category, self.app)
            except FileNotFoundError:
                continue
            raise RuntimeError(f'Refusing to overwrite existing {category} for {self.app}')
        try:
            for category, value in self.values:
                self.registry.write(category, self.app, value)
                self.written.append((category, value))
        except BaseException:
            self.close()
            raise
        return self

    def close(self) -> None:
        errors: list[str] = []
        while self.written:
            category, expected = self.written.pop()
            try:
                actual = self.registry.read(category, self.app)
                if actual != expected:
                    errors.append(f'{category} changed outside this test; left untouched')
                    continue
                self.registry.delete(category, self.app)
            except FileNotFoundError:
                pass
            except OSError as error:
                errors.append(f'{category} cleanup failed: {error}')
        if errors:
            raise RuntimeError('; '.join(errors))

    def __exit__(self, *_):
        self.close()
