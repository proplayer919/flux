"""
Container image builder using debootstrap
"""

import os
import subprocess
import tempfile
import json
import uuid
import time
from pathlib import Path
from typing import Optional, Dict, Any
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel

from config import ContainerConfig

console = Console()


class BuildState:
    """Manages build state for continuation support"""

    def __init__(self, build_id: str, config: ContainerConfig, images_dir: Path):
        self.build_id = build_id
        self.config = config
        self.images_dir = images_dir
        self.state_dir = images_dir / ".build_states"
        self.state_dir.mkdir(exist_ok=True)
        self.state_file = self.state_dir / f"{build_id}.json"

        # Build steps
        self.steps = [
            "debootstrap",
            "packages",
            "custom_commands",
            "environment",
            "tarball",
        ]

        self.state = {
            "build_id": build_id,
            "config_name": config.name,
            "started_at": time.time(),
            "current_step": 0,
            "completed_steps": [],
            "failed_step": None,
            "temp_dir": None,
            "rootfs_path": None,
            "error_message": None,
        }

    def save_state(self):
        """Save current build state to disk"""
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=2)

    def load_state(self):
        """Load build state from disk"""
        if self.state_file.exists():
            with open(self.state_file, "r") as f:
                self.state = json.load(f)

    def mark_step_completed(self, step: str):
        """Mark a build step as completed"""
        if step not in self.state["completed_steps"]:
            self.state["completed_steps"].append(step)
        if step in self.steps:
            self.state["current_step"] = max(
                self.state["current_step"], self.steps.index(step) + 1
            )
        self.save_state()

    def mark_step_failed(self, step: str, error_message: str):
        """Mark a build step as failed"""
        self.state["failed_step"] = step
        self.state["error_message"] = error_message
        self.save_state()

    def get_next_step(self) -> Optional[str]:
        """Get the next step to execute"""
        if self.state["current_step"] < len(self.steps):
            return self.steps[self.state["current_step"]]
        return None

    def cleanup(self):
        """Clean up build state files"""
        if self.state_file.exists():
            self.state_file.unlink()

    @classmethod
    def load_from_id(cls, build_id: str, images_dir: Path) -> Optional["BuildState"]:
        """Load build state from build ID"""
        state_dir = images_dir / ".build_states"
        state_file = state_dir / f"{build_id}.json"

        if not state_file.exists():
            return None

        with open(state_file, "r") as f:
            state_data = json.load(f)

        # We need to recreate the config - this is a limitation
        # In a real implementation, we'd also save the config
        return None  # For now, we'll implement this later


