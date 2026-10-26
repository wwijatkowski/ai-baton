"""Windows: fill in the environment when a hook starts with an empty one.

Codex on Windows starts hook commands with a cleared environment (no USERPROFILE, PATH, SYSTEMROOT or TEMP), so
Python cannot find the home folder and git is not on PATH. The missing values come from Windows itself: the profile
and Windows folders from the shell API, PATH and TEMP from the user's and the system's registered environment.
Values that are set are never changed.
"""
import os


def restore():
    if os.name != 'nt':
        return
    import ctypes
    import winreg

    def folder(csidl):
        buffer = ctypes.create_unicode_buffer(260)
        ok = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) == 0
        return buffer.value if ok and buffer.value else None

    def registered(name):
        """(system value, user value) of a registered environment variable, expanded."""
        values = []
        for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
                          (winreg.HKEY_CURRENT_USER, 'Environment')):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    values.append(winreg.ExpandEnvironmentStrings(str(winreg.QueryValueEx(handle, name)[0])))
            except OSError:
                values.append('')
        return values

    def setdefault(name, value):
        if value and not os.environ.get(name):
            os.environ[name] = value

    try:
        setdefault('SYSTEMROOT', folder(0x24))  # CSIDL_WINDOWS
        setdefault('USERPROFILE', folder(0x28))  # CSIDL_PROFILE
        setdefault('APPDATA', folder(0x1a))  # CSIDL_APPDATA
        setdefault('LOCALAPPDATA', folder(0x1c))  # CSIDL_LOCAL_APPDATA
        setdefault('COMSPEC', os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'System32', 'cmd.exe'))
        system, user = registered('Path')
        setdefault('PATH', ';'.join(p for p in (system, user) if p))
        setdefault('PATHEXT', registered('PATHEXT')[0])
        system_temp, user_temp = registered('TEMP')
        setdefault('TEMP', user_temp or system_temp)
        setdefault('TMP', os.environ.get('TEMP'))
    except Exception:  # noqa: BLE001 - a hook must never fail here; what is missing stays missing.
        pass
