"""
Container runner using systemd-nspawn
"""

import os
import subprocess
import tempfile
import shutil
import signal
import atexit
import uuid
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel

from config import ContainerConfig

console = Console()


class ContainerRunner:
    """Runs containers using systemd-nspawn"""

    def __init__(self, images_dir: Optional[str] = None, verbose: bool = False):
        if images_dir:
            self.images_dir = Path(images_dir)
        else:
            # Use images directory relative to project root
            self.images_dir = Path(__file__).parent / "images"

        self.verbose = verbose
        self.temp_dirs = []  # Track temp directories for cleanup

        # Register cleanup on exit
        atexit.register(self._cleanup_all)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def run_container(self, config: ContainerConfig):
        """Run a container from configuration"""
        console.print(f"[blue]Starting container for {config.name}...[/blue]")

        # Check if systemd-nspawn is available
        if not self._check_systemd_nspawn():
            raise RuntimeError(
                "systemd-nspawn not found. Please install systemd-container: sudo apt install systemd-container"
            )

        # Find the image file
        image_path = self._find_image(config)
        if not image_path:
            raise RuntimeError(
                f"No image found for {config.name}. Run 'flux build {config.name}' first."
            )

        # Create temporary directory
        temp_dir = self._create_temp_dir()

        try:
            # Extract image
            self._extract_image(image_path, temp_dir)

            # Run container
            self._run_nspawn(config, temp_dir)

        finally:
            # Cleanup
            self._cleanup_temp_dir(temp_dir)

    def _check_systemd_nspawn(self) -> bool:
        """Check if systemd-nspawn is available"""
        try:
            subprocess.run(["which", "systemd-nspawn"], check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def _find_image(self, config: ContainerConfig) -> Optional[str]:
        """Find the image file for the configuration"""
        # Look for exact match first
        image_pattern = f"{config.name}-{config.distribution}-{config.version}.tar.gz"
        image_path = self.images_dir / image_pattern

        if image_path.exists():
            return str(image_path)

        # Look for any image with the config name
        for image_file in self.images_dir.glob(f"{config.name}-*.tar.gz"):
            return str(image_file)

        return None

    def _create_temp_dir(self) -> str:
        """Create temporary directory for container"""
        temp_dir = tempfile.mkdtemp(prefix="flux-container-")
        self.temp_dirs.append(temp_dir)
        console.print(f"[dim]Using temporary directory: {temp_dir}[/dim]")
        return temp_dir

    def _extract_image(self, image_path: str, temp_dir: str):
        """Extract container image to temporary directory"""
        console.print("[yellow]Extracting container image...[/yellow]")

        rootfs_path = Path(temp_dir) / "rootfs"
        rootfs_path.mkdir()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting filesystem...", total=None)

            try:
                # Extract using tar command
                cmd = ["tar", "-xzf", image_path, "-C", str(rootfs_path)]

                if self.verbose:
                    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
                    subprocess.run(cmd, check=True)
                    console.print("[green]✓ Filesystem extracted[/green]")
                else:
                    subprocess.run(cmd, check=True, capture_output=True)
                    progress.update(task, description="✓ Filesystem extracted")

            except subprocess.CalledProcessError as e:
                progress.update(task, description="✗ Extraction failed")
                raise RuntimeError(f"Failed to extract image: {e.stderr}")

    def _run_nspawn(self, config: ContainerConfig, temp_dir: str):
        """Run container with systemd-nspawn"""
        console.print("[green]Starting container...[/green]")
        console.print("[dim]Type 'exit' to leave the container[/dim]")
        console.print()

        rootfs_path = Path(temp_dir) / "rootfs"

        # Generate unique machine name to allow multiple instances
        unique_id = str(uuid.uuid4())[:8]
        machine_name = f"flux-{config.name}-{unique_id}"

        # Build systemd-nspawn command
        cmd = [
            "sudo",
            "systemd-nspawn",
            "--directory",
            str(rootfs_path),
            "--machine",
            machine_name,
        ]

        # Add user if specified
        if config.user != "root":
            cmd.extend(["--user", config.user])

        # Add working directory
        if config.working_dir != "/":
            cmd.extend(["--chdir", config.working_dir])

        # Add environment variables
        for key, value in config.environment_vars.items():
            cmd.extend(["--setenv", f"{key}={value}"])

        # Add port forwarding if specified
        for port in config.ports:
            cmd.extend(["--port", f"{port}"])

        # Add volume mounts if specified
        for volume in config.volumes:
            if ":" in volume:
                host_path, container_path = volume.split(":", 1)
                cmd.extend(["--bind", f"{host_path}:{container_path}"])

        # Add X11 forwarding if enabled
        if config.allow_x11:
            # Get DISPLAY environment variable
            display = os.environ.get("DISPLAY", ":0")
            cmd.extend(["--setenv", f"DISPLAY={display}"])

            # Bind mount X11 socket
            x11_socket = f"/tmp/.X11-unix"
            if os.path.exists(x11_socket):
                cmd.extend(["--bind", f"{x11_socket}:{x11_socket}"])

            # Allow access to X11 (this requires xhost to be available on host)
            # Note: We could run xhost +local: before container starts, but it's better
            # to let the user handle X11 permissions as needed
            console.print(
                "[yellow]Note: X11 forwarding enabled. You may need to run 'xhost +local:' on the host if you encounter permission issues.[/yellow]"
            )

        # Add shell
        cmd.append("/bin/bash")

        try:
            # Show container info panel
            x11_status = "Enabled" if config.allow_x11 else "Disabled"
            info_panel = Panel(
                f"[bold]Container: {config.name}[/bold]\n"
                f"Distribution: {config.distribution} {config.version}\n"
                f"User: {config.user}\n"
                f"Working Directory: {config.working_dir}\n"
                f"X11 Forwarding: {x11_status}",
                title="Container Information",
                border_style="green",
            )
            console.print(info_panel)
            console.print()

            # Run the container
            subprocess.run(cmd, check=False)

        except KeyboardInterrupt:
            console.print("\n[yellow]Container interrupted[/yellow]")
        except Exception as e:
            console.print(f"[red]Failed to run container: {e}[/red]")
            raise
        finally:
            console.print("\n[blue]Container exited[/blue]")

    def _cleanup_temp_dir(self, temp_dir: str):
        """Clean up temporary directory"""
        console.print("[yellow]Cleaning up temporary files...[/yellow]")

        try:
            # Remove from tracking list
            if temp_dir in self.temp_dirs:
                self.temp_dirs.remove(temp_dir)

            # Remove directory with sudo if needed (in case of permission issues)
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except PermissionError:
                    # Use sudo to remove if permission denied
                    subprocess.run(["sudo", "rm", "-rf", temp_dir], check=True)

                console.print("[green]✓ Temporary files cleaned up[/green]")

        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not clean up {temp_dir}: {e}[/yellow]"
            )

    def _cleanup_all(self):
        """Clean up all temporary directories"""
        for temp_dir in self.temp_dirs.copy():
            self._cleanup_temp_dir(temp_dir)

    def _signal_handler(self, signum, frame):
        """Handle interrupt signals"""
        console.print(f"\n[yellow]Received signal {signum}, cleaning up...[/yellow]")
        self._cleanup_all()
        exit(0)

    def list_running_containers(self) -> list:
        """List running flux containers"""
        try:
            result = subprocess.run(
                ["sudo", "machinectl", "list"],
                capture_output=True,
                text=True,
                check=True,
            )

            containers = []
            lines = result.stdout.strip().split("\n")[1:]  # Skip header

            for line in lines:
                if line.strip() and "flux-" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        machine_name = parts[0]
                        # Extract config name from machine name (flux-{config}-{uuid})
                        if machine_name.startswith("flux-"):
                            # Split by dash and take all parts except the last one (UUID)
                            name_parts = machine_name.split("-")
                            if len(name_parts) >= 3:
                                config_name = "-".join(
                                    name_parts[1:-1]
                                )  # Everything between flux- and -uuid
                            else:
                                config_name = (
                                    name_parts[1]
                                    if len(name_parts) > 1
                                    else machine_name
                                )
                        else:
                            config_name = machine_name

                        containers.append(
                            {
                                "name": machine_name,
                                "config": config_name,
                                "class": parts[1] if len(parts) > 1 else "container",
                            }
                        )

            return containers

        except subprocess.CalledProcessError:
            return []

    def stop_container(self, container_name: str) -> bool:
        """Stop a running container"""
        try:
            subprocess.run(
                ["sudo", "machinectl", "terminate", container_name],
                check=True,
                capture_output=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def get_container_info(self, container_name: str) -> Optional[dict]:
        """Get information about a running container"""
        try:
            result = subprocess.run(
                ["sudo", "machinectl", "show", container_name],
                capture_output=True,
                text=True,
                check=True,
            )

            info = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    info[key] = value

            return info

        except subprocess.CalledProcessError:
            return None
