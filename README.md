SystemInfo.py – Real‑time system monitor for your terminal

This is a single‑file Python script that keeps an eye on your computer’s hardware and software: CPU, memory, disks, network, battery, browsers, listening ports, and more. It refreshes every 45 seconds and prints everything in neatly centred tables with baby‑pink borders and rainbow‑coloured text.

It runs on Linux (CachyOS, any distro), macOS, Windows 10/11 PowerShell, and Android (via Termux).

What it does:
CPU – per‑core utilisation, temperature, clock speed, and a simple load bar.

Memory – total, used, free, available, and a warning if it gets low.

GPU – name, temperature, utilisation (NVIDIA or AMD).

Disks – usage per partition, file system type, SSD/HDD detection, and disk temperatures (if smartctl is installed). Warnings at 97%+ full or above 60°C.

Network – internet connectivity, private IPv4/IPv6, public IPs, and the MAC address of the active interface (the one with the default route).

Listening ports – shows all TCP/UDP ports your machine is waiting for, plus the process that opened them (requires admin rights).

Battery – percentage, charge status, cycle count (where available).

NPU (Neural Processing Unit) – detects Intel NPU, Apple Neural Engine, or any AI‑accelerator hardware.

CPU cache – per‑level sizes and total in KB.

Audio device – primary sound card or output device.

Monitor(s) – resolution and refresh rate.

OS & kernel – distribution name, version, kernel release, and uptime.

Installed browsers – name, version, install path (supports Chrome, Firefox, Edge, Brave, Opera, Vivaldi, Floorp, Tor Browser, Safari, Orion, plus snaps and flatpaks).

Critical warnings – internet disconnection, low RAM, near‑full disks, CPU/GPU overload, high disk temperatures – all printed in bright pink and centred.

The script tries to elevate privileges (sudo/administrator) at startup – this gives you full process names for listening ports and disk temperatures. If elevation fails, it still runs, but those two sections will show less detail.

Why I made this? 
I wanted a single dashboard I could leave running in a terminal tab while I work – something that updates itself and catches my eye when something goes wrong (like a disk filling up or the CPU pegging 100%). I started with a few lines to show RAM and CPU, and it grew into this.

You’ll need
* Python 3.6+
* psutil – install it for your chosen OS.
* smartmontools (optional) – for disk temperatures. On Linux/macOS you probably already have it; on Windows you can grab it from smartmontools.org.

How to run:
1. Open Terminal
2. type:
   python3 SystemInfo.py
3.Hit Ctrl+C to stop it.
4. If you want to see full process names for listening ports or get disk temperatures, let the script request admin rights (it’ll prompt you).

Notes:
* The tables automatically centre themselves to your terminal width.
* Colours use ANSI escape codes – they work in any modern terminal (including Windows Terminal and PowerShell 7+).
* On Termux (Android), some features like smartctl won’t work, but CPU/memory/network still do.
* Public IP lookups use api.ipify.org and fallbacks; they’re cached for 45 seconds, so you won’t get rate‑limited.

License:
Do whatever you want with it. If you fix something, consider sharing it back. I consider this as a public domain python script.



