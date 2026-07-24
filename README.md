# ArchDomainJoin

Join Windows domain on Arch KDE with ease.

## Description

ArchDomainJoin is a Python utility designed to simplify the process of joining an Arch Linux system (with KDE Plasma desktop) to a Windows Active Directory domain. This tool automates the configuration and setup required for seamless domain integration on Arch KDE systems, including support for Plasma Login Manager.

## Features

- Automated Windows domain joining on Arch Linux
- Optimized for KDE Plasma desktop environment with Plasma Login Manager support
- User-friendly setup process
- Python-based implementation for portability
- Streamlined authentication integration

## Requirements

- Arch Linux system
- KDE Plasma desktop environment
- Python 3.x
- Active Directory domain credentials
- Required system packages (sssd, samba, krb5, etc.)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Imdabossou/ArchDomainJoin.git
cd ArchDomainJoin
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Ensure necessary system packages are installed:
```bash
sudo pacman -S sssd samba krb5
```

## Usage

Run the main script with appropriate permissions:

```bash
sudo python3 main.py
```

Follow the on-screen prompts to configure your domain settings and credentials.

## Configuration

The tool will guide you through:
- Domain name specification
- User credentials
- System hostname configuration
- Network settings
- Plasma Login Manager integration
