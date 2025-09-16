# Flux

> Interactive Linux Container Configuration

## 🚀 Features

- **Interactive Configuration**: Step-by-step guided setup for container configurations
- **Multiple Linux Distributions**: Support for Ubuntu, Debian, Fedora, CentOS, and Alpine
- **Package Management**: Easy installation of packages during container creation
- **Custom Commands**: Execute custom commands during the build process
- **Environment Variables**: Configure environment variables for containers
- **Port Mapping**: Expose container ports to the host system
- **Volume Mounting**: Mount host directories into containers
- **X11 Forwarding**: Run GUI applications inside containers with X11 support
- **Build State Management**: Resume interrupted builds with state persistence
- **Image Pulling**: Pull (download) container images directly from URLs
- **Rich CLI Interface**: Beautiful, user-friendly command-line interface using Rich

## 📋 Requirements

### System Requirements

- Linux operating system
- Root/sudo privileges
- Python 3.8+
- `debootstrap` (for building container images)
- `systemd-container` (for running containers with systemd-nspawn)

### Installation Dependencies

#### Ubuntu/Debian

```bash
sudo apt update
sudo apt install debootstrap systemd-container python3 python3-pip
```

#### Fedora/CentOS

```bash
sudo dnf install debootstrap systemd-container python3 python3-pip
# or for older versions
sudo yum install debootstrap systemd-container python3 python3-pip
```

#### Arch Linux

```bash
sudo pacman -S debootstrap systemd python python-pip
```

## 🛠️ Installation

