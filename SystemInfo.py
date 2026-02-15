#!/usr/bin/env python3
"""
Real‑time system resource monitor – RAM, CPU per core (utilisation, temp, clock),
disk usage, CPU fan speed, GPU temperature, battery stats, NPU detection,
CPU cache info (including total in KB), audio device, monitor details, network info,
OS details, uptime, installed browsers (with versions), disk temperatures,
LISTENING PORTS, and critical warnings (internet, low RAM, disk space, CPU/GPU overload, high disk temp).
Aesthetic table layout with baby pink borders and rainbow colours inside.
ALL TABLES ARE CENTERED on your terminal for a polished 1080p view.
Refreshes every 45 seconds. Press Ctrl+C to exit.
Compatible with CachyOS (Linux), macOS Sonoma, Windows 10/11 PowerShell, and Termux (Android).

This script will attempt to elevate to root/administrator privileges to access disk temperatures and full process info for listening ports.
"""

import psutil
import os
import time
import sys
import subprocess
import platform
import re
import socket
import urllib.request
import ipaddress
from urllib.error import URLError

# ANSI colour codes (rainbow order)
COLORS = [31, 33, 32, 34, 35, 36]   # red, yellow, green, blue, magenta, cyan
BABY_PINK = "38;5;218"               # baby pink for borders
HOT_PINK = "38;5;201"                # bright hot pink for warnings
RESET = '\033[0m'
BOLD = '\033[1m'

def color(text, code):
    """Wrap text in ANSI colour code."""
    return f'\033[{code}m{text}{RESET}'

def color_bold(text, code):
    """Wrap text in bold ANSI colour."""
    return f'\033[{code};1m{text}{RESET}'