class ImageBuilder:
    """Builds container images from configurations"""

    def __init__(self, images_dir: Optional[str] = None, verbose: bool = False):
        if images_dir:
            self.images_dir = Path(images_dir)
        else:
            # Use images directory relative to project root
            self.images_dir = Path(__file__).parent / "images"

        self.images_dir.mkdir(exist_ok=True)
        self.verbose = verbose
        self._current_build_state = None

    def build_image(
        self, config: ContainerConfig, continue_build_id: Optional[str] = None
    ) -> str:
        """Build a container image from configuration"""
        # Check if debootstrap is available
        if not self._check_debootstrap():
            raise RuntimeError(
                "debootstrap not found. Please install it: sudo apt install debootstrap"
            )

        # Check if running with sufficient privileges
        if os.geteuid() != 0:
            console.print(
                "[yellow]Note: Running without root privileges. Some operations may require sudo.[/yellow]"
            )

        # Initialize or load build state
        if continue_build_id:
            build_state = self._load_build_state(continue_build_id, config)
            if not build_state:
                raise RuntimeError(
                    f"Could not load build state for ID: {continue_build_id}"
                )
            console.print(
                f"[blue]Continuing build {continue_build_id} for {config.name}...[/blue]"
            )
        else:
            build_id = str(uuid.uuid4())[:8]
            build_state = BuildState(build_id, config, self.images_dir)
            console.print(
                f"[blue]Starting new build {build_id} for {config.name}...[/blue]"
            )

        self._current_build_state = build_state

        try:
            return self._execute_build_steps(build_state)
        except Exception as e:
            # Generate continuation code
            continuation_code = build_state.build_id
            build_state.mark_step_failed(
                build_state.get_next_step() or "unknown", str(e)
            )

            console.print(f"[red]Build failed: {e}[/red]")
            console.print(f"[yellow]To continue from where it left off, run:[/yellow]")
            console.print(f"[cyan]flux build-continue {continuation_code}[/cyan]")

            raise

    def _load_build_state(
        self, build_id: str, config: ContainerConfig
    ) -> Optional[BuildState]:
        """Load build state from ID"""
        build_state = BuildState(build_id, config, self.images_dir)
        state_file = build_state.state_file

        if not state_file.exists():
            return None

        build_state.load_state()
        return build_state

    def _execute_build_steps(self, build_state: BuildState) -> str:
        """Execute build steps with state management"""
        config = build_state.config

        # Create or reuse temporary directory
        if (
            build_state.state.get("temp_dir")
            and Path(build_state.state["temp_dir"]).exists()
        ):
            temp_dir = build_state.state["temp_dir"]
            rootfs_path = Path(build_state.state["rootfs_path"])
            console.print(f"[blue]Reusing existing build directory: {temp_dir}[/blue]")
        else:
            temp_dir = tempfile.mkdtemp(prefix=f"flux_build_{build_state.build_id}_")
            rootfs_path = Path(temp_dir) / "rootfs"

            # Create rootfs directory with proper permissions
            rootfs_path.mkdir(mode=0o755)
            os.chmod(temp_dir, 0o755)
            os.chmod(rootfs_path, 0o755)

            # Save temp dir info to state
            build_state.state["temp_dir"] = temp_dir
            build_state.state["rootfs_path"] = str(rootfs_path)
            build_state.save_state()

            console.print(f"[blue]Build directory: {temp_dir}[/blue]")

        try:
            # Execute build steps based on current state
            next_step = build_state.get_next_step()

            while next_step:
                console.print(f"[blue]Executing step: {next_step}[/blue]")

                if (
                    next_step == "debootstrap"
                    and "debootstrap" not in build_state.state["completed_steps"]
                ):
                    self._run_debootstrap(config, rootfs_path)
                    build_state.mark_step_completed("debootstrap")

                elif (
                    next_step == "packages"
                    and "packages" not in build_state.state["completed_steps"]
                ):
                    if config.packages:
                        self._install_packages(config, rootfs_path)
                    build_state.mark_step_completed("packages")

                elif (
                    next_step == "custom_commands"
                    and "custom_commands" not in build_state.state["completed_steps"]
                ):
                    if config.custom_commands:
                        self._run_custom_commands(config, rootfs_path)
                    build_state.mark_step_completed("custom_commands")

                elif (
                    next_step == "environment"
                    and "environment" not in build_state.state["completed_steps"]
                ):
                    self._setup_environment(config, rootfs_path)
                    build_state.mark_step_completed("environment")

                elif (
                    next_step == "tarball"
                    and "tarball" not in build_state.state["completed_steps"]
                ):
                    image_path = self._create_tarball(config, rootfs_path)
                    build_state.mark_step_completed("tarball")

                    # Clean up successful build
                    build_state.cleanup()

                    # Clean up temp directory
                    try:
                        subprocess.run(
                            ["sudo", "rm", "-rf", temp_dir],
                            check=True,
                            capture_output=True,
                        )
                    except:
                        console.print(
                            f"[yellow]Warning: Could not clean up temp directory {temp_dir}[/yellow]"
                        )

                    return image_path

                next_step = build_state.get_next_step()

            # If we get here, all steps are completed but no image was returned
            raise RuntimeError("Build completed but no image was created")

        except Exception as e:
            # Don't clean up temp directory on error so it can be resumed
            if "Operation not permitted" in str(e):
                console.print("[red]Permission denied error detected.[/red]")
                console.print(
                    "[yellow]This may be due to filesystem restrictions or insufficient privileges.[/yellow]"
                )
                console.print(
                    "[yellow]Try running with sudo or ensure /tmp is writable and allows exec.[/yellow]"
                )
            raise

    def continue_build(self, build_id: str, config: ContainerConfig) -> str:
        """Continue a failed build from where it left off"""
        return self.build_image(config, continue_build_id=build_id)

    def _check_debootstrap(self) -> bool:
        """Check if debootstrap is available"""
        try:
            subprocess.run(["which", "debootstrap"], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _run_debootstrap(self, config: ContainerConfig, rootfs_path: Path):
        """Run debootstrap to create base system"""
        console.print("[yellow]Running debootstrap...[/yellow]")

        # Map distribution to debootstrap suite
        suite_map = {
            "ubuntu": {
                "22.04": "jammy",
                "20.04": "focal",
                "18.04": "bionic",
                "24.04": "noble",
            },
            "debian": {
                "12": "bookworm",
                "11": "bullseye",
                "10": "buster",
                "bookworm": "bookworm",
                "bullseye": "bullseye",
            },
        }

        # Get suite name
        if config.distribution in suite_map:
            suite = suite_map[config.distribution].get(config.version, config.version)
        else:
            suite = config.version

        # Get mirror URL with fallbacks
        mirror_map = {
            "ubuntu": [
                "http://archive.ubuntu.com/ubuntu/",
                "http://us.archive.ubuntu.com/ubuntu/",
                "http://mirror.math.princeton.edu/pub/ubuntu/",
            ],
            "debian": [
                "http://deb.debian.org/debian/",
                "http://ftp.us.debian.org/debian/",
            ],
        }
        mirrors = mirror_map.get(config.distribution, [""])

        # Try each mirror until one works
        last_error = None
        for mirror in mirrors:
            try:
                console.print(f"[yellow]Trying mirror: {mirror}[/yellow]")
                self._run_debootstrap_with_mirror(config, rootfs_path, suite, mirror)
                return  # Success, exit the function
            except Exception as e:
                last_error = e
                console.print(f"[red]Mirror failed: {mirror}[/red]")
                continue

        # If all mirrors failed, raise the last error
        if last_error:
            raise last_error

    def _run_debootstrap_with_mirror(
        self, config: ContainerConfig, rootfs_path: Path, suite: str, mirror: str
    ):

        # Build debootstrap command
        cmd = [
            "sudo",
            "debootstrap",
            "--arch",
            config.architecture,
            "--variant=minbase",
            "--include=ca-certificates",  # Include certificates for HTTPS downloads
            "--components=main,universe",  # Include universe for Ubuntu
            suite,
            str(rootfs_path),
        ]

        if mirror:
            cmd.append(mirror)

        # Add timeout and retry options for better reliability
        env = os.environ.copy()
        env.update(
            {
                "DEBIAN_FRONTEND": "noninteractive",
                "APT_CONFIG": "/dev/null",  # Avoid user apt config interference
            }
        )

        if self.verbose:
            console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
            try:
                result = subprocess.run(
                    cmd, check=True, text=True, env=env, timeout=1800
                )  # 30 min timeout
                console.print("[green]✓ Base system created[/green]")
            except subprocess.TimeoutExpired:
                console.print(f"[red]debootstrap timed out after 30 minutes[/red]")
                raise RuntimeError("debootstrap timed out")
            except subprocess.CalledProcessError as e:
                console.print(f"[red]debootstrap failed: {e.stderr}[/red]")
                raise RuntimeError(f"debootstrap failed: {e.stderr}")
        else:
            # Run with progress indication
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Creating base system...", total=None)

                try:
                    result = subprocess.run(
                        cmd,
                        check=True,
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=1800,
                    )
                    progress.update(task, description="✓ Base system created")
                except subprocess.TimeoutExpired:
                    progress.update(
                        task, description="✗ Base system creation timed out"
                    )
                    raise RuntimeError("debootstrap timed out after 30 minutes")
                except subprocess.CalledProcessError as e:
                    progress.update(task, description="✗ Base system creation failed")
                    raise RuntimeError(f"debootstrap failed: {e.stderr}")

    def _install_packages(self, config: ContainerConfig, rootfs_path: Path):
        """Install packages in the container"""
        if not config.packages:
            return

        console.print(
            f"[yellow]Installing packages: {', '.join(config.packages)}[/yellow]"
        )

        # Create package installation script
        script_content = self._create_package_script(config)
        script_path = rootfs_path / "tmp" / "install_packages.sh"
        script_path.parent.mkdir(exist_ok=True)

        with open(script_path, "w") as f:
            f.write(script_content)

        script_path.chmod(0o755)

        # Run package installation in chroot
        cmd = ["sudo", "chroot", str(rootfs_path), "/tmp/install_packages.sh"]

        if self.verbose:
            console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
            try:
                result = subprocess.run(cmd, check=True, text=True)
                console.print("[green]✓ Packages installed[/green]")
            except subprocess.CalledProcessError as e:
                console.print(f"[red]Package installation error: {e.stderr}[/red]")
                raise RuntimeError(f"Package installation failed: {e.stderr}")
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Installing packages...", total=None)

                try:
                    result = subprocess.run(
                        cmd, check=True, capture_output=True, text=True
                    )
                    progress.update(task, description="✓ Packages installed")
                except subprocess.CalledProcessError as e:
                    progress.update(task, description="✗ Package installation failed")
                    console.print(f"[red]Package installation error: {e.stderr}[/red]")
                    raise RuntimeError(f"Package installation failed: {e.stderr}")

        # Clean up
        script_path.unlink()

    def _create_package_script(self, config: ContainerConfig) -> str:
        """Create package installation script"""
        if config.distribution in ["ubuntu", "debian"]:
            return f"""#!/bin/bash
set -e

# Update package lists
apt-get update

# Install packages
apt-get install -y {' '.join(config.packages)}

# Clean up
apt-get clean
rm -rf /var/lib/apt/lists/*
"""
        elif config.distribution == "fedora":
            return f"""#!/bin/bash
set -e

# Install packages
dnf install -y {' '.join(config.packages)}

# Clean up
dnf clean all
"""
        elif config.distribution == "centos":
            return f"""#!/bin/bash
set -e

# Install packages
yum install -y {' '.join(config.packages)}

# Clean up
yum clean all
"""
        elif config.distribution == "alpine":
            return f"""#!/bin/sh
set -e

# Update package index
apk update

# Install packages
apk add {' '.join(config.packages)}

# Clean up
rm -rf /var/cache/apk/*
"""
        else:
            return f"""#!/bin/bash
set -e
echo "Package installation not supported for {config.distribution}"
"""

    def _run_custom_commands(self, config: ContainerConfig, rootfs_path: Path):
        """Run custom commands in the container"""
        if not config.custom_commands:
            return

        console.print("[yellow]Running custom commands...[/yellow]")

        # Create custom commands script
        script_content = "#!/bin/bash\nset -e\n\n" + "\n".join(config.custom_commands)
        script_path = rootfs_path / "tmp" / "custom_commands.sh"
        script_path.parent.mkdir(exist_ok=True)

        with open(script_path, "w") as f:
            f.write(script_content)

        script_path.chmod(0o755)

        # Run custom commands in chroot
        cmd = ["sudo", "chroot", str(rootfs_path), "/tmp/custom_commands.sh"]

        if self.verbose:
            console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
            try:
                result = subprocess.run(cmd, check=True, text=True)
                console.print("[green]✓ Custom commands executed[/green]")
            except subprocess.CalledProcessError as e:
                console.print(f"[red]Custom command error: {e.stderr}[/red]")
                raise RuntimeError(f"Custom commands failed: {e.stderr}")
        else:
            try:
                result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                console.print("[green]✓ Custom commands executed[/green]")
            except subprocess.CalledProcessError as e:
                console.print(f"[red]Custom command error: {e.stderr}[/red]")
                raise RuntimeError(f"Custom commands failed: {e.stderr}")

        # Clean up
        script_path.unlink()

    def _setup_environment(self, config: ContainerConfig, rootfs_path: Path):
        """Set up environment in the container"""
        console.print("[yellow]Setting up environment...[/yellow]")

        # Create user if not root
        if config.user != "root":
            self._create_user(config, rootfs_path)

        # Set up environment variables
        if config.environment_vars:
            self._setup_env_vars(config, rootfs_path)

        # Set working directory
        if config.working_dir != "/":
            working_dir_path = rootfs_path / config.working_dir.lstrip("/")
            working_dir_path.mkdir(parents=True, exist_ok=True)

    def _create_user(self, config: ContainerConfig, rootfs_path: Path):
        """Create user in container"""
        script_content = f"""#!/bin/bash
set -e

# Create user
useradd -m -s /bin/bash {config.user}

# Set up sudo if available
if command -v sudo >/dev/null 2>&1; then
    usermod -aG sudo {config.user}
fi
"""

        script_path = rootfs_path / "tmp" / "create_user.sh"
        with open(script_path, "w") as f:
            f.write(script_content)

        script_path.chmod(0o755)

        cmd = ["sudo", "chroot", str(rootfs_path), "/tmp/create_user.sh"]

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            console.print(
                f"[yellow]Warning: Could not create user: {e.stderr}[/yellow]"
            )

        script_path.unlink()

    def _setup_env_vars(self, config: ContainerConfig, rootfs_path: Path):
        """Set up environment variables"""
        env_file = rootfs_path / "etc" / "environment"

        with open(env_file, "a") as f:
            for key, value in config.environment_vars.items():
                f.write(f"{key}={value}\n")

    def _create_tarball(self, config: ContainerConfig, rootfs_path: Path) -> str:
        """Create compressed tarball of the filesystem"""
        console.print("[yellow]Creating image tarball...[/yellow]")

        image_name = f"{config.name}-{config.distribution}-{config.version}.tar.gz"
        image_path = self.images_dir / image_name

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Compressing filesystem...", total=None)

            try:
                # Create tarball using tar command for better performance
                cmd = [
                    "sudo",
                    "tar",
                    "-czf",
                    str(image_path),
                    "-C",
                    str(rootfs_path),
                    ".",
                ]

                subprocess.run(cmd, check=True, capture_output=True)

                progress.update(task, description="✓ Image created")

            except subprocess.CalledProcessError as e:
                progress.update(task, description="✗ Image creation failed")
                raise RuntimeError(f"Failed to create tarball: {e.stderr}")

        return str(image_path)

    def list_images(self) -> list:
        """List all built images"""
        images = []
        for image_file in self.images_dir.glob("*.tar.gz"):
            stat = image_file.stat()
            images.append(
                {
                    "name": image_file.name,
                    "path": str(image_file),
                    "size": stat.st_size,
                    "created": stat.st_mtime,
                }
            )
        return sorted(images, key=lambda x: x["created"], reverse=True)

    def delete_image(self, image_name: str) -> bool:
        """Delete an image"""
        image_path = self.images_dir / image_name
        if image_path.exists():
            image_path.unlink()
            return True
        return False