1. **If not installed, install [Polly](https://github.com/pollypm/polly) using the instructions in their repository.**
2. **Run `polly install https://github.com/proplayer919/flux.git`**

## 📖 Usage

Flux provides several commands to manage container configurations:

### Create a New Configuration

```bash
sudo flux create --name mycontainer
```

This will start an interactive session where you can configure:

- Linux distribution and version
- Target architecture
- Packages to install
- Custom commands to execute
- Environment variables
- Port mappings
- Volume mounts
- User settings
- X11 forwarding for GUI applications

### List Configurations

```bash
flux list
```

### Build a Container Image

```bash
sudo flux build mycontainer
```

### Run a Container

```bash
sudo flux run mycontainer
```

#### Performance Optimizations

For better I/O performance, you can enable piped terminal mode:

```bash
sudo flux run mycontainer --pipe-terminal
```

This flag enables piped terminal mode instead of the default interactive mode for better I/O performance in automated scenarios.

#### Run with X11 Forwarding

To run GUI applications inside the container, use the `--allow-x11` flag:

```bash
sudo flux run mycontainer --allow-x11
```

You can combine flags for GUI support with optimized I/O:

```bash
sudo flux run mycontainer --allow-x11 --pipe-terminal
```

This enables X11 forwarding, allowing you to run graphical applications from within the container. The container will have access to your host's X11 display server.

**Note**: You may need to grant X11 access permissions on your host system:

```bash
# Allow local connections to X11 server
xhost +local:

# To restore security after use (optional)
xhost -local:
```

### Show Configuration Details

```bash
flux show mycontainer
```

### Delete a Configuration

```bash
flux delete mycontainer
```

This will delete the configuration and all its associated built images.

### Pull Container Images

```bash
# Pull a container image from a URL
flux pull https://example.com/image.tar.gz

# Pull with a custom name
flux pull https://example.com/image.tar.gz --name myimage

# Show download info before pulling
flux pull https://example.com/image.tar.gz --info

# Force overwrite existing image
flux pull https://example.com/image.tar.gz --force
```

## 🏗️ Configuration Format

Configurations are stored as JSON files in the `configs/` directory. Here's an example configuration:

```json
{
  "name": "development",
  "distribution": "ubuntu",
  "version": "24.04",
  "architecture": "amd64",
  "packages": [
    "curl",
    "wget",
    "git",
    "vim",
    "htop",
    "build-essential",
    "python3",
    "python3-pip",
    "nodejs",
    "npm"
  ],
  "custom_commands": [
    "useradd -m developer",
    "echo 'developer ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers"
  ],
  "environment_vars": {
    "NODE_ENV": "development",
    "PATH": "/usr/local/bin:/usr/bin:/bin"
  },
  "ports": [3000, 8080],
  "volumes": ["/home/user/projects:/workspace"],
  "user": "developer",
  "working_dir": "/workspace",
  "allow_x11": false,
  "created_at": "2025-09-14T14:57:01.925702"
}
```

## 🐧 Supported Distributions

| Distribution | Versions            | Architecture Support |
| ------------ | ------------------- | -------------------- |
| Ubuntu       | 20.04, 22.04, 24.04 | amd64, arm64         |
| Debian       | 11, 12              | amd64, arm64, i386   |
| Fedora       | 38, 39, 40          | amd64, arm64         |
| CentOS       | 8, 9                | amd64, arm64         |
| Alpine       | 3.18, 3.19          | amd64, arm64         |

## 🔧 Advanced Usage

### Build State Management

Flux automatically saves build state, allowing you to resume interrupted builds:

```bash
# If a build fails or is interrupted, Flux will give a "continue code", which you can use to continue from where you left off once the error is fixed.
sudo flux build-continue <code>
```

### X11 Forwarding for GUI Applications

Flux supports X11 forwarding to run graphical applications inside containers. This feature allows you to use GUI programs like web browsers, text editors, or development tools from within the container environment.

#### Enabling X11 Forwarding

You can enable X11 forwarding in two ways:

1. **At runtime** using the `--allow-x11` flag:

   ```bash
   sudo flux run mycontainer --allow-x11
   ```

2. **In the configuration** by setting `allow_x11` to `true`:

   ```json
   {
     "name": "gui-container",
     "distribution": "ubuntu",
     "version": "24.04",
     "allow_x11": true,
     "packages": ["firefox", "gedit", "xterm"]
   }
   ```

#### Prerequisites

Before using X11 forwarding, ensure you have:

- An X11 server running on your host (usually automatic in desktop environments)
- The `DISPLAY` environment variable set (usually `:0` or `:1`)

#### Granting X11 Access

For security reasons, you may need to grant the container access to your X11 server:

```bash
# Allow local connections (required before running container)
xhost +local:

# Run your container with X11 forwarding
sudo flux run mycontainer --allow-x11

# Optionally restore X11 security after use
xhost -local:
```

#### Common X11 Applications

Here are some popular GUI applications you can install and run:

```json
{
  "packages": [
    "firefox",           // Web browser
    "code",              // VS Code (requires Microsoft repo)
    "gedit",             // Text editor
    "nautilus",          // File manager
    "gnome-terminal",    // Terminal emulator
    "gimp",              // Image editor
    "libreoffice",       // Office suite
    "vlc"                // Media player
  ]
}
```

#### Troubleshooting X11

- **"Cannot connect to display"**: Ensure `DISPLAY` is set and X11 server is running
- **Permission denied**: Run `xhost +local:` to grant access
- **Applications won't start**: Check if the application requires additional packages or fonts

### Custom Package Sources

For Debian/Ubuntu containers, you can configure custom package sources by adding them to custom commands:

```json
{
  "custom_commands": [
    "echo 'deb http://ppa.launchpad.net/custom/ppa/ubuntu focal main' > /etc/apt/sources.list.d/custom.list",
    "apt-key adv --keyserver keyserver.ubuntu.com --recv-keys KEYID",
    "apt update"
  ]
}
```

## 🏗️ Architecture

Flux consists of several key components:

- **CLI (`cli.py`)**: Command-line interface using Click framework
- **Config Manager (`config.py`)**: Handles configuration creation, validation, and management
- **Image Builder (`builder.py`)**: Builds container images using debootstrap
- **Container Runner (`runner.py`)**: Runs containers using systemd-nspawn
- **Shell Script (`flux.sh`)**: Wrapper script for elevated permissions

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-amazing-feature`
3. Make your changes and add tests
4. Commit your changes: `git commit -m 'Add amazing feature'`
5. Push to the branch: `git push origin feature-amazing-feature`
6. Open a Pull Request

### Code Style

- Follow PEP 8 for Python code
- Use type hints where appropriate
- Add docstrings to all functions and classes
- Keep functions small and focused

## 🐛 Troubleshooting

### Common Issues

#### Permission Denied

```bash
# Ensure you're running with sudo for build/run operations
sudo flux build mycontainer
```

#### Debootstrap Not Found

```bash
# Install debootstrap
sudo apt install debootstrap  # Ubuntu/Debian
sudo dnf install debootstrap  # Fedora
```

#### systemd-nspawn Not Found

```bash
# Install systemd-container
sudo apt install systemd-container  # Ubuntu/Debian
sudo dnf install systemd-container   # Fedora
```

#### Build Failures

- Check internet connectivity for package downloads
- Verify the distribution and version are correct
- Check disk space in the build directory
- Review custom commands for syntax errors

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [debootstrap](https://wiki.debian.org/Debootstrap) for Linux root filesystem creation
- [systemd-nspawn](https://www.freedesktop.org/software/systemd/man/systemd-nspawn.html) for container runtime
- [Rich](https://github.com/Textualize/rich) for beautiful terminal interfaces
- [Click](https://click.palletsprojects.com/) for command-line interface framework
- [Pydantic](https://pydantic-docs.helpmanual.io/) for data validation

## 🔗 Links

- [Issue Tracker](https://github.com/proplayer919/flux/issues)

---

**Flux** - Making Linux container creation simple and interactive.