def strip_ansi(text):
    """Remove ANSI escape sequences from a string."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)

# ----------------------------------------------------------------------
# Privilege elevation
# ----------------------------------------------------------------------

def is_admin():
    """Return True if the script is running with root/administrator privileges."""
    if platform.system() == 'Windows':
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
    else:  # Linux, macOS, etc.
        return os.geteuid() == 0

def elevate_privileges():
    """
    Attempt to re-run the script with elevated privileges (sudo on Unix, runas on Windows).
    If already elevated, does nothing.
    If elevation fails, prints a warning and continues (disk temps may be unavailable).
    """
    if is_admin():
        return  # Already elevated

    # Avoid infinite loop if we've already tried
    if os.environ.get('ELEVATED') == '1':
        print(color_bold("⚠️  Could not obtain elevated privileges. Disk temperatures may not be available.", HOT_PINK))
        return

    print("Requesting administrator privileges...")
    sys.stdout.flush()

    if platform.system() == 'Windows':
        try:
            import ctypes
            # Relaunch with runas verb
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, " ".join(sys.argv), None, 1
            )
            sys.exit(0)  # Exit this instance; new elevated instance will run
        except Exception as e:
            print(color_bold(f"⚠️  Elevation failed: {e}. Continuing without admin rights.", HOT_PINK))
            os.environ['ELEVATED'] = '1'
    else:  # Unix-like
        try:
            # Re-exec with sudo, passing the same arguments and setting ELEVATED=1
            new_env = os.environ.copy()
            new_env['ELEVATED'] = '1'
            os.execvp('sudo', ['sudo', sys.executable] + sys.argv + [])
        except Exception as e:
            print(color_bold(f"⚠️  Elevation failed: {e}. Continuing without root.", HOT_PINK))
            os.environ['ELEVATED'] = '1'

# ----------------------------------------------------------------------
# OS detection
# ----------------------------------------------------------------------
IS_WINDOWS = platform.system() == 'Windows'
IS_MAC = platform.system() == 'Darwin'
IS_LINUX = not (IS_WINDOWS or IS_MAC)

# ----------------------------------------------------------------------
# Disk temperature function (requires smartctl)
# ----------------------------------------------------------------------

def get_disk_temperatures():
    """
    Use smartctl (from smartmontools) to get disk temperatures.
    Returns a list of tuples (device, temp_celsius).
    If smartctl is not available or fails, returns empty list.
    """
    temps = []
    smartctl_cmd = 'smartctl'

    # Check if smartctl is in PATH
    try:
        subprocess.run([smartctl_cmd, '--version'], capture_output=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        return temps  # smartctl not available

    # Get list of disks based on platform
    disks = []
    if IS_LINUX:
        # Look for /dev/sdX, /dev/nvmeXnY, etc.
        for dev in os.listdir('/dev'):
            if dev.startswith('sd') and dev[2:].isdigit() is False:  # whole disk, not partition
                disks.append(f'/dev/{dev}')
            elif dev.startswith('nvme') and 'n' in dev and 'p' not in dev:  # nvme controller, not partition
                disks.append(f'/dev/{dev}')
    elif IS_MAC:
        # On macOS, disk identifiers like disk0, disk1
        for i in range(0, 10):
            disk = f'/dev/disk{i}'
            if os.path.exists(disk):
                disks.append(disk)
    elif IS_WINDOWS:
        # On Windows, smartctl can use /dev/sdX or physical drives
        # We'll try physical drives \\.\PhysicalDriveX
        for i in range(0, 10):
            disk = f'\\\\.\\PhysicalDrive{i}'
            # We can't easily check existence, so we'll try smartctl and see
            disks.append(disk)

    for disk in disks:
        try:
            # Run smartctl -A to get attributes
            result = subprocess.run(
                [smartctl_cmd, '-A', disk],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                continue
            # Parse output for temperature
            lines = result.stdout.splitlines()
            temp = None
            for line in lines:
                if 'Temperature' in line:
                    numbers = re.findall(r'(\d+)', line)
                    if numbers:
                        temp = int(numbers[-1])
                        break
                if re.search(r'194\s+Temperature_Celsius', line):
                    parts = line.split()
                    if len(parts) >= 10:
                        try:
                            temp = int(parts[9])
                            break
                        except:
                            pass
            if temp is not None:
                temps.append((disk, temp))
        except (subprocess.TimeoutExpired, subprocess.SubprocessError):
            continue

    return temps

# ----------------------------------------------------------------------
# Browser detection function – now with VERSION detection!
# ----------------------------------------------------------------------

def get_browser_version(name, path):
    """
    Attempt to get the version of a browser given its name and executable path.
    Returns version string or "N/A".
    """
    version = "N/A"
    try:
        if IS_WINDOWS:
            # On Windows, try to read file properties (ProductVersion)
            if path.lower().endswith('.exe'):
                # Use PowerShell to get file version
                ps_cmd = f'(Get-Item -Path "{path}").VersionInfo.ProductVersion'
                result = subprocess.run(
                    ['powershell', '-Command', ps_cmd],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    ver = result.stdout.strip()
                    if ver:
                        version = ver
            # Fallback: try --version
            if version == "N/A":
                result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    ver = result.stdout.strip() or result.stderr.strip()
                    if ver:
                        version = ver.splitlines()[0][:50]
        elif IS_MAC:
            # On macOS, browsers are .app bundles; try to read CFBundleShortVersionString from Info.plist
            plist_path = os.path.join(path, 'Contents', 'Info.plist')
            if os.path.exists(plist_path):
                # Use plutil to extract version (macOS has plutil built-in)
                result = subprocess.run(
                    ['plutil', '-extract', 'CFBundleShortVersionString', 'xml1', '-o', '-', plist_path],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    # Parse XML
                    match = re.search(r'<string>(.*?)</string>', result.stdout)
                    if match:
                        version = match.group(1)
            # Fallback: try --version from the actual executable inside .app
            if version == "N/A":
                exe_path = os.path.join(path, 'Contents', 'MacOS', os.path.basename(path).replace('.app', ''))
                if os.path.exists(exe_path):
                    result = subprocess.run([exe_path, '--version'], capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        ver = result.stdout.strip() or result.stderr.strip()
                        if ver:
                            version = ver.splitlines()[0][:50]
        else:  # Linux
            # Try --version
            result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                ver = result.stdout.strip() or result.stderr.strip()
                if ver:
                    version = ver.splitlines()[0][:50]
            # Also try with --version for browsers that need it
            if version == "N/A":
                result = subprocess.run([path, '-version'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    ver = result.stdout.strip() or result.stderr.strip()
                    if ver:
                        version = ver.splitlines()[0][:50]
    except Exception:
        pass
    return version

def get_installed_browsers():
    """
    Detect installed web browsers, their versions, and installation paths.
    Returns a list of tuples (browser_name, version, install_path).
    Works on Windows, macOS, Linux, and Termux.
    """
    browsers = []  # each element will be (name, version, path)

    # Helper to add if path exists, then fetch version
    def add_if_exists(name, path):
        if path and os.path.exists(path):
            version = get_browser_version(name, path)
            browsers.append((name, version, path))

    if IS_WINDOWS:
        # Common Program Files paths
        prog_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
        prog_files_x86 = os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
        local_appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~\\AppData\\Local'))
        user_desktop = os.path.expanduser('~/Desktop')

        # Existing browsers
        add_if_exists("Google Chrome", os.path.join(prog_files, 'Google', 'Chrome', 'Application', 'chrome.exe'))
        add_if_exists("Google Chrome", os.path.join(prog_files_x86, 'Google', 'Chrome', 'Application', 'chrome.exe'))
        add_if_exists("Mozilla Firefox", os.path.join(prog_files, 'Mozilla Firefox', 'firefox.exe'))
        add_if_exists("Mozilla Firefox", os.path.join(prog_files_x86, 'Mozilla Firefox', 'firefox.exe'))
        add_if_exists("Microsoft Edge", os.path.join(prog_files, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))
        add_if_exists("Microsoft Edge", os.path.join(prog_files_x86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'))
        add_if_exists("Brave", os.path.join(prog_files, 'BraveSoftware', 'Brave-Browser', 'Application', 'brave.exe'))
        add_if_exists("Opera", os.path.join(prog_files, 'Opera', 'launcher.exe'))
        add_if_exists("Vivaldi", os.path.join(prog_files, 'Vivaldi', 'Application', 'vivaldi.exe'))

        # Floorp
        floorp_paths = [
            os.path.join(local_appdata, 'floorp', 'floorp.exe'),
            os.path.join(prog_files, 'Floorp', 'floorp.exe'),
            os.path.join(prog_files_x86, 'Floorp', 'floorp.exe'),
        ]
        for path in floorp_paths:
            add_if_exists("Floorp", path)

        # Tor Browser
        tor_paths = [
            os.path.join(user_desktop, 'Tor Browser', 'Browser', 'firefox.exe'),
            os.path.join(prog_files, 'Tor Browser', 'Browser', 'firefox.exe'),
            os.path.join(prog_files_x86, 'Tor Browser', 'Browser', 'firefox.exe'),
            os.path.join(local_appdata, 'Tor Browser', 'Browser', 'firefox.exe'),
        ]
        for path in tor_paths:
            add_if_exists("Tor Browser", path)

        # Registry fallbacks (keep existing code, but add version)
        try:
            import winreg
            # Chrome
            for key in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    reg_key = winreg.OpenKey(key, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe")
                    path, _ = winreg.QueryValueEx(reg_key, "")
                    winreg.CloseKey(reg_key)
                    if os.path.exists(path):
                        version = get_browser_version("Google Chrome", path)
                        browsers.append(("Google Chrome", version, path))
                except:
                    pass
            # Firefox
            try:
                reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Mozilla\Mozilla Firefox")
                version_key = winreg.EnumKey(reg_key, 0)
                winreg.CloseKey(reg_key)
                reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Mozilla\Mozilla Firefox\{version_key}\Main")
                path, _ = winreg.QueryValueEx(reg_key, "PathToExe")
                winreg.CloseKey(reg_key)
                if os.path.exists(path):
                    version = get_browser_version("Mozilla Firefox", path)
                    browsers.append(("Mozilla Firefox", version, path))
            except:
                pass
            # Edge
            try:
                reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe")
                path, _ = winreg.QueryValueEx(reg_key, "")
                winreg.CloseKey(reg_key)
                if os.path.exists(path):
                    version = get_browser_version("Microsoft Edge", path)
                    browsers.append(("Microsoft Edge", version, path))
            except:
                pass
            # Brave
            try:
                reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BraveSoftware\Brave-Browser")
                version_key = winreg.EnumKey(reg_key, 0)
                winreg.CloseKey(reg_key)
                reg_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\BraveSoftware\Brave-Browser\{version_key}\Main")
                path, _ = winreg.QueryValueEx(reg_key, "PathToExe")
                winreg.CloseKey(reg_key)
                if os.path.exists(path):
                    version = get_browser_version("Brave", path)
                    browsers.append(("Brave", version, path))
            except:
                pass
        except ImportError:
            pass

    elif IS_MAC:
        # Applications folders
        app_dirs = ['/Applications', os.path.expanduser('~/Applications')]
        for app_dir in app_dirs:
            if not os.path.isdir(app_dir):
                continue
            # Existing browsers
            add_if_exists("Google Chrome", os.path.join(app_dir, 'Google Chrome.app'))
            add_if_exists("Mozilla Firefox", os.path.join(app_dir, 'Firefox.app'))
            add_if_exists("Safari", os.path.join(app_dir, 'Safari.app'))
            add_if_exists("Microsoft Edge", os.path.join(app_dir, 'Microsoft Edge.app'))
            add_if_exists("Brave Browser", os.path.join(app_dir, 'Brave Browser.app'))
            add_if_exists("Opera", os.path.join(app_dir, 'Opera.app'))
            add_if_exists("Vivaldi", os.path.join(app_dir, 'Vivaldi.app'))
            # Floorp
            add_if_exists("Floorp", os.path.join(app_dir, 'Floorp.app'))
            # Orion (macOS only)
            add_if_exists("Orion", os.path.join(app_dir, 'Orion.app'))
            # Tor Browser
            add_if_exists("Tor Browser", os.path.join(app_dir, 'Tor Browser.app'))

    else:  # Linux (including Termux)
        # Use 'which' to find common browser executables in PATH
        browser_commands = [
            ("Google Chrome", ["google-chrome", "google-chrome-stable"]),
            ("Chromium", ["chromium", "chromium-browser"]),
            ("Mozilla Firefox", ["firefox"]),
            ("Microsoft Edge", ["microsoft-edge", "microsoft-edge-stable"]),
            ("Brave", ["brave-browser"]),
            ("Opera", ["opera"]),
            ("Vivaldi", ["vivaldi"]),
            ("Floorp", ["floorp"]),
            ("Tor Browser", ["torbrowser-launcher"]),  # launcher script
        ]
        for name, commands in browser_commands:
            for cmd in commands:
                try:
                    path = subprocess.check_output(['which', cmd], text=True, stderr=subprocess.DEVNULL).strip()
                    if path and os.path.exists(path):
                        version = get_browser_version(name, path)
                        browsers.append((name, version, path))
                        break
                except:
                    pass

        # Additional manual installation paths for Tor Browser (often extracted)
        home = os.path.expanduser('~')
        tor_manual_paths = [
            os.path.join(home, 'tor-browser', 'Browser', 'firefox'),
            os.path.join(home, 'tor-browser', 'firefox'),
            '/opt/tor-browser/Browser/firefox',
            os.path.join(home, '.local', 'share', 'torbrowser', 'tbb', 'firefox'),
        ]
        for path in tor_manual_paths:
            if os.path.exists(path):
                version = get_browser_version("Tor Browser", path)
                browsers.append(("Tor Browser", version, path))
                break  # avoid duplicates

        # Check snap packages
        snap_paths = [
            ("Chromium", "/snap/bin/chromium"),
            ("Firefox", "/snap/bin/firefox"),
            ("Brave", "/snap/bin/brave"),
            ("Floorp", "/snap/bin/floorp"),           # if exists
            ("Tor Browser", "/snap/bin/torbrowser-launcher"),
        ]
        for name, path in snap_paths:
            if os.path.exists(path):
                version = get_browser_version(name, path)
                browsers.append((name, version, path))

        # Check flatpak packages (common IDs)
        flatpak_base = '/var/lib/flatpak/exports/bin'
        if os.path.isdir(flatpak_base):
            flatpak_apps = [
                ("Chromium", "org.chromium.Chromium"),
                ("Firefox", "org.mozilla.firefox"),
                ("Brave", "brave"),                   # may vary
                ("Floorp", "net.floorp.Floorp"),       # typical ID
                ("Tor Browser", "org.torproject.torbrowser-launcher"),
            ]
            for name, app_id in flatpak_apps:
                path = os.path.join(flatpak_base, app_id)
                if os.path.exists(path):
                    version = get_browser_version(name, path)
                    browsers.append((name, version, path))

    # Remove duplicates (same name and path)
    unique = {}
    for name, version, path in browsers:
        unique[(name, path)] = (name, version, path)
    browsers = list(unique.values())

    return browsers

# ----------------------------------------------------------------------
# New function: get_listening_ports()
# ----------------------------------------------------------------------

def get_listening_ports():
    """
    Detect listening TCP/UDP ports.
    Returns a list of rows: [protocol, local_address, remote_address, state, process]
    Works on Linux, macOS, Windows.
    """
    rows = []
    system = platform.system()

    if system == 'Linux':
        # Use ss (modern)
        try:
            if is_admin():
                cmd = ['ss', '-tulnp']  # includes process
            else:
                cmd = ['ss', '-tuln']
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            lines = output.splitlines()
            for line in lines:
                if line.startswith('Netid') or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    netid = parts[0]
                    state = parts[1]
                    local = parts[4]
                    remote = parts[5] if len(parts) > 5 else ''
                    process = ''
                    if len(parts) > 6:
                        process = ' '.join(parts[6:])
                    if 'LISTEN' in state:
                        rows.append([netid, local, remote, state, process])
        except (subprocess.SubprocessError, FileNotFoundError):
            # Fallback to netstat
            try:
                cmd = ['netstat', '-tuln']
                output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                lines = output.splitlines()
                for line in lines:
                    if 'Active' in line or 'Proto' in line or not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 4:
                        proto = parts[0]
                        local = parts[3]
                        remote = parts[4] if len(parts) > 4 else ''
                        state = parts[5] if len(parts) > 5 else ''
                        if 'LISTEN' in state or proto.startswith('udp'):
                            rows.append([proto, local, remote, state, ''])
            except:
                pass

    elif system == 'Darwin':  # macOS
        try:
            # lsof is common on macOS
            cmd = ['lsof', '-i', '-P', '-n', '-sTCP:LISTEN']
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
            lines = output.splitlines()
            for line in lines:
                if line.startswith('COMMAND') or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    command = parts[0]
                    pid = parts[1]
                    # name field is usually the last part, format like *:port or IP:port
                    name = parts[8]
                    rows.append(['tcp', name, '', 'LISTEN', f"{command}({pid})"])
        except:
            # Fallback to netstat
            try:
                cmd = ['netstat', '-an']
                output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
                lines = output.splitlines()
                for line in lines:
                    if 'Proto' in line or not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 4:
                        proto = parts[0]
                        local = parts[3]
                        remote = parts[4]
                        state = parts[5] if len(parts) > 5 else ''
                        if 'LISTEN' in state:
                            rows.append([proto, local, remote, state, ''])
            except:
                pass

    elif system == 'Windows':
        try:
            cmd = ['netstat', '-an']
            output = subprocess.check_output(cmd, text=True, encoding='oem', stderr=subprocess.DEVNULL)
            lines = output.splitlines()
            for line in lines:
                if 'Proto' in line or not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 4:
                    proto = parts[0]
                    local = parts[1]
                    remote = parts[2]
                    state = parts[3] if len(parts) > 3 else ''
                    if 'LISTENING' in state:
                        rows.append([proto, local, remote, state, ''])
        except:
            pass

    return rows

# ----------------------------------------------------------------------
# New function: get_active_mac()
# ----------------------------------------------------------------------

def get_active_mac():
    """
    Return the MAC address of the network interface used for the default route
    (i.e., the interface connected to the internet). Returns "N/A" if not found.
    Works on Linux, macOS, Windows.
    """
    system = platform.system()
    iface = None

    # 1. Find the default route interface
    if system == 'Linux':
        try:
            # Use 'ip route' to get default via interface
            out = subprocess.check_output(['ip', 'route', 'show', 'default'], text=True, stderr=subprocess.DEVNULL)
            # Typical output: "default via 192.168.1.1 dev wlp2s0 proto dhcp metric 600"
            match = re.search(r'dev\s+(\S+)', out)
            if match:
                iface = match.group(1)
        except:
            pass
        if not iface:
            try:
                # Fallback to 'route -n'
                out = subprocess.check_output(['route', '-n'], text=True, stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    if line.startswith('0.0.0.0'):
                        parts = line.split()
                        if len(parts) >= 8:
                            iface = parts[7]  # last column is interface name
                            break
            except:
                pass

    elif system == 'Darwin':  # macOS
        try:
            # 'route -n get default' gives interface
            out = subprocess.check_output(['route', '-n', 'get', 'default'], text=True, stderr=subprocess.DEVNULL)
            match = re.search(r'interface:\s+(\S+)', out)
            if match:
                iface = match.group(1)
        except:
            pass

    elif system == 'Windows':
        try:
            # Use PowerShell to get the interface with default gateway
            cmd = ['powershell', '-Command', 
                   'Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Select-Object -ExpandProperty InterfaceAlias']
            out = subprocess.check_output(cmd, text=True, encoding='oem', stderr=subprocess.DEVNULL).strip()
            if out:
                iface = out.splitlines()[0]
        except:
            pass
        if not iface:
            try:
                # Fallback to 'route print -4'
                out = subprocess.check_output(['route', 'print', '-4'], text=True, encoding='oem', stderr=subprocess.DEVNULL)
                in_table = False
                for line in out.splitlines():
                    if 'Active Routes:' in line:
                        in_table = True
                        continue
                    if in_table and line.strip() and not line.startswith('='):
                        parts = line.split()
                        if len(parts) >= 5 and parts[0] == '0.0.0.0':
                            # The interface name is the last column (sometimes after metric)
                            # Format: Network Destination  Netmask  Gateway  Interface  Metric
                            # We'll take the interface column (4th index)
                            if len(parts) >= 5:
                                iface = parts[4]
                                break
            except:
                pass

    # 2. If we have the interface name, get its MAC address
    if iface:
        mac = None
        if system == 'Linux':
            try:
                with open(f'/sys/class/net/{iface}/address', 'r') as f:
                    mac = f.read().strip()
            except:
                pass
        elif system == 'Darwin':
            try:
                out = subprocess.check_output(['ifconfig', iface], text=True, stderr=subprocess.DEVNULL)
                # Look for 'ether' line
                for line in out.splitlines():
                    if 'ether' in line:
                        parts = line.split()
                        # typical: "ether 00:11:22:33:44:55"
                        if len(parts) >= 2:
                            mac = parts[1]
                            break
            except:
                pass
        elif system == 'Windows':
            try:
                # Use getmac command filtered by interface name
                # getmac /FO CSV /NH gives lines like "00-11-22-33-44-55","Intel(R) ..."
                out = subprocess.check_output(['getmac', '/FO', 'CSV', '/NH'], text=True, encoding='oem', stderr=subprocess.DEVNULL)
                for line in out.splitlines():
                    if iface.lower() in line.lower():
                        # CSV format: "MAC","Name","Transport Name"
                        parts = line.strip('"').split('","')
                        if len(parts) >= 1:
                            mac = parts[0].replace('-', ':')  # convert to colon format
                            break
            except:
                pass

        if mac:
            return mac
        else:
            # Fallback: try to get MAC from psutil
            try:
                addrs = psutil.net_if_addrs()
                if iface in addrs:
                    for addr in addrs[iface]:
                        if addr.family == psutil.AF_LINK:
                            return addr.address
            except:
                pass
            return "N/A"
    else:
        # No default interface found, maybe try the first non-loopback with MAC
        try:
            addrs = psutil.net_if_addrs()
            for name, addr_list in addrs.items():
                if name == 'lo' or name.startswith('lo'):
                    continue
                for addr in addr_list:
                    if addr.family == psutil.AF_LINK:
                        return addr.address
        except:
            pass
        return "N/A"

# ----------------------------------------------------------------------
# Existing helper functions (data retrieval) – unchanged
# (All functions from previous version remain exactly the same)
# ----------------------------------------------------------------------

def get_os_info():
    """Return tuple (os_name, os_version, kernel) for the current system."""
    if IS_WINDOWS:
        try:
            release = platform.release()          # e.g., '10'
            version = platform.version()          # e.g., '10.0.19045'
            # Try to detect Windows 11 based on build number
            build = int(version.split('.')[-1]) if '.' in version else 0
            os_name = "Windows 11" if build >= 22000 else "Windows 10"
            return os_name, version, version
        except:
            return "Windows", "Unknown", "Unknown"
    elif IS_MAC:
        try:
            name = subprocess.check_output(['sw_vers', '-productName'], text=True).strip()
            version = subprocess.check_output(['sw_vers', '-productVersion'], text=True).strip()
            kernel = subprocess.check_output(['uname', '-r'], text=True).strip()
            return name, version, kernel
        except:
            return "macOS", "Unknown", "Unknown"
    else:  # Linux (including Termux)
        os_name = "Linux"
        os_version = ""
        kernel = platform.release()
        # Try to get distribution info (works on most full Linux, may fail on Termux)
        try:
            with open('/etc/os-release', 'r') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        os_name = line.split('=', 1)[1].strip().strip('"')
                    elif line.startswith('VERSION_ID='):
                        os_version = line.split('=', 1)[1].strip().strip('"')
        except:
            # Termux often doesn't have /etc/os-release; fallback to "Android" if possible
            if os.path.exists('/data/data/com.termux'):
                os_name = "Android (Termux)"
                try:
                    with open('/system/build.prop', 'r') as f:
                        for line in f:
                            if line.startswith('ro.build.version.release='):
                                os_version = line.split('=')[1].strip()
                                break
                except:
                    pass
        return os_name, os_version, kernel

def get_uptime():
    """
    Return a formatted string of system uptime (days, hours, minutes, seconds).
    Uses psutil.boot_time() – works on all platforms where psutil is installed.
    """
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = int(time.time() - boot_time)
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if days > 0:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours > 0:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes > 0:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        return ", ".join(parts)
    except Exception as e:
        return "N/A"

def format_freq(freq_mhz):
    if freq_mhz >= 1000:
        return f"{freq_mhz/1000:.2f} GHz"
    else:
        return f"{freq_mhz:.0f} MHz"

def get_cpu_frequencies():
    try:
        freqs = psutil.cpu_freq(percpu=True)
    except Exception:
        try:
            single = psutil.cpu_freq(percpu=False)
            if single:
                return [format_freq(single.current)] * psutil.cpu_count()
        except Exception:
            pass
        return ["N/A"] * psutil.cpu_count()
    out = []
    for f in freqs:
        if f is None:
            out.append("N/A")
        else:
            out.append(format_freq(f.current))
    return out

def is_ssd(device):
    if IS_WINDOWS:
        return None
    if IS_MAC:
        disk = device.replace('/dev/', '').split('s')[0]
        try:
            output = subprocess.check_output(['diskutil', 'info', disk], text=True)
            if 'Solid State: Yes' in output or 'Rotational: No' in output:
                return True
            elif 'Solid State: No' in output or 'Rotational: Yes' in output:
                return False
            else:
                return None
        except:
            return None
    base = device.rstrip('0123456789')
    rotational_path = f"/sys/block/{os.path.basename(base)}/queue/rotational"
    try:
        with open(rotational_path, 'r') as f:
            return f.read().strip() == '0'
    except:
        return None

def get_cpu_temperatures():
    if IS_WINDOWS or IS_MAC:
        return "N/A"
    temps = psutil.sensors_temperatures()
    if not temps:
        return "N/A (no sensors)"
    out = []
    for sensor, entries in temps.items():
        for entry in entries:
            label = entry.label or sensor
            if 'core' in label.lower() or 'package' in label.lower() or sensor in ('coretemp', 'k10temp'):
                out.append(f"{label}: {entry.current:.1f}°C")
    if out:
        return ", ".join(out)
    first = next(iter(temps.values()))[0]
    return f"{first.label or 'CPU'}: {first.current:.1f}°C"

def get_fan_speeds():
    if IS_WINDOWS or IS_MAC:
        return "N/A"
    fans = psutil.sensors_fans()
    if not fans:
        return "N/A (no fan sensors)"
    out = []
    for label, entries in fans.items():
        for entry in entries:
            out.append(f"{entry.label or label}: {entry.current} RPM")
    return ", ".join(out)

def get_gpu_temperature():
    if IS_WINDOWS or IS_MAC:
        return "N/A"
    try:
        output = subprocess.check_output(
            ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'],
            text=True, stderr=subprocess.DEVNULL
        ).strip()
        if output:
            temps = output.splitlines()
            if len(temps) == 1:
                return f"{temps[0]}°C"
            else:
                return ", ".join([f"GPU{i}: {t}°C" for i, t in enumerate(temps)])
    except:
        pass
    try:
        for card in os.listdir('/sys/class/drm/'):
            if card.startswith('card'):
                hwmon_path = f'/sys/class/drm/{card}/device/hwmon'
                if os.path.exists(hwmon_path):
                    for hwmon in os.listdir(hwmon_path):
                        temp_input = f'{hwmon_path}/{hwmon}/temp1_input'
                        if os.path.exists(temp_input):
                            with open(temp_input, 'r') as f:
                                temp = int(f.read().strip()) / 1000.0
                                return f"{temp:.1f}°C"
    except:
        pass
    temps = psutil.sensors_temperatures()
    if temps:
        for sensor, entries in temps.items():
            for entry in entries:
                label = entry.label or sensor
                if 'gpu' in label.lower() or 'amdgpu' in sensor.lower():
                    return f"{label}: {entry.current:.1f}°C"
    return "N/A"

def get_gpu_utilization():
    """
    Return GPU utilization as a string (e.g., "GPU0: 45%, GPU1: 60%") or None if not available.
    Works on Linux and Windows with NVIDIA drivers (nvidia-smi) or AMD (rocm-smi).
    """
    if IS_WINDOWS:
        try:
            output = subprocess.check_output(
                ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            if output:
                util_vals = output.splitlines()
                if len(util_vals) == 1:
                    return f"GPU: {util_vals[0]}%"
                else:
                    return ", ".join([f"GPU{i}: {u}%" for i, u in enumerate(util_vals)])
        except:
            pass
        return None
    elif IS_MAC:
        return None
    else:  # Linux
        try:
            output = subprocess.check_output(
                ['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                text=True, stderr=subprocess.DEVNULL
            ).strip()
            if output:
                util_vals = output.splitlines()
                if len(util_vals) == 1:
                    return f"GPU: {util_vals[0]}%"
                else:
                    return ", ".join([f"GPU{i}: {u}%" for i, u in enumerate(util_vals)])
        except:
            pass
        try:
            output = subprocess.check_output(
                ['rocm-smi', '--showuse'],
                text=True, stderr=subprocess.DEVNULL
            )
            utils = []
            for line in output.splitlines():
                if 'GPU[' in line and '%' in line:
                    match = re.search(r'GPU\[\d+\]\s*:\s*(\d+)%', line)
                    if match:
                        utils.append(match.group(1))
            if utils:
                if len(utils) == 1:
                    return f"GPU: {utils[0]}%"
                else:
                    return ", ".join([f"GPU{i}: {u}%" for i, u in enumerate(utils)])
        except:
            pass
        return None

def get_battery_stats():
    battery = psutil.sensors_battery()
    if battery is None:
        return None
    percent = battery.percent
    if battery.power_plugged:
        status = "Fully charged" if percent >= 100 else "Charging"
    else:
        status = "Discharging"
    cycle_count = "N/A"
    if IS_LINUX:
        try:
            for bat in os.listdir('/sys/class/power_supply/'):
                if bat.startswith('BAT'):
                    cycle_path = f'/sys/class/power_supply/{bat}/cycle_count'
                    if os.path.exists(cycle_path):
                        with open(cycle_path, 'r') as f:
                            count = f.read().strip()
                            if count:
                                cycle_count = count
                            break
        except:
            pass
    elif IS_MAC:
        try:
            output = subprocess.check_output(['system_profiler', 'SPPowerDataType'], text=True, stderr=subprocess.DEVNULL)
            for line in output.splitlines():
                if 'Cycle Count' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        cycle_count = parts[1].strip()
                        break
        except:
            pass
    elif IS_WINDOWS:
        try:
            output = subprocess.check_output(
                ['wmic', 'path', 'Win32_Battery', 'get', 'CycleCount', '/format:csv'],
                text=True, encoding='oem', stderr=subprocess.DEVNULL
            )
            lines = output.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split(',')
                if len(parts) >= 2:
                    count = parts[1].strip()
                    if count:
                        cycle_count = count
        except:
            pass
    return percent, status, cycle_count

def get_npu_info():
    if IS_WINDOWS:
        try:
            cmd = [
                'powershell', '-Command',
                'Get-WmiObject Win32_PnPEntity | Where-Object { $_.Name -match \"NPU|neural|AI\" } | Select-Object -ExpandProperty Name'
            ]
            output = subprocess.check_output(cmd, text=True, encoding='oem', stderr=subprocess.DEVNULL).strip()
            if output:
                return output.splitlines()[0]
        except:
            pass
        return None
    elif IS_MAC:
        return "Apple Neural Engine" if platform.machine() == 'arm64' else None
    else:
        try:
            output = subprocess.check_output(['lspci'], text=True, stderr=subprocess.DEVNULL)
            for line in output.splitlines():
                if re.search(r'neural|npu|ai', line, re.I):
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
                    else:
                        return line.strip()
        except:
            pass
        if os.path.exists('/sys/class/intel_npu'):
            return "Intel NPU"
        try:
            output = subprocess.check_output(['lsmod'], text=True, stderr=subprocess.DEVNULL)
            if re.search(r'intel_npu|amd_npu', output, re.I):
                return "NPU module loaded"
        except:
            pass
        return None

def get_cpu_cache_info():
    if IS_WINDOWS:
        try:
            output = subprocess.check_output(
                ['wmic', 'cpu', 'get', 'L2CacheSize,L3CacheSize', '/format:csv'],
                text=True, encoding='oem', stderr=subprocess.DEVNULL
            )
            lines = output.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split(',')
                if len(parts) >= 3:
                    l2, l3 = parts[1].strip(), parts[2].strip()
                    caches = []
                    if l2 and l2 != '0':
                        caches.append(f"L2: {int(l2)//1024} KB")
                    if l3 and l3 != '0':
                        caches.append(f"L3: {int(l3)//1024} KB")
                    return ", ".join(caches) if caches else "N/A"
        except:
            pass
        return "N/A"
    elif IS_MAC:
        out = []
        for level in ['l1icache', 'l1dcache', 'l2cache', 'l3cache']:
            try:
                size = subprocess.check_output(['sysctl', '-n', f'hw.{level}size'], text=True).strip()
                if size and size != '0':
                    label = level.replace('cache', '').upper()
                    out.append(f"{label}: {int(size)//1024} KB")
            except:
                pass
        return ", ".join(out) if out else "N/A"
    else:
        try:
            caches = []
            base = '/sys/devices/system/cpu/cpu0/cache'
            if not os.path.exists(base):
                return "N/A"
            for idx in os.listdir(base):
                if not idx.startswith('index'):
                    continue
                level_file = f"{base}/{idx}/level"
                size_file = f"{base}/{idx}/size"
                if os.path.exists(level_file) and os.path.exists(size_file):
                    with open(level_file, 'r') as f:
                        level = f.read().strip()
                    with open(size_file, 'r') as f:
                        size = f.read().strip()
                    if level and size:
                        caches.append(f"L{level}: {size}")
            if caches:
                unique = {}
                for c in caches:
                    key = c.split(':')[0]
                    unique[key] = c
                return ", ".join(unique.values())
        except:
            pass
        return "N/A"

def get_audio_device_info():
    if IS_WINDOWS:
        try:
            output = subprocess.check_output(
                ['wmic', 'path', 'Win32_SoundDevice', 'get', 'Name', '/format:csv'],
                text=True, encoding='oem', stderr=subprocess.DEVNULL
            )
            lines = output.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split(',')
                if len(parts) >= 2:
                    return parts[1].strip()
        except:
            pass
        return "N/A"
    elif IS_MAC:
        try:
            output = subprocess.check_output(['system_profiler', 'SPAudioDataType'], text=True, stderr=subprocess.DEVNULL)
            for line in output.splitlines():
                if 'Output Device:' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        return parts[1].strip()
        except:
            pass
        return "N/A"
    else:
        try:
            output = subprocess.check_output(['aplay', '-l'], text=True, stderr=subprocess.DEVNULL)
            for line in output.splitlines():
                if 'card' in line and ':' in line:
                    parts = line.split(':')
                    if len(parts) >= 2:
                        return parts[1].split(',')[0].strip()
        except:
            pass
        try:
            with open('/proc/asound/cards', 'r') as f:
                for line in f:
                    if '[' in line and ']' in line:
                        match = re.search(r'\[(.*?)\]', line)
                        if match:
                            return match.group(1)
        except:
            pass
        return "N/A"

def get_monitor_info():
    monitors = []
    if IS_WINDOWS:
        try:
            output2 = subprocess.check_output(
                ['wmic', 'path', 'Win32_DisplayConfiguration', 'get', 'DeviceName,PelsWidth,PelsHeight,DisplayFrequency', '/format:csv'],
                text=True, encoding='oem', stderr=subprocess.DEVNULL
            )
            lines = output2.strip().splitlines()
            if len(lines) >= 2:
                for line in lines[1:]:
                    parts = line.split(',')
                    if len(parts) >= 5:
                        name = parts[1].strip() if parts[1] else "Unknown"
                        width = parts[2].strip() if parts[2] else "?"
                        height = parts[3].strip() if parts[3] else "?"
                        freq = parts[4].strip() if parts[4] else "?"
                        monitors.append(f"{name} {width}x{height} @{freq}Hz")
        except:
            pass
        if not monitors:
            monitors.append("N/A")
    elif IS_MAC:
        try:
            output = subprocess.check_output(['system_profiler', 'SPDisplaysDataType'], text=True, stderr=subprocess.DEVNULL)
            current = {}
            for line in output.splitlines():
                line = line.strip()
                if line.startswith('Display Type:'):
                    if current:
                        monitors.append(f"{current.get('name','Unknown')} {current.get('res','?')} @{current.get('hz','?')}Hz")
                    current = {}
                elif 'Resolution:' in line:
                    current['res'] = line.split(':',1)[1].strip()
                elif 'Refresh Rate:' in line:
                    hz = line.split(':',1)[1].strip().replace(' Hz','')
                    current['hz'] = hz
                elif line and ':' not in line and current:
                    current['name'] = line
            if current:
                monitors.append(f"{current.get('name','Unknown')} {current.get('res','?')} @{current.get('hz','?')}Hz")
            if not monitors:
                monitors.append("N/A")
        except:
            monitors.append("N/A")
    else:
        try:
            output = subprocess.check_output(['xrandr', '--current'], text=True, stderr=subprocess.DEVNULL)
            current = None
            for line in output.splitlines():
                if ' connected ' in line:
                    parts = line.split(' connected ')
                    name = parts[0].strip()
                    current = {'name': name}
                elif current and '*' in line:
                    match = re.search(r'(\d+x\d+)\s+(\d+\.?\d*)\*', line)
                    if match:
                        res = match.group(1)
                        hz = match.group(2)
                        monitors.append(f"{current['name']} {res} @{hz}Hz")
                        current = None
        except:
            pass
        if not monitors:
            monitors.append("N/A")
    return monitors

def get_cpu_name():
    if IS_WINDOWS:
        try:
            output = subprocess.check_output(
                ['wmic', 'cpu', 'get', 'name', '/format:csv'],
                text=True, encoding='oem'
            )
            lines = output.strip().splitlines()
            if len(lines) >= 2:
                return lines[1].split(',', 1)[-1].strip()
        except:
            pass
        return "Unknown CPU"
    if IS_MAC:
        try:
            return subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip()
        except:
            return "Unknown CPU"
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if 'model name' in line:
                    return line.split(':', 1)[1].strip()
    except:
        pass
    return "Unknown CPU"

def get_gpu_name():
    if IS_WINDOWS:
        try:
            output = subprocess.check_output(
                ['wmic', 'path', 'win32_VideoController', 'get', 'name', '/format:csv'],
                text=True, encoding='oem'
            )
            lines = output.strip().splitlines()
            if len(lines) >= 2:
                return lines[1].split(',', 1)[-1].strip()
        except:
            pass
        return "Unknown GPU"
    if IS_MAC:
        try:
            output = subprocess.check_output(['system_profiler', 'SPDisplaysDataType'], text=True)
            for line in output.splitlines():
                if 'Chipset Model:' in line:
                    return line.split('Chipset Model:', 1)[1].strip()
        except:
            pass
        return "Unknown GPU"
    try:
        output = subprocess.check_output(['lspci'], text=True)
        for line in output.splitlines():
            if 'VGA' in line or '3D' in line or 'Display' in line:
                parts = line.split(':', 2)
                if len(parts) >= 3:
                    return parts[2].strip()
                else:
                    return line.strip()
    except:
        pass
    return "Unknown GPU"

def get_system_model():
    if IS_WINDOWS:
        try:
            manufacturer = subprocess.check_output(
                ['wmic', 'computersystem', 'get', 'manufacturer', '/format:csv'],
                text=True, encoding='oem'
            ).strip().splitlines()
            model = subprocess.check_output(
                ['wmic', 'computersystem', 'get', 'model', '/format:csv'],
                text=True, encoding='oem'
            ).strip().splitlines()
            if len(manufacturer) >= 2 and len(model) >= 2:
                mfg = manufacturer[1].split(',', 1)[-1].strip()
                mdl = model[1].split(',', 1)[-1].strip()
                if mfg and mdl:
                    return f"{mfg} {mdl}"
        except:
            pass
        return "Unknown Windows PC"
    if IS_MAC:
        try:
            model = subprocess.check_output(['sysctl', '-n', 'hw.model'], text=True).strip()
            return f"Apple {model}"
        except:
            return "Unknown Mac"
    vendor = product = version = "Unknown"
    try:
        with open('/sys/class/dmi/id/sys_vendor', 'r') as f:
            vendor = f.read().strip()
    except:
        pass
    try:
        with open('/sys/class/dmi/id/product_name', 'r') as f:
            product = f.read().strip()
    except:
        pass
    try:
        with open('/sys/class/dmi/id/product_version', 'r') as f:
            version = f.read().strip()
    except:
        pass
    if vendor != "Unknown" or product != "Unknown":
        if version != "Unknown" and version not in product:
            return f"{vendor} {product} ({version})"
        else:
            return f"{vendor} {product}".strip()
    return "Unknown system"

# ----------------------------------------------------------------------
# Network functions
# ----------------------------------------------------------------------

def check_internet(timeout=2):
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        return True
    except:
        try:
            socket.create_connection(("1.1.1.1", 53), timeout=timeout)
            return True
        except:
            return False

def get_private_ips():
    ipv4_list = []
    ipv6_list = []
    addrs = psutil.net_if_addrs()
    for iface, sniclist in addrs.items():
        for snic in sniclist:
            if snic.family == socket.AF_INET:
                ip = snic.address
                if ip.startswith("127."):
                    continue
                try:
                    if ipaddress.ip_address(ip).is_private:
                        ipv4_list.append(f"{ip} ({iface})")
                except:
                    pass
            elif snic.family == socket.AF_INET6:
                ip = snic.address.split('%')[0]
                if ip == "::1":
                    continue
                try:
                    addr = ipaddress.ip_address(ip)
                    if addr.is_private or addr.is_link_local:
                        display = f"{snic.address} ({iface})" if '%' in snic.address else f"{ip} ({iface})"
                        ipv6_list.append(display)
                except:
                    pass
    return ", ".join(ipv4_list) if ipv4_list else "None", ", ".join(ipv6_list) if ipv6_list else "None"

def get_public_ip(version=4):
    urls_v4 = ["https://api.ipify.org", "https://ipv4.icanhazip.com", "https://v4.ident.me"]
    urls_v6 = ["https://api6.ipify.org", "https://ipv6.icanhazip.com", "https://v6.ident.me"]
    urls = urls_v4 if version == 4 else urls_v6
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return response.read().decode('utf-8').strip()
        except:
            continue
    return None

def get_public_ips():
    return get_public_ip(4), get_public_ip(6)

# ----------------------------------------------------------------------
# Improved table printing function – now with CENTERING!
# ----------------------------------------------------------------------

def get_terminal_width():
    try:
        return os.get_terminal_size().columns
    except:
        return 80

def truncate_string(s, max_len):
    """Truncate string to max_len, adding '...' if needed."""
    if len(s) <= max_len:
        return s
    return s[:max_len-3] + "..."

def print_table(title, headers, rows, col_colors=None):
    """
    Print a bordered table with title and optional column colors.
    - title: string (table title, will be colored with baby pink)
    - headers: list of header strings
    - rows: list of lists, each inner list contains strings for each column
    - col_colors: list of color codes for each column (applied to entire column)
    The entire table is CENTERED on the terminal.
    """
    if not rows and not headers:
        return

    # Ensure col_colors matches number of headers; if not, fill with default colors
    num_cols = len(headers)
    if not col_colors:
        col_colors = [COLORS[i % len(COLORS)] for i in range(num_cols)]
    elif len(col_colors) < num_cols:
        col_colors.extend([COLORS[(i+len(col_colors)) % len(COLORS)] for i in range(num_cols - len(col_colors))])

    # Determine column widths based on raw string lengths (without ANSI codes)
    MAX_COL_WIDTH = 70  # Slightly wider for readability on 1080p
    col_widths = []
    for i in range(num_cols):
        # Start with header length
        max_len = len(strip_ansi(headers[i]))
        for row in rows:
            if i < len(row):
                cell_len = len(strip_ansi(row[i]))
                if cell_len > max_len:
                    max_len = cell_len
        # Add padding (2 spaces) and cap at MAX_COL_WIDTH
        col_widths.append(min(max_len + 2, MAX_COL_WIDTH))

    total_width = sum(col_widths) + num_cols + 1  # +1 for left border

    # Center the table
    term_width = get_terminal_width()
    left_pad = max(0, (term_width - total_width) // 2)
    pad_spaces = ' ' * left_pad

    # Top border
    top = "┌" + "┬".join("─" * w for w in col_widths) + "┐"
    print(pad_spaces + color(top, BABY_PINK))

    # Title line
    if title:
        title_str = "│" + color(f" {title:^{total_width-2}} ", BABY_PINK) + "│"
        print(pad_spaces + title_str)
        sep = "├" + "┼".join("─" * w for w in col_widths) + "┤"
        print(pad_spaces + color(sep, BABY_PINK))

    # Headers
    header_cells = []
    for i, h in enumerate(headers):
        h_display = truncate_string(h, col_widths[i] - 2)
        header_cells.append(color(f" {h_display:<{col_widths[i]-1}}", col_colors[i]))
    print(pad_spaces + "│" + "│".join(header_cells) + "│")

    # Separator after headers
    sep = "├" + "┼".join("─" * w for w in col_widths) + "┤"
    print(pad_spaces + color(sep, BABY_PINK))

    # Rows
    for row in rows:
        padded_row = row + [''] * (num_cols - len(row))
        row_cells = []
        for i, cell in enumerate(padded_row):
            cell_display = truncate_string(cell, col_widths[i] - 2)
            row_cells.append(color(f" {cell_display:<{col_widths[i]-1}}", col_colors[i]))
        print(pad_spaces + "│" + "│".join(row_cells) + "│")

    # Bottom border
    bottom = "└" + "┴".join("─" * w for w in col_widths) + "┘"
    print(pad_spaces + color(bottom, BABY_PINK))

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def calculate_total_cache(cache_str):
    """
    Parse a cache string like "L1: 32K, L2: 256K, L3: 8192K" and return total KB as integer.
    If parsing fails, returns None.
    """
    if cache_str == "N/A" or not cache_str:
        return None
    total = 0
    # Find all numbers followed by K (or KB) and sum them
    matches = re.findall(r'(\d+)\s*K', cache_str, re.IGNORECASE)
    for match in matches:
        total += int(match)
    return total if total > 0 else None

def main():
    # First, attempt to elevate privileges (if not already elevated)
    elevate_privileges()

    refresh_interval = 45  # <-- changed from 20 to 45 seconds
    print("Rainbow system monitor (refreshes every 45 seconds – press Ctrl+C to exit)")
    time.sleep(1)

    # Static info (collected once, except uptime which is dynamic)
    cpu_name = get_cpu_name()
    gpu_name = get_gpu_name()
    system_model = get_system_model()
    npu_info = get_npu_info()
    cache_info = get_cpu_cache_info()
    audio_device = get_audio_device_info()
    os_name, os_version, kernel = get_os_info()

    try:
        while True:
            clear_screen()
            term_width = get_terminal_width()

            # Header banner (baby pink borders, text in yellow) – already centered
            banner = "=" * term_width
            print(color(banner, BABY_PINK))
            banner_text = "System Info for Terminal (macOS, Linux, Windows Powershell and Android via Termux) by Mayn Santos mayn@outlook.ph Feb 15, 2026"
            print(color(" " * ((term_width - len(banner_text)) // 2) + banner_text, f"{COLORS[1]};1"))
            print(color(banner, BABY_PINK))
            print(f"Last update: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

            # System info (dynamic parts: monitors and uptime)
            monitors = get_monitor_info()
            uptime = get_uptime()

            # Build system info list (static + dynamic)
            system_info = [
                ("OS", f"{os_name} {os_version}"),
                ("Kernel", kernel),
                ("Uptime", uptime),
                ("CPU", cpu_name),
                ("GPU", gpu_name),
                ("System", system_model),
                ("NPU", npu_info if npu_info else "Not detected"),
                ("Cache", cache_info),
            ]
            # Calculate and add total cache in KB
            total_cache_kb = calculate_total_cache(cache_info)
            if total_cache_kb is not None:
                system_info.append(("Total Cache (KB)", f"{total_cache_kb} KB"))
            else:
                system_info.append(("Total Cache (KB)", "N/A"))

            system_info.append(("Audio", audio_device))

            if monitors and monitors[0] != "N/A":
                for idx, mon in enumerate(monitors):
                    if idx == 0:
                        system_info.append(("Monitor", mon))
                    else:
                        system_info.append(("", mon))
            else:
                system_info.append(("Monitor", "N/A"))

            print_table("SYSTEM INFORMATION", ["Component", "Details"],
                        [[label, value] for label, value in system_info],
                        col_colors=[COLORS[3], COLORS[4]])
            print()

            # Network info
            internet = check_internet()
            internet_status = "Connected" if internet else "Disconnected"
            priv4, priv6 = get_private_ips()
            pub4, pub6 = get_public_ips()
            pub4_str = pub4 if pub4 else "N/A"
            pub6_str = pub6 if pub6 else "N/A"
            active_mac = get_active_mac()
            network_data = [
                ("Internet", internet_status),
                ("Private IPv4", priv4),
                ("Private IPv6", priv6),
                ("Public IPv4", pub4_str),
                ("Public IPv6", pub6_str),
                ("MAC Address (active)", active_mac),
            ]
            print_table("NETWORK", ["Item", "Details"],
                        [[item, value] for item, value in network_data],
                        col_colors=[COLORS[5], COLORS[0]])
            
            # Internet disconnected warning (centered manually)
            if internet_status == "Disconnected":
                warning = "⚠️  Please connect to Wi-Fi or LAN cable"
                print(color_bold(" " * ((term_width - len(strip_ansi(warning)))//2) + warning, HOT_PINK))
            print()

            # --- NEW: Listening Ports Section ---
            listening_ports = get_listening_ports()
            if listening_ports:
                # Prepare rows: protocol, local, remote, state, process
                port_rows = []
                for row in listening_ports:
                    # row format: [proto, local, remote, state, process]
                    port_rows.append([row[0], row[1], row[2], row[3], row[4]])
                print_table("LISTENING PORTS", ["Proto", "Local Address", "Remote Address", "State", "Process"],
                            port_rows, col_colors=[COLORS[0], COLORS[1], COLORS[2], COLORS[3], COLORS[4]])
            else:
                print_table("LISTENING PORTS", ["Info"], [["No listening ports found or unable to query"]])
            print()

            # Memory, CPU temp, fan, GPU temp, battery (compact table)
            mem = psutil.virtual_memory()
            mem_total = f"{mem.total//(1024**3)} GB"
            mem_used = f"{mem.used//(1024**3)} GB ({mem.percent:.1f}%)"
            mem_free = f"{mem.free//(1024**3)} GB"
            mem_avail = f"{mem.available//(1024**3)} GB"

            cpu_temp = get_cpu_temperatures()
            fan_speed = get_fan_speeds()
            gpu_temp = get_gpu_temperature()

            battery_data = []
            battery = get_battery_stats()
            if battery:
                percent, status, cycles = battery
                battery_data = [("Battery", f"{percent:.1f}%"), ("Status", status), ("Cycles", cycles)]

            # Combine into one table
            left_col = [
                ("Memory Total", mem_total),
                ("Memory Used", mem_used),
                ("Memory Free", mem_free),
                ("Memory Avail", mem_avail),
                ("CPU Temp", cpu_temp),
                ("Fan Speed", fan_speed),
                ("GPU Temp", gpu_temp),
            ]
            if battery_data:
                left_col.extend(battery_data)

            print_table("RESOURCE USAGE", ["Metric", "Value"],
                        [[label, value] for label, value in left_col],
                        col_colors=[COLORS[1], COLORS[2]])
            
            # Low RAM warning (centered)
            if mem.available < 512 * 1024 * 1024:  # 512 MB in bytes
                warning = f"⚠️  Low memory! Only {mem.available // (1024**2)} MB available"
                print(color_bold(" " * ((term_width - len(strip_ansi(warning)))//2) + warning, HOT_PINK))
            print()

            # CPU per core
            cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
            freqs = get_cpu_frequencies()
            core_rows = []
            cpu_overload_cores = []
            for i, (p, freq) in enumerate(zip(cpu_percent, freqs)):
                bar = '█' * int(p // 5) + '░' * (20 - int(p // 5))
                core_rows.append([f"Core {i}", f"{p:5.1f}%", bar, freq])
                if p >= 99:
                    cpu_overload_cores.append(str(i))
            print_table("CPU PER CORE", ["Core", "Usage", "Load Bar", "Frequency"],
                        core_rows, col_colors=[COLORS[3], COLORS[4], COLORS[5], COLORS[0]])

            # CPU overload warning (centered)
            if cpu_overload_cores:
                cores_str = ", ".join(cpu_overload_cores)
                warning = f"⚠️  CPU core{'s' if len(cpu_overload_cores)>1 else ''} {cores_str} at 99%+ utilisation"
                print(color_bold(" " * ((term_width - len(strip_ansi(warning)))//2) + warning, HOT_PINK))
            print()

            # GPU utilization
            gpu_util = get_gpu_utilization()
            if gpu_util:
                # Show utilization in a small line (left-aligned within centered table? We'll keep as is for now)
                print(f"📌 GPU UTILIZATION: {gpu_util}")
                util_values = re.findall(r'(\d+)%', gpu_util)
                overloaded = [f"GPU{i}" for i, val in enumerate(util_values) if int(val) >= 99]
                if overloaded:
                    gpu_str = ", ".join(overloaded)
                    warning = f"⚠️  {gpu_str} at 99%+ utilisation"
                    print(color_bold(" " * ((term_width - len(strip_ansi(warning)))//2) + warning, HOT_PINK))
                print()
            else:
                pass

            # Disk usage
            partitions = psutil.disk_partitions()
            disk_rows = []
            disk_warnings = []
            for part in partitions:
                if part.fstype in ('tmpfs', 'devtmpfs', 'squashfs', 'proc', 'sysfs',
                                   'fusectl', 'securityfs', 'cgroup', 'cgroup2',
                                   'pstore', 'bpf', 'configfs', 'debugfs', 'tracefs',
                                   'hugetlbfs', 'mqueue', 'devpts', 'autofs', 'binfmt_misc'):
                    continue
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    ssd = is_ssd(part.device)
                    drive_type = "SSD" if ssd is True else "HDD" if ssd is False else "unknown"
                    total = f"{usage.total // (1024**3)} GB"
                    used = f"{usage.used // (1024**3)} GB"
                    free = f"{usage.free // (1024**3)} GB"
                    used_percent = f"{usage.percent:.1f}%"
                    disk_rows.append([
                        part.device,
                        part.mountpoint,
                        part.fstype.upper(),
                        drive_type,
                        total,
                        used,
                        free,
                        used_percent
                    ])
                    if usage.percent >= 97:
                        disk_warnings.append(f"{part.mountpoint} is {usage.percent:.1f}% full")
                except:
                    continue
            if disk_rows:
                disk_colors = [COLORS[(i+1) % len(COLORS)] for i in range(8)]
                print_table("DISK USAGE", ["Device", "Mount", "FS Type", "Drive", "Total", "Used", "Free", "Used%"],
                            disk_rows, col_colors=disk_colors)
            else:
                print_table("DISK USAGE", ["Info"], [["No physical partitions found"]])

            # Disk space warnings (centered)
            if disk_warnings:
                for warn in disk_warnings:
                    print(color_bold(" " * ((term_width - len(strip_ansi(warn)))//2) + f"⚠️  {warn}", HOT_PINK))
            print()

            # Disk temperatures
            disk_temps = get_disk_temperatures()
            if disk_temps:
                temp_rows = [[device, f"{temp}°C"] for device, temp in disk_temps]
                print_table("DISK TEMPERATURES", ["Device", "Temperature"],
                            temp_rows, col_colors=[COLORS[4], COLORS[5]])
                # High disk temp warnings (centered)
                high_temp_warnings = [f"{dev} is {temp}°C" for dev, temp in disk_temps if temp > 60]
                if high_temp_warnings:
                    for warn in high_temp_warnings:
                        full_warn = f"⚠️  High disk temperature: {warn}"
                        print(color_bold(" " * ((term_width - len(strip_ansi(full_warn)))//2) + full_warn, HOT_PINK))
            else:
                print_table("DISK TEMPERATURES", ["Info"], [["No temperature data available"]])
            print()

            # Installed browsers (now with versions)
            browsers = get_installed_browsers()
            if browsers:
                browser_rows = [[name, version, path] for name, version, path in browsers]
                print_table("INSTALLED BROWSERS", ["Browser", "Version", "Install Path"],
                            browser_rows, col_colors=[COLORS[2], COLORS[3], COLORS[4]])
            else:
                print_table("INSTALLED BROWSERS", ["Info"], [["None detected"]])
            print()

            # Wait for next refresh
            remaining = refresh_interval - 1
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        clear_screen()
        print(color("\nMonitoring stopped. Goodbye! 🌈\n", f"{COLORS[3]};1"))
        sys.exit(0)

if __name__ == "__main__":
    main()