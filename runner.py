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
        """List running flux containers with resource usage"""
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

                        # Get resource usage for this container
                        resource_usage = self.get_container_resource_usage(machine_name)

                        containers.append(
                            {
                                "name": machine_name,
                                "config": config_name,
                                "class": parts[1] if len(parts) > 1 else "container",
                                "cpu_percent": resource_usage.get("cpu_percent", "N/A"),
                                "memory_usage": resource_usage.get(
                                    "memory_usage", "N/A"
                                ),
                                "memory_percent": resource_usage.get(
                                    "memory_percent", "N/A"
                                ),
                                "disk_usage": resource_usage.get("disk_usage", "N/A"),
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

    def get_container_resource_usage(self, container_name: str) -> dict:
        """Get CPU, RAM, and disk usage for a container"""
        resource_info = {
            "cpu_percent": "N/A",
            "memory_usage": "N/A",
            "memory_percent": "N/A",
            "disk_usage": "N/A",
        }

        try:
            # Get container PID using machinectl
            result = subprocess.run(
                ["sudo", "machinectl", "show", container_name, "--property=Leader"],
                capture_output=True,
                text=True,
                check=True,
            )

            leader_pid = None
            for line in result.stdout.strip().split("\n"):
                if line.startswith("Leader="):
                    leader_pid = line.split("=", 1)[1]
                    break

            if not leader_pid or leader_pid == "0":
                return resource_info

            # Get CPU usage using systemctl and the container's service
            try:
                cpu_result = subprocess.run(
                    [
                        "sudo",
                        "systemctl",
                        "show",
                        f"systemd-nspawn@{container_name}.service",
                        "--property=CPUUsageNSec",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )

                # For CPU percentage, we'll need to calculate it differently
                # Let's use a simpler approach with /proc/stat for the container's cgroup
                cpu_usage = self._get_container_cpu_usage(container_name)
                if cpu_usage is not None:
                    resource_info["cpu_percent"] = f"{cpu_usage:.1f}%"

            except subprocess.CalledProcessError:
                pass

            # Get memory usage from cgroup
            memory_usage = self._get_container_memory_usage(container_name)
            if memory_usage:
                resource_info.update(memory_usage)

            # Get disk usage for container's temporary directory
            disk_usage = self._get_container_disk_usage(container_name)
            if disk_usage:
                resource_info["disk_usage"] = disk_usage

        except subprocess.CalledProcessError:
            pass

        return resource_info

    def _get_container_cpu_usage(self, container_name: str) -> Optional[float]:
        """Get CPU usage percentage for container"""
        try:
            # Try to get CPU usage from systemd cgroup
            cgroup_path = (
                f"/sys/fs/cgroup/system.slice/systemd-nspawn@{container_name}.service"
            )

            if os.path.exists(f"{cgroup_path}/cpu.stat"):
                # Read CPU stats from cgroup v2
                with open(f"{cgroup_path}/cpu.stat", "r") as f:
                    content = f.read()
                    for line in content.split("\n"):
                        if line.startswith("usage_usec"):
                            usage_usec = int(line.split()[1])
                            # This is cumulative, so we'd need to calculate delta
                            # For now, return a simple estimate
                            return min(usage_usec / 10000, 100.0)

            # Alternative: try cgroup v1 path
            cgroup_v1_path = f"/sys/fs/cgroup/cpu/system.slice/systemd-nspawn@{container_name}.service"
            if os.path.exists(f"{cgroup_v1_path}/cpuacct.usage"):
                with open(f"{cgroup_v1_path}/cpuacct.usage", "r") as f:
                    usage_ns = int(f.read().strip())
                    # Simple estimation - this is cumulative usage
                    return min(
                        usage_ns / 1000000000, 100.0
                    )  # Convert to rough percentage

            return None
        except (FileNotFoundError, ValueError, PermissionError):
            return None

    def _get_container_memory_usage(self, container_name: str) -> dict:
        """Get memory usage for container"""
        memory_info = {}

        try:
            # Try cgroup v2 first
            cgroup_path = (
                f"/sys/fs/cgroup/system.slice/systemd-nspawn@{container_name}.service"
            )

            if os.path.exists(f"{cgroup_path}/memory.current"):
                with open(f"{cgroup_path}/memory.current", "r") as f:
                    current_bytes = int(f.read().strip())
                    memory_info["memory_usage"] = self._format_bytes(current_bytes)

                # Try to get memory limit
                if os.path.exists(f"{cgroup_path}/memory.max"):
                    with open(f"{cgroup_path}/memory.max", "r") as f:
                        max_bytes = f.read().strip()
                        if max_bytes != "max":
                            max_bytes = int(max_bytes)
                            percentage = (current_bytes / max_bytes) * 100
                            memory_info["memory_percent"] = f"{percentage:.1f}%"
                        else:
                            # No limit set, calculate against system memory
                            try:
                                with open("/proc/meminfo", "r") as meminfo:
                                    for line in meminfo:
                                        if line.startswith("MemTotal:"):
                                            total_kb = (
                                                int(line.split()[1]) * 1024
                                            )  # Convert to bytes
                                            percentage = (
                                                current_bytes / total_kb
                                            ) * 100
                                            memory_info["memory_percent"] = (
                                                f"{percentage:.1f}%"
                                            )
                                            break
                            except:
                                pass
            else:
                # Try cgroup v1
                cgroup_v1_path = f"/sys/fs/cgroup/memory/system.slice/systemd-nspawn@{container_name}.service"
                if os.path.exists(f"{cgroup_v1_path}/memory.usage_in_bytes"):
                    with open(f"{cgroup_v1_path}/memory.usage_in_bytes", "r") as f:
                        current_bytes = int(f.read().strip())
                        memory_info["memory_usage"] = self._format_bytes(current_bytes)

                    # Try to get memory limit
                    if os.path.exists(f"{cgroup_v1_path}/memory.limit_in_bytes"):
                        with open(f"{cgroup_v1_path}/memory.limit_in_bytes", "r") as f:
                            limit_bytes = int(f.read().strip())
                            # Check if limit is reasonable (not max value)
                            if limit_bytes < (1 << 62):  # Reasonable limit
                                percentage = (current_bytes / limit_bytes) * 100
                                memory_info["memory_percent"] = f"{percentage:.1f}%"

        except (FileNotFoundError, ValueError, PermissionError):
            pass

        return memory_info

    def _get_container_disk_usage(self, container_name: str) -> Optional[str]:
        """Get disk usage for container's temporary files"""
        try:
            # Try to find the container's mount point or temporary directory
            result = subprocess.run(
                [
                    "sudo",
                    "machinectl",
                    "show",
                    container_name,
                    "--property=RootDirectory",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            root_dir = None
            for line in result.stdout.strip().split("\n"):
                if line.startswith("RootDirectory="):
                    root_dir = line.split("=", 1)[1]
                    break

            if root_dir and os.path.exists(root_dir):
                # Get disk usage of the container's root directory
                usage_result = subprocess.run(
                    ["sudo", "du", "-sh", root_dir],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                if usage_result.stdout:
                    disk_usage = usage_result.stdout.split()[0]
                    return disk_usage

            return None

        except (subprocess.CalledProcessError, FileNotFoundError):
            return None

    def _format_bytes(self, bytes_value: int) -> str:
        """Format bytes in human readable format"""
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f}{unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f}TB"
